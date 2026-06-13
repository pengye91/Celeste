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

from celeste.config.settings import EngineSettings, get_settings
from celeste.core.planner import DAGPlan
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.core.opa_loop import OPALoop, WorkflowResult
from celeste.core.workspaces.local_tmp import LocalTmpWorkspace
from celeste.database.db import close_db, get_session, init_db
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)
from celeste.tools.security_auditor import SecurityAuditor, SecurityVerdict

logger = logging.getLogger(__name__)


class Engine:
    """Left Brain: High-concurrency async DAG scheduler & durable state replayer."""

    def __init__(
        self,
        settings: EngineSettings | None = None,
        workspace_factory: Callable[[], BaseWorkspace] | None = None,
        security_auditor: SecurityAuditor | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._workspace_factory = workspace_factory or self._default_workspace_factory
        self._security_auditor = security_auditor
        self._semaphore: asyncio.Semaphore | None = None
        self._running = False
        self._event_queue: asyncio.Queue[WorkspaceEvent] = asyncio.Queue()
        # Track active asyncio tasks for graceful cancellation
        self._active_tasks: set[asyncio.Task] = set()

    def set_security_auditor(self, auditor: SecurityAuditor | None) -> None:
        """Inject a SecurityAuditor (SEC-002 / SEC-007).

        When set, every node command and every compensation command is
        audited before it reaches the workspace. ``None`` disables auditing
        (used by legacy / tests that don't need it).
        """
        self._security_auditor = auditor

    def _audit_or_block(self, command: str, context: str = "") -> None:
        """Run check_deterministic and raise if the verdict is unsafe.

        The Engine path runs synchronously per node, so we use the
        deterministic regex check (Phase 1). If a full LLM audit is desired,
        callers can invoke ``self._security_auditor.audit_command`` directly.
        """
        if self._security_auditor is None:
            return
        verdict: SecurityVerdict | None = self._security_auditor.check_deterministic(
            command
        )
        if verdict is not None and not verdict.is_safe:
            raise RuntimeError(
                f"Security audit blocked command ({context}): {verdict.reason} "
                f"(threats={verdict.detected_threats})"
            )

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

            # OBS-005: emit WORKFLOW_SUBMITTED TaskEvent so the audit trail
            # has a canonical "workflow started" marker. task_node_id is
            # required (NOT NULL FK), so we attach to the first node.
            first_node_id = all_nodes[0].id if all_nodes else wf_id
            session.add(
                TaskEvent(
                    task_node_id=first_node_id,
                    workflow_id=wf_id,
                    event_type=TaskEventType.WORKFLOW_SUBMITTED,
                    event_data={
                        "name": plan.name,
                        "node_count": len(all_nodes),
                    },
                )
            )

        logger.info("Submitted workflow %s (%s) with %d nodes", wf_id, plan.name, len(plan.nodes))
        return wf_id

    # ------------------------------------------------------------------
    # OPA Loop workflow execution
    # ------------------------------------------------------------------

    async def run(
        self,
        goal: str,
        agent: Any | None = None,
        planner: Any | None = None,
        evaluator: Any | None = None,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Run a workflow using the OPA (Observe-Plan-Act) loop.

        This is the new primary execution method for the Environment Agent
        Protocol. It runs continuous OPA cycles until the goal is achieved
        or safety limits are hit.

        Args:
            goal: The high-level workflow goal.
            agent: EnvironmentAgent instance. Required.
            planner: Planner instance. Required.
            evaluator: Evaluator instance. Required.
            **kwargs: Additional arguments passed to OPALoop.run()
                (e.g., max_cycles, max_llm_tokens).

        Returns:
            WorkflowResult with final status and metrics.

        Raises:
            ValueError: If agent, planner, or evaluator is not provided.
        """
        self._ensure_running()

        if agent is None:
            raise ValueError("agent is required for OPA loop execution")
        if planner is None:
            raise ValueError("planner is required for OPA loop execution")
        if evaluator is None:
            raise ValueError("evaluator is required for OPA loop execution")

        loop = OPALoop(
            agent=agent,
            planner=planner,
            evaluator=evaluator,
            settings=self._settings,
        )
        return await loop.run(goal=goal, **kwargs)

    async def resume_workflow(
        self,
        workflow_id: uuid.UUID,
        human_input: str,
        agent: Any | None = None,
        planner: Any | None = None,
        evaluator: Any | None = None,
    ) -> WorkflowResult:
        """Resume a paused workflow with human guidance.

        Args:
            workflow_id: UUID of the paused workflow.
            human_input: Guidance from the human operator.
            agent: EnvironmentAgent instance. Required if not already provided.
            planner: Planner instance. Required if not already provided.
            evaluator: Evaluator instance. Required if not already provided.

        Returns:
            WorkflowResult after the resumed workflow completes or pauses again.

        Raises:
            ValueError: If workflow not found or not in PAUSED state.
        """
        self._ensure_running()

        # Atomic update: only succeed if status is still 'paused'.
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")

            from sqlalchemy import update
            from celeste.database.models import _utcnow

            stmt = (
                update(Workflow)
                .where(Workflow.id == workflow_id, Workflow.status == WorkflowStatus.PAUSED)
                .values(status=WorkflowStatus.RUNNING, human_input=human_input, paused_at=None)
            )
            res = await session.execute(stmt)
            if res.rowcount == 0:
                raise ValueError(
                    f"Workflow {workflow_id} is not paused (status={workflow.status.value})"
                )

        loop = OPALoop(
            agent=agent,
            planner=planner,
            evaluator=evaluator,
            settings=self._settings,
        )
        return await loop.resume(workflow_id, human_input)

    # ------------------------------------------------------------------
    # Legacy workflow execution
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
        """Acquire semaphore and execute a single node.

        Emits WORKSPACE_SPAWN / WORKSPACE_DESTROY WorkflowEvent rows so
        the FeatureDetector can compute concurrent_max and detect leaks.
        """
        if self._semaphore is None:
            raise RuntimeError("Engine semaphore not initialized; call start() first")
        async with self._semaphore:
            # Emit WORKSPACE_SPAWN before workspace setup
            await self._emit_workflow_event_atomic(
                workflow_id=workflow_id,
                node_id=node_id,
                event_type=TaskEventType.WORKSPACE_SPAWN,
            )

            try:
                workspace = self._workspace_factory()
                async with workspace:
                    await self._execute_node(node_id, workspace)
            finally:
                # Emit WORKSPACE_DESTROY after workspace teardown
                await self._emit_workflow_event_atomic(
                    workflow_id=workflow_id,
                    node_id=node_id,
                    event_type=TaskEventType.WORKSPACE_DESTROY,
                )

    async def _emit_workflow_event_atomic(
        self,
        workflow_id: uuid.UUID,
        event_type: TaskEventType,
        node_id: uuid.UUID | None = None,
        event_data: dict | None = None,
        max_retries: int = 8,
    ) -> int:
        """Atomically allocate the next sequence_number and insert a
        WorkflowEvent row.

        F008: catches IntegrityError caused by a concurrent insert
        stealing the same sequence number and retries with a fresh
        allocation. Returns the sequence_number used.
        """
        from sqlalchemy.exc import IntegrityError

        for attempt in range(max_retries):
            try:
                async with get_session() as session:
                    seq_result = await session.execute(
                        select(WorkflowEvent)
                        .where(WorkflowEvent.workflow_id == workflow_id)
                        .order_by(WorkflowEvent.sequence_number.desc())
                        .limit(1)
                    )
                    last_event = seq_result.scalar_one_or_none()
                    next_seq = (last_event.sequence_number + 1) if last_event else 1
                    session.add(
                        WorkflowEvent(
                            workflow_id=workflow_id,
                            task_node_id=node_id,
                            event_type=event_type,
                            sequence_number=next_seq,
                            event_data=event_data,
                        )
                    )
                return next_seq
            except IntegrityError:
                # Another coroutine stole this sequence number. Retry.
                logger.debug(
                    "F008: sequence_number collision on workflow %s; retry %d",
                    workflow_id, attempt + 1,
                )
                continue
        # Exhausted retries -- fall back to a high-entropy offset
        # based on a uuid4 to guarantee uniqueness.
        async with get_session() as session:
            last_event = (
                await session.execute(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.workflow_id == workflow_id)
                    .order_by(WorkflowEvent.sequence_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            base = (last_event.sequence_number + 1) if last_event else 1
            fallback_seq = base + int(uuid.uuid4().int % 1_000_000)
            session.add(
                WorkflowEvent(
                    workflow_id=workflow_id,
                    task_node_id=node_id,
                    event_type=event_type,
                    sequence_number=fallback_seq,
                    event_data=event_data,
                )
            )
            return fallback_seq

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
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        failed = False
        failure_data: dict | None = None

        # SEC-002: audit before execution
        self._audit_or_block(node.command or "", context=f"node {node.name}")

        async for event in workspace.execute(node.command, node.arguments):
            await self._event_queue.put(event)
            if event.event_type == "stdout_line":
                stdout_lines.append(str(event.data))
            elif event.event_type == "stderr_line":
                # OBS-020: capture stderr lines so operators can see
                # what a node wrote to stderr (DockerWorkspace emits
                # these events; previously they were dropped).
                stderr_lines.append(str(event.data))
            elif event.event_type == "execution_failed":
                failed = True
                failure_data = (
                    event.data if isinstance(event.data, dict) else {"error": str(event.data)}
                )

        # OBS-020: persist both streams as structured outputs. The shape is
        # {"stdout": "...", "stderr": "..."} so operators can recover
        # what the node printed to either stream.
        outputs_blob = json.dumps(
            {
                "stdout": "\n".join(stdout_lines),
                "stderr": "\n".join(stderr_lines),
            }
        )

        if failed:
            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(TaskNode.id == node_id)
                )
                node = result.scalar_one()
                node.status = TaskNodeStatus.FAILED
                node.outputs = outputs_blob

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
                node.outputs = outputs_blob

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
                # SEC-007: audit compensation before execution
                self._audit_or_block(comp_cmd or "", context=f"compensation {node_name}")
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
        # F003: atomic conditional update. Only transition to COMPLETED
        # if the workflow is still in RUNNING. Prevents races where two
        # completion paths each read the row, set it to terminal, and
        # one overwrites the other (or a CONCURRENT CANCELLED write wins).
        from sqlalchemy import update as _update

        async with get_session() as session:
            stmt = (
                _update(Workflow)
                .where(
                    Workflow.id == workflow_id,
                    Workflow.status == WorkflowStatus.RUNNING,
                )
                .values(status=WorkflowStatus.COMPLETED)
            )
            res = await session.execute(stmt)
            if res.rowcount == 0:
                # Workflow already in a terminal state; skip transition.
                logger.info(
                    "Workflow %s already in terminal state; skipping COMPLETED",
                    workflow_id,
                )
            else:
                # OBS-005: emit WORKFLOW_COMPLETED TaskEvent so the audit
                # trail has a canonical "workflow terminated successfully"
                # marker. We attach to the first task node to satisfy the
                # NOT NULL FK on TaskEvent.task_node_id; downstream consumers
                # should filter on workflow_id.
                first_node_id = (
                    await session.execute(
                        select(TaskNode.id)
                        .where(TaskNode.workflow_id == workflow_id)
                        .order_by(TaskNode.created_at.asc())
                        .limit(1)
                    )
                ).scalar_one_or_none() or workflow_id
                session.add(
                    TaskEvent(
                        task_node_id=first_node_id,
                        workflow_id=workflow_id,
                        event_type=TaskEventType.WORKFLOW_COMPLETED,
                        event_data={"status": "completed"},
                    )
                )
        logger.info("Workflow %s completed successfully", workflow_id)

    async def _fail_workflow(self, workflow_id: uuid.UUID) -> None:
        # F003: atomic conditional update. Only transition to FAILED
        # if the workflow is still in RUNNING.
        from sqlalchemy import update as _update

        async with get_session() as session:
            stmt = (
                _update(Workflow)
                .where(
                    Workflow.id == workflow_id,
                    Workflow.status == WorkflowStatus.RUNNING,
                )
                .values(status=WorkflowStatus.FAILED)
            )
            res = await session.execute(stmt)
            if res.rowcount == 0:
                logger.info(
                    "Workflow %s already in terminal state; skipping FAILED",
                    workflow_id,
                )
            else:
                # OBS-005: emit WORKFLOW_FAILED TaskEvent so the audit trail
                # has a canonical "workflow terminated unsuccessfully" marker.
                first_node_id = (
                    await session.execute(
                        select(TaskNode.id)
                        .where(TaskNode.workflow_id == workflow_id)
                        .order_by(TaskNode.created_at.asc())
                        .limit(1)
                    )
                ).scalar_one_or_none() or workflow_id
                session.add(
                    TaskEvent(
                        task_node_id=first_node_id,
                        workflow_id=workflow_id,
                        event_type=TaskEventType.WORKFLOW_FAILED,
                        event_data={"status": "failed"},
                    )
                )
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
            from celeste.core.workspaces.git_worktree import GitWorktreeWorkspace
            return GitWorktreeWorkspace()
        elif engine_type == "docker":
            from celeste.core.workspaces.docker import DockerWorkspace
            return DockerWorkspace()
        elif engine_type == "firecracker":
            from celeste.core.workspaces.firecracker import FirecrackerWorkspace
            return FirecrackerWorkspace()
        else:
            raise ValueError(f"Unknown workspace engine: {engine_type}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Checkpoint integration (Continue-As-New)
    # ------------------------------------------------------------------

    async def _check_and_checkpoint(
        self,
        workflow_id: uuid.UUID,
        checkpoint_mgr: "CheckpointManager",
    ) -> uuid.UUID | None:
        """Check if checkpoint threshold is reached and perform Continue-As-New.

        Returns the new workflow ID if a checkpoint was created, else None.
        """
        if not await checkpoint_mgr.should_checkpoint(workflow_id):
            return None

        # 1. Create checkpoint state
        checkpoint_state = await checkpoint_mgr.create_checkpoint(workflow_id)

        # 2. Record CHECKPOINT event on old workflow
        await checkpoint_mgr.record_checkpoint_event(workflow_id, checkpoint_state)

        # 3. Archive old workflow (mark as cancelled)
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            old_wf = result.scalar_one()
            old_wf.status = WorkflowStatus.CANCELLED

        logger.info(
            "Archived workflow %s after checkpoint (events >= %d)",
            workflow_id,
            checkpoint_mgr._event_threshold,
        )

        # 4. Create new workflow run with checkpoint as initial state
        new_wf_id = uuid.uuid4()
        async with get_session() as session:
            old_result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            old_workflow = old_result.scalar_one()

            # Merge checkpoint state into dag_definition
            new_dag_def = dict(old_workflow.dag_definition or {})
            new_dag_def["_checkpoint_state"] = checkpoint_state

            new_workflow = Workflow(
                id=new_wf_id,
                name=old_workflow.name,
                description=old_workflow.description,
                status=WorkflowStatus.PENDING,
                dag_definition=new_dag_def,
            )
            session.add(new_workflow)

            # Copy task nodes to new workflow, rewriting adjacency IDs.
            # F016: new TaskNode rows get fresh UUIDs, so previous_node_ids
            # and next_node_ids copied verbatim from the old workflow point
            # to UUIDs that no longer exist in the new workflow, causing
            # _get_ready_nodes to deadlock. Build old_id -> new_id map and
            # translate both adjacency lists.
            node_result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == workflow_id)
            )
            old_nodes = node_result.scalars().all()
            id_map: dict[str, str] = {
                str(old_node.id): str(uuid.uuid4()) for old_node in old_nodes
            }
            for old_node in old_nodes:
                new_prev = [
                    id_map[p]
                    for p in (old_node.previous_node_ids or [])
                    if p in id_map
                ]
                new_next = [
                    id_map[n]
                    for n in (old_node.next_node_ids or [])
                    if n in id_map
                ]
                new_node = TaskNode(
                    id=uuid.UUID(id_map[str(old_node.id)]),
                    workflow_id=new_wf_id,
                    name=old_node.name,
                    task_type=old_node.task_type,
                    status=TaskNodeStatus.PENDING,
                    command=old_node.command,
                    arguments=dict(old_node.arguments or {}),
                    previous_node_ids=new_prev,
                    next_node_ids=new_next,
                    compensation_command=old_node.compensation_command,
                    compensation_arguments=old_node.compensation_arguments,
                    max_retries=old_node.max_retries,
                )
                session.add(new_node)

        logger.info(
            "Created new workflow %s from checkpoint of %s",
            new_wf_id,
            workflow_id,
        )
        return new_wf_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_running(self) -> None:
        """Raise RuntimeError if the engine has not been started."""
        if not self._running:
            raise RuntimeError("Engine is not started. Call start() first.")
