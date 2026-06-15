"""Tests for workflow retention policy and cleanup (TODO-19).

Follows strict TDD. Covers:
- WORKFLOW_RETENTION_DAYS setting default (0 = disabled) + validation.
- cleanup_old_workflows() deletes only old, terminal workflows.
- Non-terminal (pending/running/paused) workflows are never deleted.
- Lineage parents (TODO-20) are protected: a terminal parent with a live
  child run is preserved so the "continued as" chain is never severed.
- count_retention_candidates() reports the raw backlog.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.database.db import get_session, init_db
from celeste.database.models import Workflow, WorkflowStatus
from celeste.database.retention import (
    TERMINAL_STATUSES,
    cleanup_old_workflows,
    count_retention_candidates,
)


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _reset_db_module():
    import celeste.database.db as db_mod

    db_mod._engine = None
    db_mod._async_session_factory = None
    yield
    if db_mod._engine is not None:
        try:
            await db_mod._engine.dispose()
        except Exception:
            pass
    db_mod._engine = None
    db_mod._async_session_factory = None


@pytest.fixture
def settings():
    return EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL)


async def _make_workflow(
    *,
    name: str,
    status: WorkflowStatus,
    created_at: datetime,
    parent_workflow_id: uuid.UUID | None = None,
) -> uuid.UUID:
    wf_id = uuid.uuid4()
    async with get_session() as session:
        session.add(
            Workflow(
                id=wf_id,
                name=name,
                status=status,
                dag_definition={},
                created_at=created_at,
                updated_at=created_at,
                parent_workflow_id=parent_workflow_id,
            )
        )
    return wf_id


# ---------------------------------------------------------------------------
# Settings contract
# ---------------------------------------------------------------------------


def test_retention_default_is_disabled():
    s = EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL)
    assert s.WORKFLOW_RETENTION_DAYS == 0


def test_retention_can_be_enabled():
    s = EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL, WORKFLOW_RETENTION_DAYS=30)
    assert s.WORKFLOW_RETENTION_DAYS == 30


def test_retention_negative_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL, WORKFLOW_RETENTION_DAYS=-1)


# ---------------------------------------------------------------------------
# cleanup_old_workflows
# ---------------------------------------------------------------------------


async def test_disabled_retention_is_a_noop(settings):
    """WORKFLOW_RETENTION_DAYS=0 must never delete anything."""
    await init_db(settings=settings)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=400)
    await _make_workflow(name="old-completed", status=WorkflowStatus.COMPLETED, created_at=old)

    result = await cleanup_old_workflows(settings, now=now)
    assert result == {"deleted": 0}

    async with get_session() as session:
        count = len((await session.execute(select(Workflow))).scalars().all())
    assert count == 1


async def test_deletes_old_terminal_workflows(settings):
    await init_db(settings=settings)
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL, WORKFLOW_RETENTION_DAYS=30
    )
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=60)
    recent = now - timedelta(days=5)

    old_done = await _make_workflow(name="old-done", status=WorkflowStatus.COMPLETED, created_at=old)
    old_failed = await _make_workflow(name="old-failed", status=WorkflowStatus.FAILED, created_at=old)
    old_cancelled = await _make_workflow(name="old-cancelled", status=WorkflowStatus.CANCELLED, created_at=old)
    old_escalated = await _make_workflow(name="old-escalated", status=WorkflowStatus.ESCALATED, created_at=old)
    recent_done = await _make_workflow(name="recent-done", status=WorkflowStatus.COMPLETED, created_at=recent)

    result = await cleanup_old_workflows(settings, now=now)
    assert result["deleted"] == 4

    remaining_names = set()
    async with get_session() as session:
        for row in (await session.execute(select(Workflow))).scalars().all():
            remaining_names.add(row.name)
    assert remaining_names == {"recent-done"}
    # the four old terminal workflows are gone
    for name in ("old-done", "old-failed", "old-cancelled", "old-escalated"):
        assert name not in remaining_names


async def test_never_deletes_non_terminal_workflows(settings):
    """Pending / running / paused workflows are never reaped."""
    await init_db(settings=settings)
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL, WORKFLOW_RETENTION_DAYS=7
    )
    now = datetime.now(timezone.utc)
    ancient = now - timedelta(days=365)

    pending = await _make_workflow(name="pending", status=WorkflowStatus.PENDING, created_at=ancient)
    running = await _make_workflow(name="running", status=WorkflowStatus.RUNNING, created_at=ancient)
    paused = await _make_workflow(name="paused", status=WorkflowStatus.PAUSED, created_at=ancient)

    result = await cleanup_old_workflows(settings, now=now)
    assert result["deleted"] == 0

    async with get_session() as session:
        ids = {w.id for w in (await session.execute(select(Workflow))).scalars().all()}
    assert {pending, running, paused} <= ids


async def test_lineage_parent_is_protected(settings):
    """A terminal parent with a child run must NOT be deleted (TODO-20)."""
    await init_db(settings=settings)
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL, WORKFLOW_RETENTION_DAYS=7
    )
    now = datetime.now(timezone.utc)
    ancient = now - timedelta(days=365)
    recent = now - timedelta(days=1)

    # Old terminal parent...
    parent_id = await _make_workflow(
        name="parent", status=WorkflowStatus.CANCELLED, created_at=ancient
    )
    # ...with a recent child run that is itself non-terminal (running).
    child_id = await _make_workflow(
        name="child",
        status=WorkflowStatus.RUNNING,
        created_at=recent,
        parent_workflow_id=parent_id,
    )

    result = await cleanup_old_workflows(settings, now=now)
    assert result["deleted"] == 0  # parent protected by lineage

    async with get_session() as session:
        ids = {w.id for w in (await session.execute(select(Workflow))).scalars().all()}
    assert parent_id in ids
    assert child_id in ids


async def test_lineage_collapses_when_child_also_old_and_terminal(settings):
    """Once the child is itself old + terminal, the whole chain is deleted."""
    await init_db(settings=settings)
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL, WORKFLOW_RETENTION_DAYS=7
    )
    now = datetime.now(timezone.utc)
    ancient = now - timedelta(days=365)

    # NOTE: child must be inserted BEFORE the parent so the deletion sweep
    # ordering is deterministic. Both are old + terminal here.
    child_id = await _make_workflow(
        name="child",
        status=WorkflowStatus.COMPLETED,
        created_at=ancient,
    )
    parent_id = await _make_workflow(
        name="parent",
        status=WorkflowStatus.CANCELLED,
        created_at=ancient,
        parent_workflow_id=child_id,  # parent points at the even-older child
    )
    # Re-orient: the "parent" row above references child_id, but to test the
    # collapse we want parent_id -> child. Fix the lineage by deleting and
    # recreating with the correct pointer.

    # Simpler: just build a two-step chain where BOTH are old+terminal.
    # Clear and rebuild cleanly.
    from celeste.database.db import close_db
    await close_db()
    await init_db(settings=settings)

    ancestor = await _make_workflow(
        name="ancestor", status=WorkflowStatus.COMPLETED, created_at=ancient
    )
    descendant = await _make_workflow(
        name="descendant",
        status=WorkflowStatus.FAILED,
        created_at=ancient,
        parent_workflow_id=ancestor,
    )

    # First sweep: ancestor is protected because descendant references it.
    result1 = await cleanup_old_workflows(settings, now=now)
    assert result1["deleted"] == 1  # only the leaf (descendant) has no child

    # Second sweep: ancestor is now childless and eligible.
    result2 = await cleanup_old_workflows(settings, now=now)
    assert result2["deleted"] == 1

    async with get_session() as session:
        ids = {w.id for w in (await session.execute(select(Workflow))).scalars().all()}
    assert ids == set()


# ---------------------------------------------------------------------------
# count_retention_candidates
# ---------------------------------------------------------------------------


async def test_count_candidates_reports_backlog(settings):
    await init_db(settings=settings)
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL, WORKFLOW_RETENTION_DAYS=30
    )
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=60)
    recent = now - timedelta(days=5)

    await _make_workflow(name="old-done", status=WorkflowStatus.COMPLETED, created_at=old)
    await _make_workflow(name="old-failed", status=WorkflowStatus.FAILED, created_at=old)
    await _make_workflow(name="recent-done", status=WorkflowStatus.COMPLETED, created_at=recent)
    await _make_workflow(name="running", status=WorkflowStatus.RUNNING, created_at=old)

    # count includes lineage parents (raw backlog), unlike cleanup.
    assert await count_retention_candidates(settings, now=now) == 2


def test_terminal_statuses_cover_expected_set():
    assert set(TERMINAL_STATUSES) == {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.ESCALATED,
    }


# ---------------------------------------------------------------------------
# Engine retention sweep loop integration
# ---------------------------------------------------------------------------


async def test_engine_starts_retention_loop_when_enabled():
    """Engine.start() launches the background sweep when retention > 0."""
    from celeste.core.engine import Engine

    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        WORKFLOW_RETENTION_DAYS=7,
    )
    engine = Engine(settings=settings)
    await engine.start()
    try:
        assert engine._retention_task is not None
        assert not engine._retention_task.done()
    finally:
        await engine.stop()


async def test_engine_does_not_start_retention_loop_when_disabled():
    """Engine.start() does NOT launch the sweep when retention = 0."""
    from celeste.core.engine import Engine

    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        WORKFLOW_RETENTION_DAYS=0,
    )
    engine = Engine(settings=settings)
    await engine.start()
    try:
        assert engine._retention_task is None
    finally:
        await engine.stop()


async def test_engine_stop_cancels_retention_loop():
    """Engine.stop() cancels and awaits the retention sweep task."""
    from celeste.core.engine import Engine

    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        WORKFLOW_RETENTION_DAYS=7,
    )
    engine = Engine(settings=settings)
    await engine.start()
    task = engine._retention_task
    assert task is not None

    await engine.stop()
    assert engine._retention_task is None
    assert task.cancelled() or task.done()


async def test_retention_loop_swallows_exceptions():
    """A sweep failure must not crash the engine."""
    from celeste.core.engine import Engine
    from celeste.database import retention as retention_mod

    call_count = 0

    original = retention_mod.cleanup_old_workflows

    async def _failing_cleanup(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated DB error")

    retention_mod.cleanup_old_workflows = _failing_cleanup
    try:
        settings = EngineSettings(
            DATABASE_URL=SQLITE_MEMORY_URL,
            WORKFLOW_RETENTION_DAYS=7,
        )
        engine = Engine(settings=settings)
        # Temporarily shorten the sleep interval so the loop ticks fast.
        engine._RETENTION_SWEEP_INTERVAL_SECONDS = 0
        await engine.start()
        # Give the loop time to run a failing sweep.
        import asyncio

        await asyncio.sleep(0.3)
        assert call_count > 0
        # Engine must still be running (loop swallowed the error).
        assert engine._running
        await engine.stop()
    finally:
        retention_mod.cleanup_old_workflows = original


# ---------------------------------------------------------------------------
# POST /api/admin/retention/cleanup endpoint
# ---------------------------------------------------------------------------


async def test_retention_cleanup_endpoint_deletes_old_workflows():
    """POST /api/admin/retention/cleanup triggers a sweep and reports counts."""
    import httpx
    from celeste.api.app import create_app
    from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
    import asyncio

    class _NoopWorkspace(BaseWorkspace):
        @property
        def is_active(self):
            return False

        async def setup(self):
            pass

        async def execute(self, command, arguments=None, env=None):
            return
            yield  # type: ignore[misc]

        async def teardown(self):
            pass

        async def get_workspace_path(self):
            return "/tmp"

    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        WORKFLOW_RETENTION_DAYS=7,
        MAX_PARALLEL_SUBPROCESSES=2,
    )
    await init_db(settings=settings)

    # Seed an old terminal workflow + a recent one.
    now = datetime.now(timezone.utc)
    ancient = now - timedelta(days=365)
    await _make_workflow(name="old-done", status=WorkflowStatus.COMPLETED, created_at=ancient)
    await _make_workflow(name="recent", status=WorkflowStatus.RUNNING, created_at=now)

    app = create_app(settings=settings, workspace_factory=lambda: _NoopWorkspace())
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/retention/cleanup")
            assert resp.status_code == 200
            data = resp.json()
            assert data["deleted"] == 1
            assert data["retention_days"] == 7
            assert isinstance(data["candidates"], int)
    finally:
        await lifespan_cm.__aexit__(None, None, None)


async def test_retention_cleanup_endpoint_noop_when_disabled():
    """When retention is disabled (0), the endpoint reports deleted=0."""
    import httpx
    from celeste.api.app import create_app
    from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent

    class _NoopWorkspace(BaseWorkspace):
        @property
        def is_active(self):
            return False

        async def setup(self):
            pass

        async def execute(self, command, arguments=None, env=None):
            return
            yield  # type: ignore[misc]

        async def teardown(self):
            pass

        async def get_workspace_path(self):
            return "/tmp"

    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        WORKFLOW_RETENTION_DAYS=0,
        MAX_PARALLEL_SUBPROCESSES=2,
    )
    await init_db(settings=settings)

    app = create_app(settings=settings, workspace_factory=lambda: _NoopWorkspace())
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/retention/cleanup")
            assert resp.status_code == 200
            data = resp.json()
            assert data["deleted"] == 0
            assert data["retention_days"] == 0
    finally:
        await lifespan_cm.__aexit__(None, None, None)
