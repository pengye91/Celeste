"""
Tests for Bug C: API must emit timezone-aware (UTC) ISO 8601 datetimes.

Root cause: SQLite/aiosqlite strips ``tzinfo`` on retrieval, so DB-sourced
datetimes are naive (UTC value, no offset). ``.isoformat()`` then yields a
string with NO timezone marker, which the frontend ``new Date(iso)`` parses
as LOCAL time — producing wrong relative times ("8h ago" for a minutes-old
workflow).

These tests assert every serialized DB datetime ends with ``+00:00`` so the
frontend interprets it as UTC.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    WorkflowEvent,
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
]

SAMPLE_WORKFLOW_BODY = {
    "name": "tz-test-workflow",
    "description": "A test workflow",
    "nodes": SAMPLE_NODES,
    "variables": {},
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


class TestUtcIsoSerialization:
    """Serialized DB datetimes must end with ``+00:00`` (timezone-aware UTC)."""

    @pytest.mark.asyncio
    async def test_list_workflows_created_at_is_utc(self, client):
        """GET /api/workflows items carry a +00:00 created_at."""
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        assert create_resp.status_code in (200, 201)

        resp = await client.get("/api/workflows")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        created_at = items[0]["created_at"]
        assert created_at.endswith("+00:00"), (
            f"created_at must be timezone-aware UTC, got: {created_at!r}"
        )

    @pytest.mark.asyncio
    async def test_workflow_detail_created_and_updated_are_utc(self, client):
        """GET /api/workflows/{id} returns +00:00 created_at and updated_at."""
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["created_at"].endswith("+00:00"), (
            f"created_at must be UTC, got: {data['created_at']!r}"
        )
        assert data["updated_at"].endswith("+00:00"), (
            f"updated_at must be UTC, got: {data['updated_at']!r}"
        )

    @pytest.mark.asyncio
    async def test_workflow_events_timestamp_is_utc(self, client):
        """GET /api/workflows/{id}/events timestamps carry +00:00."""
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        from celeste.database.db import get_session

        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            node = result.scalars().first()
            session.add(
                TaskEvent(
                    workflow_id=wf_uuid,
                    task_node_id=node.id,
                    event_type=TaskEventType.NODE_STARTED,
                    event_data={},
                )
            )
            await session.commit()

        resp = await client.get(f"/api/workflows/{wf_id}/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        for e in events:
            assert e["timestamp"].endswith("+00:00"), (
                f"event timestamp must be UTC, got: {e['timestamp']!r}"
            )

    @pytest.mark.asyncio
    async def test_workflow_events_workflow_source_timestamp_is_utc(self, client):
        """GET /api/workflows/{id}/workflow-events timestamps carry +00:00."""
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        from celeste.database.db import get_session

        async with get_session() as session:
            session.add(
                WorkflowEvent(
                    workflow_id=wf_uuid,
                    event_type=TaskEventType.PLAN_GENERATED,
                    sequence_number=1,
                    event_data={},
                )
            )
            await session.commit()

        resp = await client.get(f"/api/workflows/{wf_id}/workflow-events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        for e in events:
            assert e["timestamp"].endswith("+00:00"), (
                f"workflow-event timestamp must be UTC, got: {e['timestamp']!r}"
            )
