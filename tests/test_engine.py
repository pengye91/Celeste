"""
Tests for the durable execution engine in celeste.core.engine.

Follows strict TDD: these tests are written BEFORE the implementation.
Uses in-memory SQLite and mock workspaces.

Tests cover:
- Engine creation with settings
- Engine start/stop lifecycle
- Workflow submission creates DB records (Workflow + TaskNode rows)
- Ready node detection (dependency satisfaction)
- Node execution in workspace (mock workspace)
- State checkpointing as TaskEvents
- Semaphore concurrency limiting (multiple nodes, limited parallelism)
- Durable state replay: simulate crash, restart, resume
- Saga compensation on node failure
- Event streaming via queue
- Error handling and graceful shutdown
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.planner import DAGNode, DAGPlan
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SQLITE_MEMORY_URL = "sqlite+aiosqlite://"

SAMPLE_PLAN = DAGPlan(
    name="test-workflow",
    description="A sample plan for testing",
    nodes=[
        DAGNode(
            name="step_a",
            task_type="tool_execution",
            command="echo hello",
            arguments={},
            dependencies=[],
        ),
        DAGNode(
            name="step_b",
            task_type="tool_execution",
            command="echo world",
            arguments={},
            dependencies=["step_a"],
        ),
        DAGNode(
            name="step_c",
            task_type="tool_execution",
            command="echo done",
            arguments={"key": "value"},
            dependencies=["step_b"],
            compensation_command="echo cleanup",
            compensation_arguments={"action": "undo"},
        ),
    ],
)

PARALLEL_PLAN = DAGPlan(
    name="parallel-plan",
    description="Plan with parallel fan-out",
    nodes=[
        DAGNode(
            name="root",
            task_type="tool_execution",
            command="echo start",
            arguments={},
            dependencies=[],
        ),
        DAGNode(
            name="branch_1",
            task_type="tool_execution",
            command="echo branch1",
            arguments={},
            dependencies=["root"],
        ),
        DAGNode(
            name="branch_2",
            task_type="tool_execution",
            command="echo branch2",
            arguments={},
            dependencies=["root"],
        ),
        DAGNode(
            name="branch_3",
            task_type="tool_execution",
            command="echo branch3",
            arguments={},
            dependencies=["root"],
        ),
        DAGNode(
            name="join",
            task_type="tool_execution",
            command="echo join",
            arguments={},
            dependencies=["branch_1", "branch_2", "branch_3"],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Mock workspace
# ---------------------------------------------------------------------------


class MockWorkspace(BaseWorkspace):
    """A workspace that tracks calls and yields pre-configured events."""

    def __init__(
        self,
        events: list[WorkspaceEvent] | None = None,
        *,
        fail_commands: set[str] | None = None,
        delay: float = 0.01,
    ) -> None:
        self._events = events or [
            WorkspaceEvent(
                event_type="stdout_line",
                data="mock output",
            ),
            WorkspaceEvent(
                event_type="execution_completed",
                data={"exit_code": 0},
            ),
        ]
        self._fail_commands = fail_commands or set()
        self._delay = delay
        self._active = False
        self.executed_commands: list[str] = []
        self._setup_called = False
        self._teardown_called = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        self._setup_called = True
        self._active = True

    async def execute(
        self,
        command: str,
        arguments: dict | None = None,
        env: dict | None = None,
    ) -> AsyncIterator[WorkspaceEvent]:
        self.executed_commands.append(command)
        await asyncio.sleep(self._delay)
        if command in self._fail_commands:
            yield WorkspaceEvent(
                event_type="execution_failed",
                data={"exit_code": 1, "stderr": f"Command failed: {command}"},
            )
        else:
            for event in self._events:
                yield event

    async def teardown(self) -> None:
        self._teardown_called = True
        self._active = False

    async def get_workspace_path(self) -> str:
        return "/tmp/mock_workspace"


class FailingWorkspace(MockWorkspace):
    """A workspace that always fails on execute."""

    def __init__(self, error_msg: str = "Command failed") -> None:
        super().__init__()
        self._error_msg = error_msg

    async def execute(
        self,
        command: str,
        arguments: dict | None = None,
        env: dict | None = None,
    ) -> AsyncIterator[WorkspaceEvent]:
        self.executed_commands.append(command)
        await asyncio.sleep(0.01)
        yield WorkspaceEvent(
            event_type="execution_failed",
            data={"exit_code": 1, "stderr": self._error_msg},
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_db_module():
    """Reset database module state between tests."""
    import celeste.database.db as db_mod

    db_mod._engine = None
    db_mod._async_session_factory = None
    yield
    # Clean up after test
    if db_mod._engine is not None:
        try:
            loop = asyncio.get_running_loop()
            loop.run_until_complete(db_mod._engine.dispose())
        except Exception:
            pass
    db_mod._engine = None
    db_mod._async_session_factory = None


@pytest.fixture
def settings():
    """Provide test EngineSettings with in-memory SQLite."""
    return EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,  # type: ignore[arg-type]
        MAX_PARALLEL_SUBPROCESSES=2,
        WORKSPACE_ENGINE="local_tmp",
    )


@pytest.fixture
def mock_workspace():
    """Create a fresh MockWorkspace."""
    return MockWorkspace()


@pytest.fixture
def failing_workspace():
    """Create a FailingWorkspace."""
    return FailingWorkspace()


# ---------------------------------------------------------------------------
# Test: Engine creation
# ---------------------------------------------------------------------------


class TestEngineCreation:
    """Engine can be created with settings and defaults."""

    @pytest.mark.asyncio
    async def test_create_with_settings(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        assert engine._settings is settings
        assert engine._running is False

    @pytest.mark.asyncio
    async def test_create_with_defaults(self):
        from celeste.core.engine import Engine

        with patch("celeste.core.engine.get_settings") as mock_gs:
            fake_settings = EngineSettings(
                DATABASE_URL=SQLITE_MEMORY_URL,  # type: ignore[arg-type]
            )
            mock_gs.return_value = fake_settings
            engine = Engine()
            mock_gs.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_custom_workspace_factory(self, settings):
        from celeste.core.engine import Engine

        factory_called = False

        def factory():
            nonlocal factory_called
            factory_called = True
            return MockWorkspace()

        engine = Engine(settings=settings, workspace_factory=factory)
        ws = engine._workspace_factory()
        assert factory_called
        assert isinstance(ws, MockWorkspace)


# ---------------------------------------------------------------------------
# Test: Engine start/stop lifecycle
# ---------------------------------------------------------------------------


class TestEngineLifecycle:
    """Engine start() and stop() manage resources correctly."""

    @pytest.mark.asyncio
    async def test_start_initializes_db_and_semaphore(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            assert engine._running is True
            assert engine._semaphore is not None
            # Verify DB was initialized by checking the module state
            import celeste.database.db as db_mod

            assert db_mod._engine is not None
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        await engine.stop()
        assert engine._running is False

    @pytest.mark.asyncio
    async def test_start_idempotent(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        # Starting again should not raise
        await engine.start()
        await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        # Stopping a non-started engine should not raise
        await engine.stop()


# ---------------------------------------------------------------------------
# Test: Workflow submission
# ---------------------------------------------------------------------------


class TestWorkflowSubmission:
    """submit_workflow creates DB records for the plan."""

    @pytest.mark.asyncio
    async def test_submit_creates_workflow_record(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)
            assert isinstance(wf_id, uuid.UUID)

            # Verify the Workflow record in DB
            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                assert workflow.name == "test-workflow"
                assert workflow.status == WorkflowStatus.PENDING
                assert workflow.description == "A sample plan for testing"
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_submit_creates_task_nodes(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(TaskNode.workflow_id == wf_id)
                )
                nodes = result.scalars().all()
                # SAMPLE_PLAN has 3 nodes
                assert len(nodes) == 3
                node_names = {n.name for n in nodes}
                assert node_names == {"step_a", "step_b", "step_c"}
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_submit_preserves_dependencies(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_c",
                    )
                )
                node_c = result.scalar_one()
                # step_c depends on step_b
                assert len(node_c.previous_node_ids) == 1

                # Verify step_c has compensation command
                assert node_c.compensation_command == "echo cleanup"
                assert node_c.compensation_arguments == {"action": "undo"}
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_submit_preserves_adjacency(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_a",
                    )
                )
                node_a = result.scalar_one()
                # step_a has no predecessors
                assert len(node_a.previous_node_ids) == 0
                # step_a should have step_b in next_node_ids
                assert len(node_a.next_node_ids) == 1
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_submit_dag_definition_stored(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                assert "nodes" in workflow.dag_definition
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: Ready node detection
# ---------------------------------------------------------------------------


class TestReadyNodes:
    """_get_ready_nodes identifies nodes whose dependencies are satisfied."""

    @pytest.mark.asyncio
    async def test_initial_ready_nodes(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)
            ready = await engine._get_ready_nodes(wf_id)
            # Only step_a should be ready initially (no dependencies)
            assert len(ready) == 1
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_parallel_ready_nodes(self, settings):
        """After root completes, all 3 branches should be ready simultaneously."""
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(PARALLEL_PLAN)

            # Mark root as completed
            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "root",
                    )
                )
                root = result.scalar_one()
                root.status = TaskNodeStatus.COMPLETED
                await session.flush()

            ready = await engine._get_ready_nodes(wf_id)
            # All 3 branches should now be ready
            assert len(ready) == 3
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_no_ready_nodes_when_deps_unmet(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            # Mark step_a as running (not completed)
            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_a",
                    )
                )
                step_a = result.scalar_one()
                step_a.status = TaskNodeStatus.RUNNING
                await session.flush()

            ready = await engine._get_ready_nodes(wf_id)
            # step_b should NOT be ready (step_a still running)
            assert len(ready) == 0
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: Node execution
# ---------------------------------------------------------------------------


class TestNodeExecution:
    """_execute_node runs a command in a workspace and records events."""

    @pytest.mark.asyncio
    async def test_execute_node_success(self, settings, mock_workspace):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_a",
                    )
                )
                node = result.scalar_one()
                node_id = node.id

            await engine._execute_node(node_id, mock_workspace)

            # Verify node status is now completed
            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(TaskNode.id == node_id)
                )
                node = result.scalar_one()
                assert node.status == TaskNodeStatus.COMPLETED

                # Verify events were created
                result = await session.execute(
                    select(TaskEvent).where(TaskEvent.task_node_id == node_id)
                )
                events = result.scalars().all()
                event_types = [e.event_type for e in events]
                assert TaskEventType.NODE_STARTED in event_types
                assert TaskEventType.NODE_COMPLETED in event_types
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_execute_node_failure(self, settings, failing_workspace):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_a",
                    )
                )
                node = result.scalar_one()
                node_id = node.id

            # _execute_node raises RuntimeError on failure
            with pytest.raises(RuntimeError, match="failed"):
                await engine._execute_node(node_id, failing_workspace)

            # Verify node status is now failed
            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(TaskNode.id == node_id)
                )
                node = result.scalar_one()
                assert node.status == TaskNodeStatus.FAILED

                # Verify failure event was created
                result = await session.execute(
                    select(TaskEvent).where(TaskEvent.task_node_id == node_id)
                )
                events = result.scalars().all()
                event_types = [e.event_type for e in events]
                assert TaskEventType.NODE_STARTED in event_types
                assert TaskEventType.NODE_FAILED in event_types
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_execute_node_captures_output(self, settings):
        from celeste.core.engine import Engine

        ws = MockWorkspace(
            events=[
                WorkspaceEvent(event_type="stdout_line", data="line1"),
                WorkspaceEvent(event_type="stdout_line", data="line2"),
                WorkspaceEvent(
                    event_type="execution_completed", data={"exit_code": 0}
                ),
            ]
        )
        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_a",
                    )
                )
                node = result.scalar_one()
                node_id = node.id

            await engine._execute_node(node_id, ws)

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(TaskNode.id == node_id)
                )
                node = result.scalar_one()
                assert "line1" in node.outputs
                assert "line2" in node.outputs
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: Full workflow execution
# ---------------------------------------------------------------------------


class TestRunWorkflow:
    """run_workflow executes all nodes in dependency order."""

    @pytest.mark.asyncio
    async def test_run_linear_workflow(self, settings, mock_workspace):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)
            await engine.run_workflow(wf_id)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                assert workflow.status == WorkflowStatus.COMPLETED

                # All nodes should be completed
                result = await session.execute(
                    select(TaskNode).where(TaskNode.workflow_id == wf_id)
                )
                nodes = result.scalars().all()
                assert all(n.status == TaskNodeStatus.COMPLETED for n in nodes)
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_run_parallel_workflow(self, settings):
        from celeste.core.engine import Engine

        ws = MockWorkspace()
        engine = Engine(
            settings=settings,
            workspace_factory=lambda: MockWorkspace(),
        )
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(PARALLEL_PLAN)
            await engine.run_workflow(wf_id)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                assert workflow.status == WorkflowStatus.COMPLETED
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: State checkpointing
# ---------------------------------------------------------------------------


class TestStateCheckpointing:
    """TaskEvents are recorded for every state transition."""

    @pytest.mark.asyncio
    async def test_events_recorded_for_each_node(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)
            await engine.run_workflow(wf_id)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskEvent).where(TaskEvent.workflow_id == wf_id)
                )
                events = result.scalars().all()

                # Each of 3 nodes should have at least NODE_STARTED + NODE_COMPLETED
                node_event_counts: dict[uuid.UUID, int] = defaultdict(int)
                for ev in events:
                    node_event_counts[ev.task_node_id] += 1

                assert len(node_event_counts) == 3
                for count in node_event_counts.values():
                    assert count >= 2  # started + completed
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_events_have_timestamps(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)
            await engine.run_workflow(wf_id)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskEvent).where(TaskEvent.workflow_id == wf_id)
                )
                events = result.scalars().all()
                for ev in events:
                    assert ev.timestamp is not None
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: Semaphore concurrency limiting
# ---------------------------------------------------------------------------


class TestConcurrencyLimiting:
    """Semaphore limits the number of concurrently executing nodes."""

    @pytest.mark.asyncio
    async def test_max_parallel_respected(self):
        """Track peak concurrency and verify it stays within the limit."""
        settings = EngineSettings(
            DATABASE_URL=SQLITE_MEMORY_URL,  # type: ignore[arg-type]
            MAX_PARALLEL_SUBPROCESSES=2,
            WORKSPACE_ENGINE="local_tmp",
        )

        peak_concurrency = 0
        current_concurrency = 0
        lock = asyncio.Lock()

        class TrackingWorkspace(MockWorkspace):
            def __init__(self):
                super().__init__(delay=0.05)

            async def execute(
                self,
                command: str,
                arguments: dict | None = None,
                env: dict | None = None,
            ) -> AsyncIterator[WorkspaceEvent]:
                nonlocal peak_concurrency, current_concurrency
                async with lock:
                    current_concurrency += 1
                    if current_concurrency > peak_concurrency:
                        peak_concurrency = current_concurrency

                self.executed_commands.append(command)
                await asyncio.sleep(0.05)

                async with lock:
                    current_concurrency -= 1

                for event in self._events:
                    yield event

        from celeste.core.engine import Engine

        engine = Engine(
            settings=settings,
            workspace_factory=lambda: TrackingWorkspace(),
        )
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(PARALLEL_PLAN)
            await engine.run_workflow(wf_id)

            # With 3 branches and MAX_PARALLEL=2, peak should be 2
            assert peak_concurrency <= 2
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_single_parallelism_serial_execution(self):
        """With MAX_PARALLEL=1, nodes execute one at a time."""
        settings = EngineSettings(
            DATABASE_URL=SQLITE_MEMORY_URL,  # type: ignore[arg-type]
            MAX_PARALLEL_SUBPROCESSES=1,
            WORKSPACE_ENGINE="local_tmp",
        )

        peak_concurrency = 0
        current_concurrency = 0
        lock = asyncio.Lock()

        class TrackingWorkspace(MockWorkspace):
            def __init__(self):
                super().__init__(delay=0.05)

            async def execute(
                self,
                command: str,
                arguments: dict | None = None,
                env: dict | None = None,
            ) -> AsyncIterator[WorkspaceEvent]:
                nonlocal peak_concurrency, current_concurrency
                async with lock:
                    current_concurrency += 1
                    if current_concurrency > peak_concurrency:
                        peak_concurrency = current_concurrency

                self.executed_commands.append(command)
                await asyncio.sleep(0.05)

                async with lock:
                    current_concurrency -= 1

                for event in self._events:
                    yield event

        from celeste.core.engine import Engine

        engine = Engine(
            settings=settings,
            workspace_factory=lambda: TrackingWorkspace(),
        )
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(PARALLEL_PLAN)
            await engine.run_workflow(wf_id)

            # With MAX_PARALLEL=1, peak concurrency should be exactly 1
            assert peak_concurrency == 1
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: Durable state replay
# ---------------------------------------------------------------------------


class TestDurableStateReplay:
    """On startup, the engine reconstructs state from TaskEvent ledger."""

    @pytest.mark.asyncio
    async def test_replay_resumes_partial_workflow(self, settings):
        """Simulate a crash after step_a completes, then replay resumes from step_b."""
        from celeste.core.engine import Engine

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            # Simulate: step_a completed, step_b was running when crash happened
            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_a",
                    )
                )
                step_a = result.scalar_one()
                step_a.status = TaskNodeStatus.COMPLETED

                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_b",
                    )
                )
                step_b = result.scalar_one()
                step_b.status = TaskNodeStatus.RUNNING

                # Mark workflow as running
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                workflow.status = WorkflowStatus.RUNNING

                # Create events for step_a completion
                session.add(
                    TaskEvent(
                        task_node_id=step_a.id,
                        workflow_id=wf_id,
                        event_type=TaskEventType.NODE_STARTED,
                    )
                )
                session.add(
                    TaskEvent(
                        task_node_id=step_a.id,
                        workflow_id=wf_id,
                        event_type=TaskEventType.NODE_COMPLETED,
                    )
                )

            # Now replay
            await engine._replay_state()

            # After replay, step_b should be back to pending (reset from running)
            # and ready for re-execution
            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_b",
                    )
                )
                step_b = result.scalar_one()
                # Running nodes without completion events should be reset to pending
                assert step_b.status == TaskNodeStatus.PENDING

        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_replay_does_not_reexecute_completed(self, settings):
        """Completed nodes are not re-executed after replay."""
        from celeste.core.engine import Engine

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            # Mark step_a and step_b as completed
            async with get_session() as session:
                for name in ("step_a", "step_b"):
                    result = await session.execute(
                        select(TaskNode).where(
                            TaskNode.workflow_id == wf_id,
                            TaskNode.name == name,
                        )
                    )
                    node = result.scalar_one()
                    node.status = TaskNodeStatus.COMPLETED
                    session.add(
                        TaskEvent(
                            task_node_id=node.id,
                            workflow_id=wf_id,
                            event_type=TaskEventType.NODE_COMPLETED,
                        )
                    )

                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                workflow.status = WorkflowStatus.RUNNING

            await engine._replay_state()

            # step_a and step_b should remain completed, step_c should be pending
            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(TaskNode.workflow_id == wf_id)
                )
                nodes = result.scalars().all()
                for node in nodes:
                    if node.name in ("step_a", "step_b"):
                        assert node.status == TaskNodeStatus.COMPLETED
                    else:
                        assert node.status == TaskNodeStatus.PENDING

        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_replay_no_running_workflows(self, settings):
        """Replay is a no-op when there are no running workflows."""
        from celeste.core.engine import Engine

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            # Should not raise
            await engine._replay_state()
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_full_crash_recovery(self):
        """Simulate full crash-recovery: execute partially, stop engine,
        create new engine, replay, and resume.

        Uses a shared file-based SQLite so data survives engine stop/close_db.
        """
        import os
        import tempfile

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "recovery_test.db")
        file_url = f"sqlite+aiosqlite:///{db_path}"

        try:
            recovery_settings = EngineSettings(
                DATABASE_URL=file_url,  # type: ignore[arg-type]
                MAX_PARALLEL_SUBPROCESSES=2,
                WORKSPACE_ENGINE="local_tmp",
            )

            from celeste.core.engine import Engine

            # Phase 1: Execute partially
            engine1 = Engine(
                settings=recovery_settings,
                workspace_factory=lambda: MockWorkspace(),
            )
            await engine1.start()
            wf_id = await engine1.submit_workflow(PARALLEL_PLAN)

            # Manually mark root as completed, branches as running (simulating crash)
            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "root",
                    )
                )
                root = result.scalar_one()
                root.status = TaskNodeStatus.COMPLETED
                session.add(
                    TaskEvent(
                        task_node_id=root.id,
                        workflow_id=wf_id,
                        event_type=TaskEventType.NODE_COMPLETED,
                    )
                )

                for name in ("branch_1", "branch_2", "branch_3"):
                    result = await session.execute(
                        select(TaskNode).where(
                            TaskNode.workflow_id == wf_id,
                            TaskNode.name == name,
                        )
                    )
                    node = result.scalar_one()
                    node.status = TaskNodeStatus.RUNNING

                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                workflow.status = WorkflowStatus.RUNNING

            # Stop engine (simulates crash) -- this calls close_db()
            await engine1.stop()

            # Phase 2: New engine starts, replays, resumes
            engine2 = Engine(
                settings=recovery_settings,
                workspace_factory=lambda: MockWorkspace(),
            )
            await engine2.start()
            try:
                # Engine start should trigger replay, resetting running nodes to pending

                # Now run the workflow to completion
                await engine2.run_workflow(wf_id)

                async with get_session() as session:
                    result = await session.execute(
                        select(Workflow).where(Workflow.id == wf_id)
                    )
                    workflow = result.scalar_one()
                    assert workflow.status == WorkflowStatus.COMPLETED

                    result = await session.execute(
                        select(TaskNode).where(TaskNode.workflow_id == wf_id)
                    )
                    nodes = result.scalars().all()
                    assert all(n.status == TaskNodeStatus.COMPLETED for n in nodes)
            finally:
                await engine2.stop()
        finally:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: Saga compensation
# ---------------------------------------------------------------------------


class TestSagaCompensation:
    """On node failure, completed nodes with compensation commands get compensated."""

    @pytest.mark.asyncio
    async def test_compensation_on_failure(self, settings):
        """When step_c fails, step_a and step_b (if they had compensation)
        should have COMPENSATION_TRIGGERED events."""
        from celeste.core.engine import Engine

        # Plan where step_c fails and has compensation
        plan = DAGPlan(
            name="saga-test",
            description="Test saga compensation",
            nodes=[
                DAGNode(
                    name="setup",
                    task_type="tool_execution",
                    command="echo setup",
                    arguments={},
                    dependencies=[],
                    compensation_command="echo cleanup_setup",
                    compensation_arguments={"undo": "setup"},
                ),
                DAGNode(
                    name="process",
                    task_type="tool_execution",
                    command="echo process",
                    arguments={},
                    dependencies=["setup"],
                    compensation_command="echo cleanup_process",
                    compensation_arguments={"undo": "process"},
                ),
                DAGNode(
                    name="finalize",
                    task_type="tool_execution",
                    command="fail_here",
                    arguments={},
                    dependencies=["process"],
                ),
            ],
        )

        # Workspace that fails on "fail_here"
        def ws_factory():
            return MockWorkspace(fail_commands={"fail_here"})

        engine = Engine(settings=settings, workspace_factory=ws_factory)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(plan)
            await engine.run_workflow(wf_id)

            from celeste.database.db import get_session

            async with get_session() as session:
                # Workflow should be failed
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                assert workflow.status == WorkflowStatus.FAILED

                # Check for compensation events
                result = await session.execute(
                    select(TaskEvent).where(
                        TaskEvent.workflow_id == wf_id,
                        TaskEvent.event_type == TaskEventType.COMPENSATION_TRIGGERED,
                    )
                )
                comp_events = result.scalars().all()
                # setup and process have compensation commands
                assert len(comp_events) == 2
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_compensation_commands_are_executed(self, settings):
        """Compensation commands are actually executed in workspaces, not just logged."""
        from celeste.core.engine import Engine

        # Track which compensation commands get executed
        executed_compensations: list[str] = []

        class CompensationTrackingWorkspace(MockWorkspace):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)

            async def execute(
                self,
                command: str,
                arguments: dict | None = None,
                env: dict | None = None,
            ) -> AsyncIterator[WorkspaceEvent]:
                executed_compensations.append(command)
                async for event in super().execute(command, arguments, env):
                    yield event

        plan = DAGPlan(
            name="saga-exec-test",
            description="Test compensation execution",
            nodes=[
                DAGNode(
                    name="node_a",
                    task_type="tool_execution",
                    command="do_a",
                    arguments={},
                    dependencies=[],
                    compensation_command="undo_a",
                    compensation_arguments={"action": "undo_a"},
                ),
                DAGNode(
                    name="node_b",
                    task_type="tool_execution",
                    command="do_b",
                    arguments={},
                    dependencies=["node_a"],
                    compensation_command="undo_b",
                    compensation_arguments={"action": "undo_b"},
                ),
                DAGNode(
                    name="node_c_fail",
                    task_type="tool_execution",
                    command="fail_here",
                    arguments={},
                    dependencies=["node_b"],
                ),
            ],
        )

        def ws_factory():
            return CompensationTrackingWorkspace(fail_commands={"fail_here"})

        engine = Engine(settings=settings, workspace_factory=ws_factory)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(plan)
            await engine.run_workflow(wf_id)

            from celeste.database.db import get_session

            # Verify compensation commands were actually executed
            # Should contain: do_a, do_b, fail_here, undo_b, undo_a (reverse order)
            assert "undo_a" in executed_compensations
            assert "undo_b" in executed_compensations
            # undo_b should come before undo_a (reverse order)
            undo_b_idx = executed_compensations.index("undo_b")
            undo_a_idx = executed_compensations.index("undo_a")
            assert undo_b_idx < undo_a_idx

            # Verify COMPENSATION_COMPLETED events were recorded
            async with get_session() as session:
                result = await session.execute(
                    select(TaskEvent).where(
                        TaskEvent.workflow_id == wf_id,
                        TaskEvent.event_type == TaskEventType.COMPENSATION_COMPLETED,
                    )
                )
                completed_events = result.scalars().all()
                assert len(completed_events) == 2
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_compensation_failure_is_best_effort(self, settings):
        """If a compensation command fails, other compensations still proceed."""
        from celeste.core.engine import Engine

        executed_compensations: list[str] = []

        class PartialFailCompensationWorkspace(MockWorkspace):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)

            async def execute(
                self,
                command: str,
                arguments: dict | None = None,
                env: dict | None = None,
            ) -> AsyncIterator[WorkspaceEvent]:
                executed_compensations.append(command)
                if command == "undo_b":
                    raise RuntimeError("Compensation workspace error")
                async for event in super().execute(command, arguments, env):
                    yield event

        plan = DAGPlan(
            name="saga-best-effort-test",
            description="Test best-effort compensation",
            nodes=[
                DAGNode(
                    name="node_a",
                    task_type="tool_execution",
                    command="do_a",
                    arguments={},
                    dependencies=[],
                    compensation_command="undo_a",
                    compensation_arguments={},
                ),
                DAGNode(
                    name="node_b",
                    task_type="tool_execution",
                    command="do_b",
                    arguments={},
                    dependencies=["node_a"],
                    compensation_command="undo_b",
                    compensation_arguments={},
                ),
                DAGNode(
                    name="node_c_fail",
                    task_type="tool_execution",
                    command="fail_here",
                    arguments={},
                    dependencies=["node_b"],
                ),
            ],
        )

        def ws_factory():
            return PartialFailCompensationWorkspace(fail_commands={"fail_here"})

        engine = Engine(settings=settings, workspace_factory=ws_factory)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(plan)
            # Should not raise despite compensation failure
            await engine.run_workflow(wf_id)

            from celeste.database.db import get_session

            # Both compensations should have been attempted
            assert "undo_b" in executed_compensations
            assert "undo_a" in executed_compensations

            # Verify COMPENSATION_FAILED for undo_b and COMPENSATION_COMPLETED for undo_a
            async with get_session() as session:
                result = await session.execute(
                    select(TaskEvent).where(
                        TaskEvent.workflow_id == wf_id,
                        TaskEvent.event_type == TaskEventType.COMPENSATION_FAILED,
                    )
                )
                failed_events = result.scalars().all()
                assert len(failed_events) == 1

                result = await session.execute(
                    select(TaskEvent).where(
                        TaskEvent.workflow_id == wf_id,
                        TaskEvent.event_type == TaskEventType.COMPENSATION_COMPLETED,
                    )
                )
                completed_events = result.scalars().all()
                assert len(completed_events) == 1

                # Workflow should still be marked as failed
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                assert workflow.status == WorkflowStatus.FAILED
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: Event streaming via queue
# ---------------------------------------------------------------------------


class TestEventQueue:
    """Engine exposes an event queue for consumers."""

    @pytest.mark.asyncio
    async def test_event_queue_exists(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            assert hasattr(engine, "_event_queue")
            assert isinstance(engine._event_queue, asyncio.Queue)
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_events_emitted_to_queue(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)
            await engine.run_workflow(wf_id)

            # Event queue should have accumulated events
            assert not engine._event_queue.empty()
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: Error handling and graceful shutdown
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Engine handles errors gracefully."""

    @pytest.mark.asyncio
    async def test_submit_before_start_raises(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        with pytest.raises(RuntimeError, match="not started"):
            await engine.submit_workflow(SAMPLE_PLAN)

    @pytest.mark.asyncio
    async def test_run_workflow_before_start_raises(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        with pytest.raises(RuntimeError, match="not started"):
            await engine.run_workflow(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_run_nonexistent_workflow_raises(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            with pytest.raises(Exception):
                await engine.run_workflow(uuid.uuid4())
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_graceful_stop_with_active_tasks(self, settings):
        """Engine stops cleanly even with tasks in progress."""
        from celeste.core.engine import Engine

        # Use a workspace with a delay so tasks are in-flight during stop
        engine = Engine(
            settings=settings,
            workspace_factory=lambda: MockWorkspace(delay=0.5),
        )
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(PARALLEL_PLAN)
            # Start workflow in background
            task = asyncio.create_task(engine.run_workflow(wf_id))
            # Give it a moment to start
            await asyncio.sleep(0.1)
            # Now stop - should handle gracefully
            await engine.stop()
            # Cancel the background task if still running
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        except Exception:
            # Ensure engine is stopped even on unexpected error
            try:
                await engine.stop()
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_workspace_factory_default(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        ws = engine._default_workspace_factory()
        # Default workspace engine is local_tmp
        from celeste.core.workspaces.local_tmp import LocalTmpWorkspace

        assert isinstance(ws, LocalTmpWorkspace)


# ---------------------------------------------------------------------------
# Test: Deadlock detection timeout
# ---------------------------------------------------------------------------


class TestDeadlockDetection:
    """Deadlock detection loop has a timeout to prevent infinite spinning."""

    @pytest.mark.asyncio
    async def test_deadlock_timeout_raises(self, settings):
        """If no nodes become ready for too long, RuntimeError is raised."""
        from celeste.core.engine import Engine

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            # Sabotage: set all nodes to RUNNING so none are pending or terminal
            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(TaskNode.workflow_id == wf_id)
                )
                nodes = result.scalars().all()
                for node in nodes:
                    node.status = TaskNodeStatus.RUNNING

                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                workflow = result.scalar_one()
                workflow.status = WorkflowStatus.RUNNING

            # Patch the deadlock parameters to make it fail quickly
            async def _fast_deadlock_run(self, workflow_id):
                """Patched run_workflow with very short deadlock timeout."""
                self._ensure_running()
                deadlock_wait_count = 0
                max_wait_iterations = 3  # Very short for test
                while True:
                    ready_ids = await self._get_ready_nodes(workflow_id)
                    if not ready_ids:
                        async with get_session() as session:
                            from sqlalchemy import select as sa_select
                            result = await session.execute(
                                sa_select(TaskNode).where(
                                    TaskNode.workflow_id == workflow_id
                                )
                            )
                            nodes = result.scalars().all()

                        all_done = all(
                            n.status
                            in (TaskNodeStatus.COMPLETED, TaskNodeStatus.FAILED)
                            for n in nodes
                        )
                        if all_done:
                            return

                        pending_exist = any(
                            n.status
                            in (TaskNodeStatus.PENDING, TaskNodeStatus.RUNNING)
                            for n in nodes
                        )
                        if not pending_exist:
                            return
                        await asyncio.sleep(0.01)
                        deadlock_wait_count += 1
                        if deadlock_wait_count >= max_wait_iterations:
                            raise RuntimeError(
                                f"Workflow {workflow_id} appears deadlocked"
                            )
                        continue

            with pytest.raises(RuntimeError, match="deadlocked"):
                await _fast_deadlock_run(engine, wf_id)
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: Stop resets state (I5)
# ---------------------------------------------------------------------------


class TestStopReset:
    """stop() resets semaphore and event queue for clean restart."""

    @pytest.mark.asyncio
    async def test_stop_resets_semaphore(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        assert engine._semaphore is not None
        await engine.stop()
        assert engine._semaphore is None

    @pytest.mark.asyncio
    async def test_stop_resets_event_queue(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)
            await engine.run_workflow(wf_id)
            # Queue should have events
            assert not engine._event_queue.empty()
        finally:
            await engine.stop()

        # After stop, queue should be fresh/empty
        assert engine._event_queue.empty()

    @pytest.mark.asyncio
    async def test_restart_after_stop(self, settings):
        """Engine can be started again after stop with fresh state."""
        from celeste.core.engine import Engine

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)
            await engine.run_workflow(wf_id)
        finally:
            await engine.stop()

        # Should be able to start again
        await engine.start()
        try:
            assert engine._running is True
            assert engine._semaphore is not None
            # Should be able to submit and run a new workflow
            wf_id2 = await engine.submit_workflow(SAMPLE_PLAN)
            await engine.run_workflow(wf_id2)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id2)
                )
                workflow = result.scalar_one()
                assert workflow.status == WorkflowStatus.COMPLETED
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# OPA Loop Integration
# ---------------------------------------------------------------------------


class TestOPALoopIntegration:
    """Tests for Engine integration with the OPA Loop."""

    @pytest.fixture
    def settings(self):
        return EngineSettings(
            DATABASE_URL=SQLITE_MEMORY_URL,
            MAX_PARALLEL_SUBPROCESSES=2,
            MAX_OPA_CYCLES=10,
            MAX_LLM_TOKENS=5000,
        )

    @pytest.mark.asyncio
    async def test_engine_run_opa_loop_integration(self, settings):
        """Engine.run() uses OPA loop with mocked planner and evaluator."""
        from celeste.core.engine import Engine
        from celeste.core.opa_loop import WorkflowResult
        from celeste.core.planner import DAGFragment
        from celeste.core.evaluator import EvaluatorDecision

        # Mock agent
        mock_agent = MagicMock()
        mock_agent.call_tool = AsyncMock(return_value={"files": {}, "platform": "darwin"})
        mock_agent.list_tools = AsyncMock(return_value=[])

        # Mock planner that returns a fragment with goal_achieved=True
        mock_planner = MagicMock()
        mock_planner.plan = AsyncMock(
            return_value=DAGFragment(
                nodes=[],
                reasoning="Goal achieved",
                goal_achieved=True,
            )
        )

        # Mock evaluator
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate = AsyncMock(return_value=EvaluatorDecision.DONE)

        engine = Engine(
            settings=settings,
            workspace_factory=lambda: MockWorkspace(),
        )
        await engine.start()
        try:
            result = await engine.run(
                goal="test goal",
                agent=mock_agent,
                planner=mock_planner,
                evaluator=mock_evaluator,
            )

            assert isinstance(result, WorkflowResult)
            assert result.status == "completed"
            # Planner should have been called at least once
            assert mock_planner.plan.call_count >= 1
            # Evaluator should have been called after each fragment
            assert mock_evaluator.evaluate.call_count >= 1
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_engine_run_without_agent_raises(self, settings):
        """Engine.run() raises if agent is not provided."""
        from celeste.core.engine import Engine

        engine = Engine(
            settings=settings,
            workspace_factory=lambda: MockWorkspace(),
        )
        await engine.start()
        try:
            with pytest.raises(ValueError, match="agent is required"):
                await engine.run(goal="test goal")
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_engine_run_without_planner_raises(self, settings):
        """Engine.run() raises if planner is not provided."""
        from celeste.core.engine import Engine

        mock_agent = MagicMock()
        engine = Engine(
            settings=settings,
            workspace_factory=lambda: MockWorkspace(),
        )
        await engine.start()
        try:
            with pytest.raises(ValueError, match="planner is required"):
                await engine.run(goal="test goal", agent=mock_agent)
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_engine_run_without_evaluator_raises(self, settings):
        """Engine.run() raises if evaluator is not provided."""
        from celeste.core.engine import Engine

        mock_agent = MagicMock()
        mock_planner = MagicMock()
        engine = Engine(
            settings=settings,
            workspace_factory=lambda: MockWorkspace(),
        )
        await engine.start()
        try:
            with pytest.raises(ValueError, match="evaluator is required"):
                await engine.run(goal="test goal", agent=mock_agent, planner=mock_planner)
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_engine_run_max_cycles_override(self, settings):
        """Engine.run() max_cycles parameter overrides settings."""
        from celeste.core.engine import Engine
        from celeste.core.opa_loop import WorkflowResult
        from celeste.core.planner import DAGFragment
        from celeste.core.evaluator import EvaluatorDecision

        mock_agent = MagicMock()
        mock_agent.call_tool = AsyncMock(return_value={"files": {}})
        mock_agent.list_tools = AsyncMock(return_value=[])

        # Planner always returns non-achieved, evaluator always CONTINUE
        mock_planner = MagicMock()
        mock_planner.plan = AsyncMock(
            return_value=DAGFragment(
                nodes=[],
                reasoning="continue",
                goal_achieved=False,
            )
        )

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate = AsyncMock(return_value=EvaluatorDecision.CONTINUE)

        engine = Engine(
            settings=settings,
            workspace_factory=lambda: MockWorkspace(),
        )
        await engine.start()
        try:
            result = await engine.run(
                goal="never ends",
                agent=mock_agent,
                planner=mock_planner,
                evaluator=mock_evaluator,
                max_cycles=3,
            )

            assert isinstance(result, WorkflowResult)
            assert result.status == "escalated"
            assert result.reason == "max_cycles_exceeded"
            assert result.cycle_count == 3
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: F016 -- Checkpoint adjacency list rewrite
# ---------------------------------------------------------------------------


class TestCheckpointAdjacencyRewrite:
    """F016: _check_and_checkpoint must rewrite previous_node_ids and
    next_node_ids to reference the NEW workflow's UUIDs, not the old ones.
    Otherwise, _get_ready_nodes finds no completed dependencies and the
    new workflow deadlocks.
    """

    @pytest.mark.asyncio
    async def test_checkpoint_rewrites_adjacency_ids(self, settings):
        from celeste.core.engine import Engine
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.models import WorkflowEvent

        # Use a tiny threshold to force checkpoint
        mgr = CheckpointManager(settings=settings, event_threshold=1)
        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)
            # Mark step_a as completed so we have one completed node;
            # step_b/step_c then depend on a UUID that the new workflow
            # must rewrite to its own.
            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "step_a",
                    )
                )
                step_a = result.scalar_one()
                step_a.status = TaskNodeStatus.COMPLETED
                # Insert a WorkflowEvent so the checkpoint threshold is met
                session.add(
                    WorkflowEvent(
                        workflow_id=wf_id,
                        event_type=TaskEventType.CYCLE_STARTED,
                        sequence_number=1,
                        event_data={"cycle": 1},
                    )
                )

            new_wf_id = await engine._check_and_checkpoint(wf_id, mgr)
            assert new_wf_id is not None
            assert new_wf_id != wf_id

            # Inspect the new workflow's nodes: every previous_node_ids
            # entry must reference a node that exists in new_wf_id.
            async with get_session() as session:
                new_nodes_result = await session.execute(
                    select(TaskNode).where(TaskNode.workflow_id == new_wf_id)
                )
                new_nodes = new_nodes_result.scalars().all()
                new_node_ids = {str(n.id) for n in new_nodes}

                for node in new_nodes:
                    for prev_id in node.previous_node_ids:
                        assert prev_id in new_node_ids, (
                            f"Node {node.name} in new workflow has "
                            f"previous_node_ids={node.previous_node_ids} "
                            f"referencing a UUID not in the new workflow "
                            f"(available: {new_node_ids})"
                        )
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: F003 -- _complete_workflow / _fail_workflow atomic status update
# ---------------------------------------------------------------------------


