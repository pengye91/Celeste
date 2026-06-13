"""
Tests for Continue-As-New checkpointing in celeste.core.checkpoint.

Follows strict TDD: these tests are written BEFORE the implementation.

Tests cover:
- CheckpointManager should_checkpoint triggers at threshold
- CheckpointManager create_checkpoint captures full workflow state
- CheckpointManager record_checkpoint_event persists CHECKPOINT WorkflowEvent
- CheckpointManager resume_from_checkpoint returns resumable state
- Engine integration: checkpoint check at end of OPA cycle
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from celeste.config.settings import EngineSettings
from celeste.core.planner import DAGNode, DAGPlan
from celeste.database.models import (
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SQLITE_MEMORY_URL = "sqlite+aiosqlite://"

SAMPLE_PLAN = DAGPlan(
    name="checkpoint-test-workflow",
    description="A sample plan for checkpoint testing",
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
    ],
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
    import asyncio

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
async def db_session(settings):
    """Provide an initialized database session."""
    from celeste.database.db import get_session, init_db

    await init_db(settings=settings)
    async with get_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Test: CheckpointManager creation
# ---------------------------------------------------------------------------


class TestCheckpointManagerCreation:
    """CheckpointManager is created with settings and threshold."""

    @pytest.mark.asyncio
    async def test_create_with_settings(self, settings):
        from celeste.core.checkpoint import CheckpointManager

        mgr = CheckpointManager(settings=settings, event_threshold=100)
        assert mgr._settings is settings
        assert mgr._event_threshold == 100

    @pytest.mark.asyncio
    async def test_default_threshold(self, settings):
        from celeste.core.checkpoint import CheckpointManager

        mgr = CheckpointManager(settings=settings)
        assert mgr._event_threshold == 500


# ---------------------------------------------------------------------------
# Test: should_checkpoint
# ---------------------------------------------------------------------------


class TestShouldCheckpoint:
    """should_checkpoint returns True when event count reaches threshold."""

    @pytest.mark.asyncio
    async def test_checkpoint_triggered_at_threshold(self, settings):
        """When WorkflowEvent count >= threshold, should_checkpoint returns True."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        mgr = CheckpointManager(settings=settings, event_threshold=5)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="threshold-test",
                status=WorkflowStatus.RUNNING,
                dag_definition={"nodes": 2},
            )
            session.add(wf)
            await session.flush()

            # Insert exactly 5 WorkflowEvent records
            for i in range(5):
                session.add(
                    WorkflowEvent(
                        workflow_id=wf_id,
                        event_type=TaskEventType.CYCLE_STARTED,
                        sequence_number=i + 1,
                        event_data={"cycle": i + 1},
                    )
                )

        # Threshold is 5, count is 5 -> should trigger
        result = await mgr.should_checkpoint(wf_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_checkpoint_not_triggered_below_threshold(self, settings):
        """When WorkflowEvent count < threshold, should_checkpoint returns False."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        mgr = CheckpointManager(settings=settings, event_threshold=10)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="below-threshold-test",
                status=WorkflowStatus.RUNNING,
                dag_definition={},
            )
            session.add(wf)
            await session.flush()

            for i in range(3):
                session.add(
                    WorkflowEvent(
                        workflow_id=wf_id,
                        event_type=TaskEventType.CYCLE_STARTED,
                        sequence_number=i + 1,
                    )
                )

        result = await mgr.should_checkpoint(wf_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_checkpoint_triggered_above_threshold(self, settings):
        """When WorkflowEvent count > threshold, should_checkpoint returns True."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        mgr = CheckpointManager(settings=settings, event_threshold=3)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="above-threshold-test",
                status=WorkflowStatus.RUNNING,
                dag_definition={},
            )
            session.add(wf)
            await session.flush()

            for i in range(7):
                session.add(
                    WorkflowEvent(
                        workflow_id=wf_id,
                        event_type=TaskEventType.OBSERVATION_CAPTURED,
                        sequence_number=i + 1,
                    )
                )

        result = await mgr.should_checkpoint(wf_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_zero_events_never_triggers(self, settings):
        """A workflow with zero events should never trigger checkpoint."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        mgr = CheckpointManager(settings=settings, event_threshold=1)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="zero-events-test",
                status=WorkflowStatus.RUNNING,
                dag_definition={},
            )
            session.add(wf)
            await session.flush()

        result = await mgr.should_checkpoint(wf_id)
        assert result is False


# ---------------------------------------------------------------------------
# Test: create_checkpoint
# ---------------------------------------------------------------------------


class TestCreateCheckpoint:
    """create_checkpoint queries DB and returns full workflow state."""

    @pytest.mark.asyncio
    async def test_checkpoint_contains_full_state(self, settings):
        """Checkpoint dict contains goal, context, completed/failed node IDs, cycle_count, tokens."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        mgr = CheckpointManager(settings=settings)

        wf_id = uuid.uuid4()
        node_a_id = uuid.uuid4()
        node_b_id = uuid.uuid4()

        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="full-state-test",
                status=WorkflowStatus.RUNNING,
                dag_definition={
                    "goal": "test the checkpoint system",
                    "context": {"env": "test", "iteration": 42},
                },
            )
            session.add(wf)
            await session.flush()

            node_a = TaskNode(
                id=node_a_id,
                workflow_id=wf_id,
                name="step_a",
                task_type="tool_execution",
                status=TaskNodeStatus.COMPLETED,
                command="echo hello",
                arguments={},
            )
            node_b = TaskNode(
                id=node_b_id,
                workflow_id=wf_id,
                name="step_b",
                task_type="tool_execution",
                status=TaskNodeStatus.FAILED,
                command="echo world",
                arguments={},
            )
            session.add(node_a)
            session.add(node_b)

        checkpoint = await mgr.create_checkpoint(wf_id)

        assert "goal" in checkpoint
        assert "context" in checkpoint
        assert "completed_node_ids" in checkpoint
        assert "failed_node_ids" in checkpoint
        assert "cycle_count" in checkpoint
        assert "llm_tokens_accumulated" in checkpoint

        assert checkpoint["goal"] == "test the checkpoint system"
        assert checkpoint["context"] == {"env": "test", "iteration": 42}
        assert str(node_a_id) in checkpoint["completed_node_ids"]
        assert str(node_b_id) in checkpoint["failed_node_ids"]
        assert isinstance(checkpoint["cycle_count"], int)
        assert isinstance(checkpoint["llm_tokens_accumulated"], int)

    @pytest.mark.asyncio
    async def test_checkpoint_empty_workflow(self, settings):
        """Checkpoint for a workflow with no nodes has empty lists."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        mgr = CheckpointManager(settings=settings)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="empty-workflow",
                status=WorkflowStatus.RUNNING,
                dag_definition={"goal": "empty test", "context": {}},
            )
            session.add(wf)
            await session.flush()

        checkpoint = await mgr.create_checkpoint(wf_id)

        assert checkpoint["goal"] == "empty test"
        assert checkpoint["completed_node_ids"] == []
        assert checkpoint["failed_node_ids"] == []

    @pytest.mark.asyncio
    async def test_checkpoint_only_completed_nodes(self, settings):
        """Only completed nodes appear in completed_node_ids."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        mgr = CheckpointManager(settings=settings)

        wf_id = uuid.uuid4()
        node_a_id = uuid.uuid4()
        node_b_id = uuid.uuid4()

        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="only-completed",
                status=WorkflowStatus.RUNNING,
                dag_definition={"goal": "test", "context": {}},
            )
            session.add(wf)
            await session.flush()

            node_a = TaskNode(
                id=node_a_id,
                workflow_id=wf_id,
                name="completed_node",
                task_type="tool_execution",
                status=TaskNodeStatus.COMPLETED,
                command="echo done",
                arguments={},
            )
            node_b = TaskNode(
                id=node_b_id,
                workflow_id=wf_id,
                name="pending_node",
                task_type="tool_execution",
                status=TaskNodeStatus.PENDING,
                command="echo wait",
                arguments={},
            )
            session.add(node_a)
            session.add(node_b)

        checkpoint = await mgr.create_checkpoint(wf_id)

        assert str(node_a_id) in checkpoint["completed_node_ids"]
        assert str(node_b_id) not in checkpoint["completed_node_ids"]
        assert checkpoint["failed_node_ids"] == []


