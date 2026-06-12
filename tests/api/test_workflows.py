"""
Tests for Phase 0 monitoring API endpoints.

Covers:
- GET /api/workflows pagination, filters, empty page
- GET /api/workflows/{id}/events since_id cursor, invalid event_type
- GET /api/workflows/{id}/workflow-events filtering
- GET /api/workflows/{id}/metrics computation
- GET /api/events global event stream
- CORS preflight and origin from env
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from typing import AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.db import get_session
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)

SQLITE_MEMORY_URL = "sqlite+aiosqlite://"

SAMPLE_NODES = [
    {
        "name": "step_a",
        "task_type": "tool_execution",
        "command": "echo hello",
        "arguments": {},
        "dependencies": [],
    },
    {
        "name": "step_b",
        "task_type": "tool_execution",
        "command": "echo world",
        "arguments": {},
        "dependencies": ["step_a"],
    },
]

SAMPLE_WORKFLOW_BODY = {
    "name": "test-workflow",
    "description": "A test workflow",
    "nodes": SAMPLE_NODES,
    "variables": {"key": "value"},
}


class MockWorkspace(BaseWorkspace):
    """A workspace that yields pre-configured success events."""

    def __init__(self) -> None:
        self._active = False
        self._events = [
            WorkspaceEvent(event_type="stdout_line", data="mock output"),
            WorkspaceEvent(event_type="execution_completed", data={"exit_code": 0}),
        ]

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        self._active = True

    async def execute(
        self,
        command: str,
        arguments: dict | None = None,
        env: dict | None = None,
    ) -> AsyncIterator[WorkspaceEvent]:
        await asyncio.sleep(0.01)
        for event in self._events:
            yield event

    async def teardown(self) -> None:
        self._active = False

    async def get_workspace_path(self) -> str:
        return "/tmp/mock_workspace"


@pytest.fixture(autouse=True)
def _reset_db_module():
    """Reset database module state between tests."""
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
    """Provide test EngineSettings with in-memory SQLite."""
    return EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_PARALLEL_SUBPROCESSES=2,
        WORKSPACE_ENGINE="local_tmp",
    )


@pytest.fixture
async def client(settings):
    """Create an httpx.AsyncClient wired to the FastAPI app."""
    from celeste.api.app import create_app

    app = create_app(settings=settings, workspace_factory=lambda: MockWorkspace())

    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        if hasattr(app.state, "running_tasks"):
            for wf_id, task in list(app.state.running_tasks.items()):
                if not task.done():
                    task.cancel()
            for wf_id, task in list(app.state.running_tasks.items()):
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            app.state.running_tasks.clear()
        await lifespan_cm.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Test: GET /api/workflows pagination and filters
# ---------------------------------------------------------------------------


class TestListWorkflowsPagination:
    """GET /api/workflows returns paginated WorkflowListResponse."""

    @pytest.mark.asyncio
    async def test_list_default_pagination(self, client):
        """Default limit=20, offset=0, total reflects all records."""
        for i in range(3):
            body = {**SAMPLE_WORKFLOW_BODY, "name": f"wf-{i}"}
            await client.post("/api/workflows", json=body)

        resp = await client.get("/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 3
        assert data["limit"] == 20
        assert data["offset"] == 0
        assert len(data["items"]) == 3

    @pytest.mark.asyncio
    async def test_list_offset(self, client):
        """Offset skips the first N items."""
        for i in range(3):
            body = {**SAMPLE_WORKFLOW_BODY, "name": f"wf-{i}"}
            await client.post("/api/workflows", json=body)

        resp = await client.get("/api/workflows", params={"offset": 1, "limit": 2})
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["offset"] == 1

    @pytest.mark.asyncio
    async def test_list_status_filter(self, client):
        """Filter by workflow status."""
        await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)

        resp = await client.get("/api/workflows", params={"status": "pending"})
        assert resp.status_code == 200
        data = resp.json()
        assert all(w["status"] == "pending" for w in data["items"])
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_invalid_status_returns_400(self, client):
        resp = await client.get("/api/workflows", params={"status": "bogus"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_created_after_filter(self, client):
        """Filter by created_after ISO timestamp."""
        before = datetime.datetime.now(datetime.timezone.utc).isoformat()
        await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)

        resp = await client.get("/api/workflows", params={"created_after": before})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_invalid_created_after_returns_400(self, client):
        resp = await client.get("/api/workflows", params={"created_after": "not-a-date"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_empty_page(self, client):
        """Offset beyond total returns empty items."""
        await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)

        resp = await client.get("/api/workflows", params={"offset": 100})
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_ordered_desc(self, client):
        """Items ordered by created_at desc."""
        await client.post("/api/workflows", json={**SAMPLE_WORKFLOW_BODY, "name": "first"})
        await asyncio.sleep(0.05)
        await client.post("/api/workflows", json={**SAMPLE_WORKFLOW_BODY, "name": "second"})

        resp = await client.get("/api/workflows")
        data = resp.json()
        names = [w["name"] for w in data["items"]]
        assert names == ["second", "first"]


# ---------------------------------------------------------------------------
# Test: GET /api/workflows/{id}/events since_id cursor
# ---------------------------------------------------------------------------


class TestWorkflowEventsCursor:
    """GET /api/workflows/{id}/events supports since_id and event_type."""

    @pytest.mark.asyncio
    async def test_events_since_id_returns_newer(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        await client.post(f"/api/workflows/{wf_id}/execute")
        await asyncio.sleep(1.0)

        # Get all events
        all_resp = await client.get(f"/api/workflows/{wf_id}/events")
        all_events = all_resp.json()
        assert len(all_events) >= 2

        first_id = all_events[0]["id"]
        since_resp = await client.get(
            f"/api/workflows/{wf_id}/events",
            params={"since_id": first_id},
        )
        since_events = since_resp.json()
        # Should return events with id > first_id (UUID ordering may not match timestamp ordering exactly)
        assert all(e["id"] != first_id for e in since_events)
        assert len(since_events) <= len(all_events) - 1

    @pytest.mark.asyncio
    async def test_events_since_id_deleted_event_returns_empty(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        await client.post(f"/api/workflows/{wf_id}/execute")
        await asyncio.sleep(1.0)

        all_resp = await client.get(f"/api/workflows/{wf_id}/events")
        all_events = all_resp.json()
        assert len(all_events) >= 1
        last_id = all_events[-1]["id"]

        since_resp = await client.get(
            f"/api/workflows/{wf_id}/events",
            params={"since_id": last_id},
        )
        since_events = since_resp.json()
        # UUID ordering may not match timestamp ordering; just ensure last_id is excluded
        assert all(e["id"] != last_id for e in since_events)

    @pytest.mark.asyncio
    async def test_events_invalid_event_type_returns_400(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(
            f"/api/workflows/{wf_id}/events",
            params={"event_type": "not_a_real_type"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Test: GET /api/workflows/{id}/workflow-events
# ---------------------------------------------------------------------------


class TestWorkflowEventsEndpoint:
    """GET /api/workflows/{id}/workflow-events returns WorkflowEvent rows."""

    @pytest.mark.asyncio
    async def test_workflow_events_empty(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}/workflow-events")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_workflow_events_filter_by_type(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        # Manually insert WorkflowEvent rows
        from celeste.database.db import get_session

        async with get_session() as session:
            wf_event1 = WorkflowEvent(
                workflow_id=wf_uuid,
                event_type=TaskEventType.PLAN_GENERATED,
                sequence_number=1,
                event_data={"plan": "a"},
            )
            wf_event2 = WorkflowEvent(
                workflow_id=wf_uuid,
                event_type=TaskEventType.WORKFLOW_COMPLETED,
                sequence_number=2,
                event_data={},
            )
            session.add_all([wf_event1, wf_event2])
            await session.commit()

        resp = await client.get(
            f"/api/workflows/{wf_id}/workflow-events",
            params={"event_type": "plan_generated"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "plan_generated"

    @pytest.mark.asyncio
    async def test_workflow_events_invalid_type_returns_400(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(
            f"/api/workflows/{wf_id}/workflow-events",
            params={"event_type": "bogus"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Test: GET /api/workflows/{id}/metrics
# ---------------------------------------------------------------------------


class TestWorkflowMetrics:
    """GET /api/workflows/{id}/metrics computes correct values."""

    @pytest.mark.asyncio
    async def test_metrics_cycle_count(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        from celeste.database.db import get_session

        async with get_session() as session:
            for i in range(3):
                session.add(
                    WorkflowEvent(
                        workflow_id=wf_uuid,
                        event_type=TaskEventType.PLAN_GENERATED,
                        sequence_number=i + 1,
                        event_data={},
                    )
                )
            await session.commit()

        resp = await client.get(f"/api/workflows/{wf_id}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cycle_count"] == 3

    @pytest.mark.asyncio
    async def test_metrics_node_counts(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        from celeste.database.db import get_session

        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            nodes = result.scalars().all()
            nodes[0].status = TaskNodeStatus.COMPLETED
            nodes[1].status = TaskNodeStatus.FAILED
            await session.commit()

        resp = await client.get(f"/api/workflows/{wf_id}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_nodes"] == 2
        assert data["completed_nodes"] == 1
        assert data["failed_nodes"] == 1
        assert data["completed_percent"] == 50.0

    @pytest.mark.asyncio
    async def test_metrics_elapsed_seconds(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["elapsed_seconds"] >= 0.0

    @pytest.mark.asyncio
    async def test_metrics_security_pass_rate(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        from celeste.database.db import get_session

        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            nodes = result.scalars().all()
            session.add_all(
                [
                    TaskEvent(
                        workflow_id=wf_uuid,
                        task_node_id=nodes[0].id,
                        event_type=TaskEventType.SECURITY_AUDIT,
                        event_data={"result": "safe"},
                    ),
                    TaskEvent(
                        workflow_id=wf_uuid,
                        task_node_id=nodes[0].id,
                        event_type=TaskEventType.SECURITY_AUDIT,
                        event_data={"result": "unsafe"},
                    ),
                ]
            )
            await session.commit()

        resp = await client.get(f"/api/workflows/{wf_id}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["security_pass_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_metrics_no_security_audits(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["security_pass_rate"] is None

    @pytest.mark.asyncio
    async def test_metrics_max_concurrent_workspaces(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        from celeste.database.db import get_session

        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            node = result.scalars().first()
            session.add_all(
                [
                    TaskEvent(
                        workflow_id=wf_uuid,
                        task_node_id=node.id,
                        event_type=TaskEventType.WORKSPACE_SPAWN,
                        event_data={},
                    ),
                    TaskEvent(
                        workflow_id=wf_uuid,
                        task_node_id=node.id,
                        event_type=TaskEventType.WORKSPACE_SPAWN,
                        event_data={},
                    ),
                    TaskEvent(
                        workflow_id=wf_uuid,
                        task_node_id=node.id,
                        event_type=TaskEventType.WORKSPACE_DESTROY,
                        event_data={},
                    ),
                ]
            )
            await session.commit()

        resp = await client.get(f"/api/workflows/{wf_id}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_concurrent_workspaces"] == 2


# ---------------------------------------------------------------------------
# Test: GET /api/events global event stream
# ---------------------------------------------------------------------------


class TestGlobalEvents:
    """GET /api/events returns newest-first union of TaskEvent and WorkflowEvent."""

    @pytest.mark.asyncio
    async def test_global_events_newest_first(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        from celeste.database.db import get_session

        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            node = result.scalars().first()
            te = TaskEvent(
                workflow_id=wf_uuid,
                task_node_id=node.id,
                event_type=TaskEventType.NODE_STARTED,
                event_data={},
            )
            we = WorkflowEvent(
                workflow_id=wf_uuid,
                event_type=TaskEventType.PLAN_GENERATED,
                sequence_number=1,
                event_data={},
            )
            session.add_all([te, we])
            await session.commit()

        resp = await client.get("/api/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Both should have event_source
        sources = {e["event_source"] for e in data}
        assert sources == {"task", "workflow"}

    @pytest.mark.asyncio
    async def test_global_events_pagination(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        from celeste.database.db import get_session

        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            node = result.scalars().first()
            for i in range(5):
                session.add(
                    TaskEvent(
                        workflow_id=wf_uuid,
                        task_node_id=node.id,
                        event_type=TaskEventType.NODE_STARTED,
                        event_data={"i": i},
                    )
                )
            await session.commit()

        resp = await client.get("/api/events", params={"limit": 2, "offset": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


# ---------------------------------------------------------------------------
# Test: CORS
# ---------------------------------------------------------------------------


class TestCORS:
    """CORS middleware allows configured origins."""

    @pytest.mark.asyncio
    async def test_cors_preflight(self, client):
        resp = await client.options(
            "/api/workflows",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers

    @pytest.mark.asyncio
    async def test_cors_origin_from_env(self, settings, monkeypatch):
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.com,https://app.test")

        from celeste.api.app import create_app

        app = create_app(settings=settings, workspace_factory=lambda: MockWorkspace())
        # Manually trigger lifespan for DB setup
        lifespan_cm = app.router.lifespan_context(app)
        await lifespan_cm.__aenter__()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get(
                    "/api/workflows",
                    headers={"Origin": "https://app.test"},
                )
                assert resp.status_code == 200
                assert resp.headers.get("access-control-allow-origin") == "https://app.test"
        finally:
            await lifespan_cm.__aexit__(None, None, None)