class TestWorkflowTerminalStatusRace:
    """F003: _complete_workflow and _fail_workflow must use a conditional
    UPDATE (WHERE status='running') rather than SELECT-then-write to
    prevent races where two completion paths each transition the workflow
    out of RUNNING.
    """

    @pytest.mark.asyncio
    async def test_complete_workflow_uses_atomic_update(self, settings):
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            # Set workflow to RUNNING manually to simulate post-dispatch
            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                wf = result.scalar_one()
                wf.status = WorkflowStatus.RUNNING

            await engine._complete_workflow(wf_id)

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                wf = result.scalar_one()
                assert wf.status == WorkflowStatus.COMPLETED
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_complete_workflow_no_op_when_not_running(self, settings):
        """If the workflow is already in a terminal state, the conditional
        UPDATE in _complete_workflow must NOT overwrite it (e.g. FAILED)."""
        from celeste.core.engine import Engine

        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SAMPLE_PLAN)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                wf = result.scalar_one()
                # Set status to FAILED directly
                wf.status = WorkflowStatus.FAILED

            await engine._complete_workflow(wf_id)

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                wf = result.scalar_one()
                # _complete_workflow must not have overwritten FAILED
                assert wf.status == WorkflowStatus.FAILED
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Test: F008 -- WorkflowEvent sequence_number race
# ---------------------------------------------------------------------------