# ---------------------------------------------------------------------------
# Test: record_checkpoint_event
# ---------------------------------------------------------------------------


class TestRecordCheckpointEvent:
    """record_checkpoint_event persists a CHECKPOINT WorkflowEvent."""

    @pytest.mark.asyncio
    async def test_record_creates_checkpoint_event(self, settings):
        """A WorkflowEvent with type CHECKPOINT is created in the DB."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        mgr = CheckpointManager(settings=settings)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="record-test",
                status=WorkflowStatus.RUNNING,
                dag_definition={},
            )
            session.add(wf)
            await session.flush()

        checkpoint_state = {
            "goal": "test",
            "context": {"key": "value"},
            "completed_node_ids": ["node-1"],
            "failed_node_ids": [],
            "cycle_count": 5,
            "llm_tokens_accumulated": 1000,
        }

        await mgr.record_checkpoint_event(wf_id, checkpoint_state)

        async with get_session() as session:
            result = await session.execute(
                select(WorkflowEvent).where(WorkflowEvent.workflow_id == wf_id)
            )
            events = result.scalars().all()
            # OBS-006: record_checkpoint_event now emits BOTH CHECKPOINT
            # and STATE_CHECKPOINT rows.
            assert len(events) == 2
            event_types = {e.event_type for e in events}
            assert TaskEventType.CHECKPOINT in event_types
            assert TaskEventType.STATE_CHECKPOINT in event_types
            checkpoint_event = next(e for e in events if e.event_type == TaskEventType.CHECKPOINT)
            # OBS-006: CHECKPOINT event_data includes state_hash in addition
            # to the original state fields.
            for k, v in checkpoint_state.items():
                assert checkpoint_event.event_data[k] == v
            assert "state_hash" in checkpoint_event.event_data

    @pytest.mark.asyncio
    async def test_record_preserves_checkpoint_data(self, settings):
        """The checkpoint_state is stored exactly in event_data."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        mgr = CheckpointManager(settings=settings)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="preserve-test",
                status=WorkflowStatus.RUNNING,
                dag_definition={},
            )
            session.add(wf)
            await session.flush()

        checkpoint_state = {
            "goal": "complex goal",
            "context": {"nested": {"deep": "value"}, "list": [1, 2, 3]},
            "completed_node_ids": ["a", "b", "c"],
            "failed_node_ids": ["d"],
            "cycle_count": 99,
            "llm_tokens_accumulated": 50000,
        }

        await mgr.record_checkpoint_event(wf_id, checkpoint_state)

        async with get_session() as session:
            result = await session.execute(
                select(WorkflowEvent).where(
                    WorkflowEvent.workflow_id == wf_id,
                    WorkflowEvent.event_type == TaskEventType.CHECKPOINT,
                )
            )
            event = result.scalar_one()
            # OBS-006: CHECKPOINT event_data preserves the original state
            # fields and adds a state_hash key.
            for k, v in checkpoint_state.items():
                assert event.event_data[k] == v
            assert "state_hash" in event.event_data


