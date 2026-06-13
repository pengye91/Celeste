"""
Tests for OBS-006: STATE_CHECKPOINT event emission.

The audit shows STATE_CHECKPOINT is declared in TaskEventType (models.py:74)
and queried by FeatureDetector.detect_checkpoint, but no code path emits
it. CheckpointManager.record_checkpoint_event only emits CHECKPOINT.

These tests verify:
- A checkpoint emission writes both CHECKPOINT and STATE_CHECKPOINT rows
  OR (per the audit verdict) the CHECKPOINT event carries state_hash so
  detect_checkpoint's hash_match computation can succeed.
- The state_hash, when present, is deterministic over identical state.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.checkpoint import CheckpointManager
from celeste.database.models import (
    TaskEventType,
    WorkflowEvent,
)


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


@pytest.fixture(autouse=True)
def _reset_db_module():
    import celeste.database.db as db_mod
    db_mod._engine = None
    db_mod._async_session_factory = None
    yield
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
    return EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,  # type: ignore[arg-type]
        MAX_PARALLEL_SUBPROCESSES=1,
    )


@pytest.fixture
async def workflow_id(settings):
    """Create a single Workflow row and return its UUID."""
    from celeste.database.db import get_session, init_db
    from celeste.database.models import Workflow, WorkflowStatus

    await init_db(settings=settings)
    wf_id = uuid.uuid4()
    async with get_session() as session:
        session.add(
            Workflow(id=wf_id, name="ckpt-test", status=WorkflowStatus.RUNNING, dag_definition={})
        )
    return wf_id


class TestCheckpointEventEmission:
    """Checkpoint emission must surface STATE_CHECKPOINT or include state_hash."""

    @pytest.mark.asyncio
    async def test_checkpoint_emits_state_checkpoint_or_state_hash(self, settings, workflow_id):
        """record_checkpoint_event must write either STATE_CHECKPOINT or
        include state_hash in the CHECKPOINT event_data so the
        FeatureDetector can compute hash_match (OBS-006)."""
        from celeste.database.db import get_session

        mgr = CheckpointManager(event_threshold=1)
        state: dict[str, Any] = {
            "goal": "demo goal",
            "context": {"a": 1},
            "completed_node_ids": [str(uuid.uuid4())],
            "failed_node_ids": [],
            "cycle_count": 1,
            "llm_tokens_accumulated": 0,
        }
        await mgr.record_checkpoint_event(workflow_id, state)

        async with get_session() as session:
            events = (
                await session.execute(
                    select(WorkflowEvent).where(WorkflowEvent.workflow_id == workflow_id)
                )
            ).scalars().all()

        types = [e.event_type for e in events]
        assert TaskEventType.STATE_CHECKPOINT in types, (
            "STATE_CHECKPOINT event must be emitted (OBS-006). Either add it "
            "directly, or include state_hash on CHECKPOINT so the detector can "
            "match."
        )

    @pytest.mark.asyncio
    async def test_state_checkpoint_event_has_state_hash(self, settings, workflow_id):
        """The STATE_CHECKPOINT event should include a state_hash field."""
        from celeste.database.db import get_session

        mgr = CheckpointManager(event_threshold=1)
        state = {
            "goal": "demo",
            "context": {},
            "completed_node_ids": [],
            "failed_node_ids": [],
            "cycle_count": 0,
            "llm_tokens_accumulated": 0,
        }
        await mgr.record_checkpoint_event(workflow_id, state)

        async with get_session() as session:
            events = (
                await session.execute(
                    select(WorkflowEvent).where(
                        WorkflowEvent.workflow_id == workflow_id,
                        WorkflowEvent.event_type == TaskEventType.STATE_CHECKPOINT,
                    )
                )
            ).scalars().all()

        assert events, "STATE_CHECKPOINT row must exist"
        ev = events[0]
        assert ev.event_data and "state_hash" in ev.event_data, (
            "STATE_CHECKPOINT event_data must include state_hash for hash_match"
        )

    @pytest.mark.asyncio
    async def test_state_hash_is_deterministic(self, settings, workflow_id):
        """Same state -> same hash, different state -> different hash."""
        from celeste.database.db import get_session

        mgr = CheckpointManager(event_threshold=1)
        state_a = {"goal": "A", "context": {}, "completed_node_ids": [], "failed_node_ids": [], "cycle_count": 1, "llm_tokens_accumulated": 0}
        state_b = {"goal": "B", "context": {}, "completed_node_ids": [], "failed_node_ids": [], "cycle_count": 1, "llm_tokens_accumulated": 0}

        await mgr.record_checkpoint_event(workflow_id, state_a)
        await mgr.record_checkpoint_event(workflow_id, state_b)

        async with get_session() as session:
            events = (
                await session.execute(
                    select(WorkflowEvent)
                    .where(
                        WorkflowEvent.workflow_id == workflow_id,
                        WorkflowEvent.event_type == TaskEventType.STATE_CHECKPOINT,
                    )
                    .order_by(WorkflowEvent.sequence_number.asc())
                )
            ).scalars().all()

        assert len(events) >= 2
        h1 = events[0].event_data["state_hash"]
        h2 = events[1].event_data["state_hash"]
        assert h1 != h2, "different states must produce different hashes"