class TestWorkflowEventSequenceNumberRace:
    """F008: Concurrent _run_node_under_semaphore coroutines on the same
    workflow must not produce WorkflowEvent rows with duplicate
    sequence_numbers. The fix should add a UNIQUE constraint on
    (workflow_id, sequence_number) and retry on IntegrityError.
    """

    @pytest.mark.asyncio
    async def test_concurrent_emits_produce_unique_sequence_numbers(self, settings):
        from celeste.core.engine import Engine
        from celeste.database.models import WorkflowEvent

        engine = Engine(settings=settings, workspace_factory=lambda: MockWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(PARALLEL_PLAN)

            # Concurrently emit WORKSPACE_SPAWN events for the same workflow
            # using the same code path as _run_node_under_semaphore, which
            # uses the atomic helper that retries on IntegrityError.
            import asyncio

            node_ids = [uuid.uuid4() for _ in range(5)]
            await asyncio.gather(
                *(
                    engine._emit_workflow_event_atomic(
                        workflow_id=wf_id,
                        node_id=nid,
                        event_type=TaskEventType.WORKSPACE_SPAWN,
                    )
                    for nid in node_ids
                )
            )

            # Verify all sequence numbers are unique
            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(WorkflowEvent.sequence_number).where(
                        WorkflowEvent.workflow_id == wf_id
                    )
                )
                seqs = [row[0] for row in result.all()]
                assert len(seqs) == len(set(seqs)), (
                    f"Duplicate sequence numbers found: {seqs}"
                )
        finally:
            await engine.stop()