# ---------------------------------------------------------------------------
# Test: resume_from_checkpoint
# ---------------------------------------------------------------------------


class TestResumeFromCheckpoint:
    """resume_from_checkpoint returns state needed to resume a workflow."""

    @pytest.mark.asyncio
    async def test_resume_from_checkpoint(self, settings):
        """Returns a dict with all fields needed to resume workflow execution."""
        from celeste.core.checkpoint import CheckpointManager

        mgr = CheckpointManager(settings=settings)

        checkpoint_state = {
            "goal": "resume test",
            "context": {"session_id": "abc123"},
            "completed_node_ids": ["node-1", "node-2"],
            "failed_node_ids": ["node-3"],
            "cycle_count": 10,
            "llm_tokens_accumulated": 2500,
        }

        resume_state = await mgr.resume_from_checkpoint(checkpoint_state)

        assert resume_state["goal"] == "resume test"
        assert resume_state["context"] == {"session_id": "abc123"}
        assert resume_state["completed_node_ids"] == ["node-1", "node-2"]
        assert resume_state["failed_node_ids"] == ["node-3"]
        assert resume_state["cycle_count"] == 10
        assert resume_state["llm_tokens_accumulated"] == 2500

    @pytest.mark.asyncio
    async def test_resume_returns_same_keys(self, settings):
        """resume_from_checkpoint preserves all keys from checkpoint_state."""
        from celeste.core.checkpoint import CheckpointManager

        mgr = CheckpointManager(settings=settings)

        checkpoint_state = {
            "goal": "test",
            "context": {},
            "completed_node_ids": [],
            "failed_node_ids": [],
            "cycle_count": 0,
            "llm_tokens_accumulated": 0,
        }

        resume_state = await mgr.resume_from_checkpoint(checkpoint_state)
        assert set(resume_state.keys()) == set(checkpoint_state.keys())


