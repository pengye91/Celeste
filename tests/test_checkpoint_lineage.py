"""Tests for checkpoint lineage (TODO-20): parent_workflow_id.

Follows strict TDD: these tests document the lineage contract added by
TODO-20 and guard against regressions.

Covers:
- The Workflow.parent_workflow_id column exists and defaults to None.
- Engine._check_and_checkpoint sets parent_workflow_id on the new run.
- GET /api/workflows and GET /api/workflows/{id} expose parent_workflow_id.
- Self-referential relationship (parent / children) resolves correctly.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from celeste.config.settings import EngineSettings
from celeste.core.checkpoint import CheckpointManager
from celeste.core.engine import Engine
from celeste.database.db import close_db, get_session, init_db
from celeste.database.models import (
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowEvent,
)


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _reset_db_module():
    """Reset database module state between tests."""
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
    """Provide test EngineSettings with in-memory SQLite."""
    return EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL)


# ---------------------------------------------------------------------------
# Model contract
# ---------------------------------------------------------------------------


async def test_workflow_parent_workflow_id_defaults_to_none(settings):
    """A top-level workflow must have parent_workflow_id == None."""
    await init_db(settings=settings)
    wf_id = uuid.uuid4()
    async with get_session() as session:
        session.add(
            Workflow(
                id=wf_id,
                name="top-level",
                status="pending",
                dag_definition={},
            )
        )

    async with get_session() as session:
        result = await session.execute(select(Workflow).where(Workflow.id == wf_id))
        wf = result.scalar_one()
        assert wf.parent_workflow_id is None


# ---------------------------------------------------------------------------
# Engine._check_and_checkpoint sets lineage
# ---------------------------------------------------------------------------


async def test_check_and_checkpoint_sets_parent_workflow_id(settings):
    """Continue-As-New must set parent_workflow_id on the new run."""
    await init_db(settings=settings)
    engine = Engine(settings=settings)
    await engine.start()
    try:
        wf_id = uuid.uuid4()
        node_id = uuid.uuid4()
        async with get_session() as session:
            session.add(
                Workflow(
                    id=wf_id,
                    name="lineage-source",
                    status="running",
                    dag_definition={"goal": "do work"},
                )
            )
            session.add(
                TaskNode(
                    id=node_id,
                    workflow_id=wf_id,
                    name="step_a",
                    task_type="tool_execution",
                    status=TaskNodeStatus.COMPLETED,
                    command="echo done",
                    arguments={},
                )
            )
            session.add(
                WorkflowEvent(
                    workflow_id=wf_id,
                    event_type=TaskEventType.CYCLE_STARTED,
                    sequence_number=1,
                )
            )

        checkpoint_mgr = CheckpointManager(settings=settings, event_threshold=1)
        new_wf_id = await engine._check_and_checkpoint(wf_id, checkpoint_mgr)

        assert new_wf_id is not None
        assert new_wf_id != wf_id

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == new_wf_id)
            )
            new_wf = result.scalar_one()
            # TODO-20 contract: the new run carries the lineage pointer.
            assert new_wf.parent_workflow_id == wf_id
    finally:
        await engine.stop()


async def test_workflow_relationship_resolves_parent_and_children(settings):
    """The self-referential parent/children relationship must resolve."""
    await init_db(settings=settings)
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    async with get_session() as session:
        session.add(
            Workflow(
                id=parent_id,
                name="parent",
                status="cancelled",
                dag_definition={},
            )
        )
        session.add(
            Workflow(
                id=child_id,
                name="child",
                status="pending",
                dag_definition={},
                parent_workflow_id=parent_id,
            )
        )

    async with get_session() as session:
        child = await session.get(Workflow, child_id)
        # Force load of the relationship.
        assert child is not None
        assert child.parent_workflow_id == parent_id

        parent = await session.get(Workflow, parent_id)
        assert parent is not None
        # children backref should include the child we created.
        await session.refresh(parent, attribute_names=["children"])
        child_ids = {c.id for c in parent.children}
        assert child_id in child_ids


# ---------------------------------------------------------------------------
# API exposure: parent_workflow_id in list + detail responses
# ---------------------------------------------------------------------------


async def test_list_workflows_exposes_parent_workflow_id(settings):
    """GET /api/workflows items include parent_workflow_id."""
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

    await init_db(settings=settings)
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    async with get_session() as session:
        session.add(Workflow(id=parent_id, name="parent", status="cancelled", dag_definition={}))
        session.add(Workflow(
            id=child_id, name="child", status="completed", dag_definition={},
            parent_workflow_id=parent_id,
        ))
        session.add(Workflow(id=uuid.uuid4(), name="top", status="pending", dag_definition={}))

    app = create_app(settings=settings, workspace_factory=lambda: _NoopWorkspace())
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/workflows")
            assert resp.status_code == 200
            items = resp.json()["items"]
            by_name = {item["name"]: item for item in items}
            # The child must carry the lineage pointer.
            assert by_name["child"]["parent_workflow_id"] == str(parent_id)
            # The top-level workflow must have None.
            assert by_name["top"]["parent_workflow_id"] is None
    finally:
        await lifespan_cm.__aexit__(None, None, None)


async def test_get_workflow_detail_exposes_parent_workflow_id(settings):
    """GET /api/workflows/{id} includes parent_workflow_id."""
    import httpx
    from celeste.api.app import create_app
    from celeste.core.workspaces.base import BaseWorkspace

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

    await init_db(settings=settings)
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    async with get_session() as session:
        session.add(Workflow(id=parent_id, name="parent", status="cancelled", dag_definition={}))
        session.add(Workflow(
            id=child_id, name="child", status="running", dag_definition={},
            parent_workflow_id=parent_id,
        ))

    app = create_app(settings=settings, workspace_factory=lambda: _NoopWorkspace())
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/workflows/{child_id}")
            assert resp.status_code == 200
            assert resp.json()["parent_workflow_id"] == str(parent_id)
    finally:
        await lifespan_cm.__aexit__(None, None, None)
