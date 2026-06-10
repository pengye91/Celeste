"""
Durable execution engine with state replay (Tasks 5.1-5.2).

The Left Brain: a non-blocking asyncio DAG scheduler that:

- Submits DAG plans and persists them as Workflow / TaskNode records.
- Executes nodes respecting dependency ordering and a configurable
  concurrency semaphore (``MAX_PARALLEL_SUBPROCESSES``).
- Checkpoints every state transition as an immutable TaskEvent for
  audit and replay.
- On startup, performs **durable state replay**: reconstructs execution
  state from the TaskEvent ledger and resets orphaned "running" nodes
  back to "pending" so they can be re-scheduled.
- On node failure, triggers **Saga compensation** for all previously
  completed nodes that carry a ``compensation_command``.

Public API
----------
- ``Engine`` -- main entry point; ``start()`` / ``stop()`` lifecycle.
- ``submit_workflow(plan)`` -- persist a DAGPlan, return workflow UUID.
- ``run_workflow(workflow_id)`` -- execute a persisted workflow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from celeste_dag.config.settings import EngineSettings, get_settings
from celeste_dag.core.planner import DAGPlan
from celeste_dag.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste_dag.core.workspaces.local_tmp import LocalTmpWorkspace
from celeste_dag.database.db import close_db, get_session, init_db
from celeste_dag.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)


class Engine:
    """Left Brain: High-concurrency async DAG scheduler & durable state replayer."""

    def __init__(
        self,
        settings: EngineSettings | None = None,
        workspace_factory: Callable[[], BaseWorkspace] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._workspace_factory = workspace_factory or self._default_workspace_factory
        self._semaphore: asyncio.Semaphore | None = None
        self._running = False
        self._event_queue: asyncio.Queue[WorkspaceEvent] = asyncio.Queue()
        # Track active asyncio tasks for graceful cancellation
        self._active_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the engine.

        1. Initialise the database (create tables if needed).
        2. Create the concurrency semaphore.
        3. Perform durable state replay.
        4. Mark engine as running.
        """
        if self._running:
            return

        await init_db(settings=self._settings)
        self._semaphore = asyncio.Semaphore(self._settings.MAX_PARALLEL_SUBPROCESSES)
        await self._replay_state()
        self._running = True
        logger.info("Engine started (max_parallel=%d)", self._settings.MAX_PARALLEL_SUBPROCESSES)

    async def stop(self) -> None:
        """Gracefully stop the engine.

        Cancels in-flight tasks, then closes the database.
        Resets semaphore and event queue so a subsequent start() is clean.
        """
        if not self._running and not self._active_tasks:
            return

        # Cancel active tasks
        for task in list(self._active_tasks):
            if not task.done():
                task.cancel()

        # Wait for tasks to finish (with timeout)
        if self._active_tasks:
            await asyncio.wait(
                self._active_tasks,
                timeout=5.0,
                return_when=asyncio.ALL_COMPLETED,
            )
        self._active_tasks.clear()

        self._running = False
        self._semaphore = None
        self._event_queue = asyncio.Queue()
        await close_db()
        logger.info("Engine stopped")

    # ------------------------------------------------------------------
    # Workflow submission
    # ------------------------------------------------------------------

    async def submit_workflow(self, plan: DAGPlan) -> uuid.UUID:
        """Persist a ``DAGPlan`` as Workflow + TaskNode records.

        Returns the workflow UUID.
        """
        self._ensure_running()

        wf_id = uuid.uuid4()
        node_name_to_id: dict[str, uuid.UUID] = {}

        # Pre-assign UUIDs so we can build adjacency lists in one pass
        for node in plan.nodes:
            node_name_to_id[node.name] = uuid.uuid4()

        # Build serialisable DAG definition
        dag_def = json.loads(plan.model_dump_json())

        async with get_session() as session:
            workflow = Workflow(
                id=wf_id,
                name=plan.name,
                description=plan.description,
                status=WorkflowStatus.PENDING,
                dag_definition=dag_def,
            )
            session.add(workflow)

            for node in plan.nodes:
                prev_ids = [
                    str(node_name_to_id[dep])
                    for dep in node.dependencies
                    if dep in node_name_to_id
                ]
                next_ids: list[str] = []

                task_node = TaskNode(
                    id=node_name_to_id[node.name],
                    workflow_id=wf_id,
                    name=node.name,
                    task_type=node.task_type,
                    status=TaskNodeStatus.PENDING,
                    command=node.command,
                    arguments=node.arguments,
                    previous_node_ids=prev_ids,
                    next_node_ids=next_ids,
                    compensation_command=node.compensation_command,
                    compensation_arguments=node.compensation_arguments,
                )
                session.add(task_node)

            # Build next_node_ids mapping in-memory (before flush)
            next_map: dict[str, list[str]] = {str(node_name_to_id[n.name]): [] for n in plan.nodes}
            for node in plan.nodes:
                for dep in node.dependencies:
                    if dep in node_name_to_id:
                        parent_id = str(node_name_to_id[dep])
                        child_id = str(node_name_to_id[node.name])
                        if child_id not in next_map[parent_id]:
                            next_map[parent_id].append(child_id)

            # Now set next_node_ids on each task node (must re-query after flush)
            await session.flush()

            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_id)
            )
            all_nodes = result.scalars().all()
            for db_node in all_nodes:
                new_next = next_map.get(str(db_node.id), [])
                # Force SQLAlchemy to detect the change by assigning a new list
                flag_modified(db_node, "next_node_ids")
                db_node.next_node_ids = new_next

        logger.info("Submitted workflow %s (%s) with %d nodes", wf_id, plan.name, len(plan.nodes))
        return wf_id

    # ------------------------------------------------------------------
    # Workflow execution
    # ------------------------------------------------------------------

    async def run_workflow(self, workflow_id: uuid.UUID) -> None:
        """Execute a workflow by ID.

        Main loop:
        1. Find pending nodes whose dependencies are all completed.
        2. Execute them (respecting semaphore concurrency limit).
        3. Checkpoint state as TaskEvents.
        4. Repeat until all nodes completed or a failure occurs.
        5. On failure, trigger Saga compensation.
        """
        self._ensure_running()

        # Mark workflow as running
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")
            workflow.status = WorkflowStatus.RUNNING

        try:
            deadlock_wait_count = 0
            max_wait_iterations = 600  # 600 * 50ms = 30 seconds
            while True:
                ready_ids = await self._get_ready_nodes(workflow_id)
                if not ready_ids:
                    # Check if all nodes are in a terminal state
                    async with get_session() as session:
                        result = await session.execute(
                            select(TaskNode).where(TaskNode.workflow_id == workflow_id)
                        )
                        nodes = result.scalars().all()

                    all_done = all(
                        n.status in (TaskNodeStatus.COMPLETED, TaskNodeStatus.FAILED)
                        for n in nodes
                    )
                    any_failed = any(
                        n.status == TaskNodeStatus.FAILED for n in nodes
                    )

                    if all_done:
                        if any_failed:
                            await self._fail_workflow(workflow_id)
                        else:
                            await self._complete_workflow(workflow_id)
                        return

                    # There are still pending nodes but none are ready -- deadlock?
                    pending_exist = any(
                        n.status in (TaskNodeStatus.PENDING, TaskNodeStatus.RUNNING)
                        for n in nodes
                    )
                    if not pending_exist:
                        return
                    # Wait a bit and retry
                    await asyncio.sleep(0.05)
                    deadlock_wait_count += 1
                    if deadlock_wait_count >= max_wait_iterations:
                        raise RuntimeError(
                            f"Workflow {workflow_id} appears deadlocked after 30 seconds"
                        )
                    continue

                # Schedule ready nodes with semaphore
                tasks: list[asyncio.Task] = []
                for node_id in ready_ids:
                    task = asyncio.create_task(
                        self._run_node_under_semaphore(node_id, workflow_id)
                    )
                    tasks.append(task)
                    self._active_tasks.add(task)
                    task.add_done_callback(self._active_tasks.discard)

                # Wait for this batch to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Check for failures
                for r in results:
                    if isinstance(r, Exception):
                        # A node failed; trigger saga compensation
                        await self._handle_failure(workflow_id)
                        return

        except asyncio.CancelledError:
            logger.info("Workflow %s execution cancelled", workflow_id)
            raise

    async def _run_node_under_semaphore(
        self, node_id: uuid.UUID, workflow_id: uuid.UUID
    ) -> None:
        """Acquire semaphore and execute a single node."""
        if self._semaphore is None:
            raise RuntimeError("Engine semaphore not initialized; call start() first")
        async with self._semaphore:
            workspace = self._workspace_factory()
            async with workspace:
                await self._execute_node(node_id, workspace)

    # ------------------------------------------------------------------
    # Node execution
    # ------------------------------------------------------------------

    async def _execute_node(
        self, node_id: uuid.UUID, workspace: BaseWorkspace
    ) -> None:
        """Execute a single task node inside a workspace.

        1. Update node status to "running".
        2. Create TaskEvent "node_started".
        3. Execute command in workspace.
        4. Stream events and collect output.
        5. On success: update status to "completed", create "node_completed" event.
        6. On failure: update status to "failed", create "node_failed" event.
        """
        # Fetch the node and capture workflow_id while the session is active
        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.id == node_id)
            )
            node = result.scalar_one()
            wf_id = node.workflow_id  # Capture before session closes
            node.status = TaskNodeStatus.RUNNING

            session.add(
                TaskEvent(
                    task_node_id=node_id,
                    workflow_id=wf_id,
                    event_type=TaskEventType.NODE_STARTED,
                )
            )

        # Execute in workspace
        output_lines: list[str] = []
        failed = False
        failure_data: dict | None = None

        async for event in workspace.execute(node.command, node.arguments):
            await self._event_queue.put(event)
            if event.event_type == "stdout_line":
                output_lines.append(str(event.data))
            elif event.event_type == "execution_failed":
                failed = True
                failure_data = (
                    event.data if isinstance(event.data, dict) else {"error": str(event.data)}
                )

        output_text = "\n".join(output_lines)

        if failed:
            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(TaskNode.id == node_id)
                )
                node = result.scalar_one()
                node.status = TaskNodeStatus.FAILED
                node.outputs = output_text

                session.add(
                    TaskEvent(
                        task_node_id=node_id,
                        workflow_id=wf_id,
                        event_type=TaskEventType.NODE_FAILED,
                        event_data=failure_data,
                    )
                )

            logger.warning("Node %s (%s) failed", node_id, node.name)
            raise RuntimeError(
                f"Node '{node.name}' failed: {failure_data}"
            )
        else:
            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(TaskNode.id == node_id)
                )
                node = result.scalar_one()
                node.status = TaskNodeStatus.COMPLETED
                node.outputs = output_text

                session.add(
                    TaskEvent(
                        task_node_id=node_id,
                        workflow_id=wf_id,
                        event_type=TaskEventType.NODE_COMPLETED,
                    )
                )

            logger.info("Node %s (%s) completed", node_id, node.name)

    # ------------------------------------------------------------------
    # Ready node detection
    # ------------------------------------------------------------------

    async def _get_ready_nodes(self, workflow_id: uuid.UUID) -> list[uuid.UUID]:
        """Find pending nodes whose dependencies are all completed."""
        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(
                    TaskNode.workflow_id == workflow_id,
                    TaskNode.status == TaskNodeStatus.PENDING,
                )
            )
            pending_nodes = result.scalars().all()

            if not pending_nodes:
                return []

            # Fetch all nodes for this workflow to check dependency statuses
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == workflow_id)
            )
            all_nodes = result.scalars().all()

            # Build a map from id -> status
            node_status: dict[str, TaskNodeStatus] = {
                str(n.id): n.status for n in all_nodes
            }

            ready: list[uuid.UUID] = []
            for node in pending_nodes:
                if not node.previous_node_ids:
                    # No dependencies -- always ready
                    ready.append(node.id)
                else:
                    all_deps_completed = all(
                        node_status.get(dep_id) == TaskNodeStatus.COMPLETED
                        for dep_id in node.previous_node_ids
                    )
                    if all_deps_completed:
                        ready.append(node.id)

            return ready

    # ------------------------------------------------------------------
    # Durable state replay
    # ------------------------------------------------------------------

    async def _replay_state(self) -> None:
        """On startup, reconstruct execution state from TaskEvent ledger.

        1. Find all workflows with status "running".
        2. For each workflow, read TaskEvents to determine actual state.
        3. Reconstruct which nodes completed, which are pending.
        4. Resume execution from the last checkpoint.
        5. Do NOT re-execute completed nodes.
        """
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.status == WorkflowStatus.RUNNING)
            )
            running_workflows = result.scalars().all()

            if not running_workflows:
                logger.info("State replay: no running workflows to recover")
                return

            for workflow in running_workflows:
                logger.info(
                    "Replaying state for workflow %s (%s)",
                    workflow.id,
                    workflow.name,
                )
                await self._replay_workflow(session, workflow)

    async def _replay_workflow(
        self, session: AsyncSession, workflow: Workflow
    ) -> None:
        """Replay a single running workflow, resetting orphaned nodes."""
        result = await session.execute(
            select(TaskNode).where(TaskNode.workflow_id == workflow.id)
        )
        nodes = result.scalars().all()

        for node in nodes:
            if node.status == TaskNodeStatus.COMPLETED:
                # Completed nodes stay completed -- do not re-execute
                continue

            if node.status == TaskNodeStatus.RUNNING:
                # Check if there is a NODE_COMPLETED or NODE_FAILED event
                evt_result = await session.execute(
                    select(TaskEvent).where(
                        TaskEvent.task_node_id == node.id,
                        TaskEvent.event_type.in_([
                            TaskEventType.NODE_COMPLETED,
                            TaskEventType.NODE_FAILED,
                        ]),
                    )
                )
                terminal_events = evt_result.scalars().all()

                if any(e.event_type == TaskEventType.NODE_COMPLETED for e in terminal_events):
                    # Actually completed -- update status
                    node.status = TaskNodeStatus.COMPLETED
                    logger.info(
                        "Replay: node %s (%s) confirmed completed via events",
                        node.id,
                        node.name,
                    )
                elif any(e.event_type == TaskEventType.NODE_FAILED for e in terminal_events):
                    # Actually failed
                    node.status = TaskNodeStatus.FAILED
                    logger.info(
                        "Replay: node %s (%s) confirmed failed via events",
                        node.id,
                        node.name,
                    )
                else:
                    # No terminal event -- was running when crash happened.
                    # Reset to pending so it gets re-scheduled.
                    node.status = TaskNodeStatus.PENDING
                    logger.info(
                        "Replay: node %s (%s) reset to pending (no terminal event)",
                        node.id,
                        node.name,
                    )

            # PENDING and FAILED nodes keep their status

    # ------------------------------------------------------------------
    # Saga compensation
    # ------------------------------------------------------------------

    async def _handle_failure(self, workflow_id: uuid.UUID) -> None:
        """A node failed: trigger Saga compensation for completed nodes
        that have compensation commands, then mark workflow as failed.

        For each completed node with a compensation_command, this method:
        1. Records a COMPENSATION_TRIGGERED event.
        2. Actually executes the compensation command in a fresh workspace.
        3. Records COMPENSATION_COMPLETED or COMPENSATION_FAILED on outcome.
        """
        logger.warning("Handling failure for workflow %s", workflow_id)

        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == workflow_id)
            )
            nodes = result.scalars().all()

            # Find completed nodes with compensation commands (in reverse order)
            completed_with_compensation = [
                (n.id, n.name, n.compensation_command, n.compensation_arguments or {})
                for n in nodes
                if n.status == TaskNodeStatus.COMPLETED and n.compensation_command
            ]
            # Reverse so most recently completed is compensated first
            completed_with_compensation.reverse()

            for node_id, node_name, comp_cmd, comp_args in completed_with_compensation:
                session.add(
                    TaskEvent(
                        task_node_id=node_id,
                        workflow_id=workflow_id,
                        event_type=TaskEventType.COMPENSATION_TRIGGERED,
                        event_data={
                            "compensation_command": comp_cmd,
                            "compensation_arguments": comp_args,
                        },
                    )
                )
                logger.info(
                    "Compensation triggered for node %s (%s)",
                    node_id,
                    node_name,
                )

        # Execute compensation commands in a fresh workspace per node
        for node_id, node_name, comp_cmd, comp_args in completed_with_compensation:
            try:
                comp_workspace = self._workspace_factory()
                await comp_workspace.setup()
                try:
                    async for event in comp_workspace.execute(comp_cmd, comp_args):
                        await self._event_queue.put(event)

                    # Record successful compensation
                    async with get_session() as session:
                        session.add(
                            TaskEvent(
                                task_node_id=node_id,
                                workflow_id=workflow_id,
                                event_type=TaskEventType.COMPENSATION_COMPLETED,
                                event_data={
                                    "compensation_command": comp_cmd,
                                },
                            )
                        )
                    logger.info(
                        "Compensation completed for node %s (%s)",
                        node_id,
                        node_name,
                    )
                finally:
                    await comp_workspace.teardown()
            except Exception as e:
                # Best-effort compensation: log failure but continue
                logger.warning(
                    "Compensation failed for node %s (%s): %s",
                    node_id,
                    node_name,
                    e,
                )
                try:
                    async with get_session() as session:
                        session.add(
                            TaskEvent(
                                task_node_id=node_id,
                                workflow_id=workflow_id,
                                event_type=TaskEventType.COMPENSATION_FAILED,
                                event_data={
                                    "compensation_command": comp_cmd,
                                    "error": str(e),
                                },
                            )
                        )
                except Exception:
                    logger.warning(
                        "Failed to record compensation failure event for node %s",
                        node_id,
                    )

        await self._fail_workflow(workflow_id)

    # ------------------------------------------------------------------
    # Workflow terminal states
    # ------------------------------------------------------------------

    async def _complete_workflow(self, workflow_id: uuid.UUID) -> None:
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one()
            workflow.status = WorkflowStatus.COMPLETED
        logger.info("Workflow %s completed successfully", workflow_id)

    async def _fail_workflow(self, workflow_id: uuid.UUID) -> None:
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one()
            workflow.status = WorkflowStatus.FAILED
        logger.info("Workflow %s marked as failed", workflow_id)

    # ------------------------------------------------------------------
    # Workspace factory
    # ------------------------------------------------------------------

    def _default_workspace_factory(self) -> BaseWorkspace:
        """Create workspace based on settings.WORKSPACE_ENGINE."""
        engine_type = self._settings.WORKSPACE_ENGINE
        if engine_type == "local_tmp":
            return LocalTmpWorkspace()
        elif engine_type == "git_worktree":
            from celeste_dag.core.workspaces.git_worktree import GitWorktreeWorkspace
            return GitWorktreeWorkspace()
        elif engine_type == "docker":
            from celeste_dag.core.workspaces.docker import DockerWorkspace
            return DockerWorkspace()
        elif engine_type == "firecracker":
            from celeste_dag.core.workspaces.firecracker import FirecrackerWorkspace
            return FirecrackerWorkspace()
        else:
            raise ValueError(f"Unknown workspace engine: {engine_type}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_running(self) -> None:
        """Raise RuntimeError if the engine has not been started."""
        if not self._running:
            raise RuntimeError("Engine is not started. Call start() first.")