# ---------------------------------------------------------------------------
# Test: Engine integration
# ---------------------------------------------------------------------------


class TestEngineCheckpointIntegration:
    """Engine integrates checkpoint check at end of OPA cycle."""

    @pytest.mark.asyncio
    async def test_engine_calls_checkpoint_at_end_of_cycle(self, settings):
        """Engine._check_and_checkpoint is called after OPA cycle processing."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.core.engine import Engine
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        engine = Engine(settings=settings)
        await engine.start()
        try:
            # Verify the engine has the checkpoint method
            assert hasattr(engine, "_check_and_checkpoint")
            assert callable(engine._check_and_checkpoint)
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_checkpoint_archives_old_workflow(self, settings):
        """When checkpointing, old workflow is marked as archived."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.core.engine import Engine
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = uuid.uuid4()
            async with get_session() as session:
                wf = Workflow(
                    id=wf_id,
                    name="archive-test",
                    status=WorkflowStatus.RUNNING,
                    dag_definition={"goal": "archive me", "context": {}},
                )
                session.add(wf)
                await session.flush()

                # Insert at least 1 WorkflowEvent so threshold is reached
                session.add(
                    WorkflowEvent(
                        workflow_id=wf_id,
                        event_type=TaskEventType.CYCLE_STARTED,
                        sequence_number=1,
                    )
                )

            checkpoint_mgr = CheckpointManager(settings=settings, event_threshold=1)

            # Manually trigger a checkpoint
            await engine._check_and_checkpoint(wf_id, checkpoint_mgr)

            # Old workflow should be archived
            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
                old_wf = result.scalar_one()
                assert old_wf.status == WorkflowStatus.CANCELLED
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_checkpoint_creates_new_workflow(self, settings):
        """When checkpointing, a new workflow run is created with checkpoint state."""
        from celeste.core.checkpoint import CheckpointManager
        from celeste.core.engine import Engine
        from celeste.database.db import get_session, init_db

        await init_db(settings=settings)
        engine = Engine(settings=settings)
        await engine.start()
        try:
            wf_id = uuid.uuid4()
            node_id = uuid.uuid4()
            async with get_session() as session:
                wf = Workflow(
                    id=wf_id,
                    name="new-wf-test",
                    status=WorkflowStatus.RUNNING,
                    dag_definition={
                        "goal": "continue as new",
                        "context": {"iteration": 5},
                    },
                )
                session.add(wf)
                await session.flush()

                node = TaskNode(
                    id=node_id,
                    workflow_id=wf_id,
                    name="step_a",
                    task_type="tool_execution",
                    status=TaskNodeStatus.COMPLETED,
                    command="echo done",
                    arguments={},
                )
                session.add(node)

                # Insert at least 1 WorkflowEvent so threshold is reached
                session.add(
                    WorkflowEvent(
                        workflow_id=wf_id,
                        event_type=TaskEventType.CYCLE_STARTED,
                        sequence_number=1,
                    )
                )

            checkpoint_mgr = CheckpointManager(settings=settings, event_threshold=1)
            new_wf_id = await engine._check_and_checkpoint(wf_id, checkpoint_mgr)

            # A new workflow should have been created
            assert new_wf_id is not None
            assert isinstance(new_wf_id, uuid.UUID)
            assert new_wf_id != wf_id

            async with get_session() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == new_wf_id)
                )
                new_wf = result.scalar_one()
                assert new_wf.status == WorkflowStatus.PENDING
                assert new_wf.dag_definition.get("_checkpoint_state") is not None
        finally:
            await engine.stop()
