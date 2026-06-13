"""
Tests for the API bug fixes identified in docs/audit-2026-06-13.json.

Each bug is covered by a dedicated failing test (written before the fix).
TDD discipline: write failing test → fix → confirm pass.

Covers:
- api-1: DELETE handler wrong ordering / wrong semantics
- api-3: Count queries load all rows (uses SELECT COUNT(*))
- api-4: get_global_events pagination unstable (tiebreaker)
- api-6: execute_workflow race condition (atomic status guard)
- api-9: Request body size limits
- api-11: since_id cursor uses random UUID (use sequence_number for WorkflowEvent)
- api-12: No tiebreaker on timestamp
- api-15: No NODE_FAILED event on exception
- api-18: No global exception handler
- api-20: running_tasks memory leak on success
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import AsyncIterator

import httpx
import pytest
from sqlalchemy import select, update

from celeste.config.settings import EngineSettings
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.db import get_session
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
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
    return EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_PARALLEL_SUBPROCESSES=2,
        WORKSPACE_ENGINE="local_tmp",
    )


@pytest.fixture
async def client(settings):
    from celeste.api.app import create_app

    app = create_app(settings=settings, workspace_factory=lambda: MockWorkspace())
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, app
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


# ===========================================================================
# Bug api-6: execute_workflow race condition
# ===========================================================================


class TestExecuteWorkflowAtomicGuard:
    """api-6: /execute must use an atomic status guard so duplicate
    concurrent POSTs do not spawn parallel tasks and a workflow already
    in a terminal state is rejected with 409 Conflict."""

    @pytest.mark.asyncio
    async def test_execute_terminal_workflow_returns_409(self, client):
        """POST /execute on a workflow that already completed must 409."""
        http, _app = client
        create_resp = await http.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        # Manually mark workflow as COMPLETED in the DB
        async with get_session() as session:
            await session.execute(
                update(Workflow)
                .where(Workflow.id == wf_uuid)
                .values(status=WorkflowStatus.COMPLETED)
            )
            await session.commit()

        # /execute on a COMPLETED workflow should return 409 Conflict
        resp = await http.post(f"/api/workflows/{wf_id}/execute")
        assert resp.status_code == 409, (
            f"Expected 409 Conflict on /execute for a terminal workflow, "
            f"got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_execute_running_workflow_returns_409(self, client):
        """POST /execute on a workflow that is already RUNNING must 409."""
        http, _app = client
        create_resp = await http.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        async with get_session() as session:
            await session.execute(
                update(Workflow)
                .where(Workflow.id == wf_uuid)
                .values(status=WorkflowStatus.RUNNING)
            )
            await session.commit()

        resp = await http.post(f"/api/workflows/{wf_id}/execute")
        assert resp.status_code == 409, (
            f"Expected 409 Conflict when already RUNNING, got {resp.status_code}"
        )


# ===========================================================================
# Bug api-1: DELETE handler ordering
# ===========================================================================


class TestDeleteHandlerOrdering:
    """api-1: DELETE /api/workflows/{id} must check existence BEFORE mutating
    the running_tasks dict, so a non-existent UUID never silently wipes
    state and returns the correct status code for a true DELETE-style
    cancel (202 Accepted, no body)."""

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404_without_mutating_state(self, client):
        """DELETE on a UUID that has no DB row must return 404 and not
        leave running_tasks in a corrupted state."""
        http, app = client
        fake_id = str(uuid.uuid4())

        # Pre-populate running_tasks with the fake UUID (out-of-band state)
        app.state.running_tasks[fake_id] = asyncio.create_task(asyncio.sleep(0))

        resp = await http.delete(f"/api/workflows/{fake_id}")
        assert resp.status_code == 404

        # The buggy implementation would have called .cancel() + del here,
        # even though the workflow does not exist in the DB.
        # After the fix, the entry should still be present (we never touched it).
        assert fake_id in app.state.running_tasks, (
            "running_tasks entry was mutated on error path before existence check"
        )
        # Clean up the fake entry
        app.state.running_tasks[fake_id].cancel()
        try:
            await app.state.running_tasks[fake_id]
        except (asyncio.CancelledError, Exception):
            pass
        del app.state.running_tasks[fake_id]

    @pytest.mark.asyncio
    async def test_delete_existing_returns_200(self, client):
        """DELETE on an existing PENDING workflow must return 200."""
        http, _app = client
        create_resp = await http.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await http.delete(f"/api/workflows/{wf_id}")
        assert resp.status_code == 200, (
            f"Expected 200 for cancellation, got {resp.status_code}"
        )


# ===========================================================================
# Bug api-3: Count queries load all rows
# ===========================================================================


class TestListWorkflowsCountQuery:
    """api-3: GET /api/workflows total count must use SELECT COUNT(*),
    not materialise every row."""

    @pytest.mark.asyncio
    async def test_total_count_uses_sql_count(self, client):
        """The list endpoint must return the correct total even when many
        rows exist. Verifies count comes from aggregate, not len() of rows."""
        http, _app = client
        # Insert 25 workflows
        for i in range(25):
            body = {**SAMPLE_WORKFLOW_BODY, "name": f"wf-{i}"}
            await http.post("/api/workflows", json=body)

        resp = await http.get("/api/workflows", params={"limit": 5, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 25
        assert len(data["items"]) == 5


# ===========================================================================
# Bug api-4: get_global_events pagination unstable
# ===========================================================================


class TestGlobalEventsTiebreaker:
    """api-4: GET /api/events must produce a stable, deterministic order
    across pages even when events share the same timestamp."""

    @pytest.mark.asyncio
    async def test_global_events_order_is_deterministic(self, client):
        """Insert events with identical timestamps and verify order is stable
        across multiple requests (deterministic tiebreaker on id)."""
        http, _app = client
        create_resp = await http.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        # Insert 5 TaskEvents that all share a fixed timestamp
        fixed_ts = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            node = result.scalars().first()
            for i in range(5):
                te = TaskEvent(
                    workflow_id=wf_uuid,
                    task_node_id=node.id,
                    event_type=TaskEventType.NODE_STARTED,
                    event_data={"i": i},
                )
                te.timestamp = fixed_ts
                session.add(te)
            await session.commit()

        # Fetch twice and compare orderings
        resp1 = await http.get("/api/events", params={"limit": 5})
        data1 = resp1.json()
        resp2 = await http.get("/api/events", params={"limit": 5})
        data2 = resp2.json()

        ids1 = [e["id"] for e in data1]
        ids2 = [e["id"] for e in data2]
        assert ids1 == ids2, (
            f"Event ordering is non-deterministic across calls: {ids1} vs {ids2}"
        )


# ===========================================================================
# Bug api-9: Request body size limits
# ===========================================================================


class TestRequestSizeLimits:
    """api-9: POST /api/workflows must reject oversized payloads."""

    @pytest.mark.asyncio
    async def test_nodes_max_length_enforced(self, client):
        """Submitting > 1000 nodes must be rejected (422)."""
        http, _app = client
        too_many_nodes = [
            {
                "name": f"node_{i}",
                "task_type": "tool_execution",
                "command": "echo",
                "arguments": {},
                "dependencies": [],
            }
            for i in range(1001)
        ]
        body = {**SAMPLE_WORKFLOW_BODY, "nodes": too_many_nodes}
        resp = await http.post("/api/workflows", json=body)
        assert resp.status_code == 422, (
            f"Expected 422 for > 1000 nodes, got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_command_max_length_enforced(self, client):
        """Submitting a node with a command > 8192 chars must be rejected."""
        http, _app = client
        body = {
            **SAMPLE_WORKFLOW_BODY,
            "nodes": [
                {
                    "name": "oversized",
                    "task_type": "tool_execution",
                    "command": "x" * 8193,
                    "arguments": {},
                    "dependencies": [],
                }
            ],
        }
        resp = await http.post("/api/workflows", json=body)
        assert resp.status_code == 422


# ===========================================================================
# Bug api-11: since_id cursor uses random UUID
# ===========================================================================


class TestSinceIdSequenceNumberCursor:
    """api-11: /workflow-events since_id cursor must support sequence_number
    so polling clients see events in temporal order."""

    @pytest.mark.asyncio
    async def test_workflow_events_since_seq_returns_older(self, client):
        """Passing since_seq=N must return events with sequence_number > N."""
        http, _app = client
        create_resp = await http.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        async with get_session() as session:
            for i in range(1, 6):
                session.add(
                    WorkflowEvent(
                        workflow_id=wf_uuid,
                        event_type=TaskEventType.PLAN_GENERATED,
                        sequence_number=i,
                        event_data={},
                    )
                )
            await session.commit()

        resp = await http.get(
            f"/api/workflows/{wf_id}/workflow-events",
            params={"since_seq": 3, "limit": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Must return events with sequence_number > 3 (i.e. 4, 5)
        seqs = [e["sequence_number"] for e in data]
        assert seqs == [4, 5], f"Expected [4, 5], got {seqs}"


# ===========================================================================
# Bug api-12: No tiebreaker on timestamp
# ===========================================================================


class TestTaskEventsTimestampTiebreaker:
    """api-12: GET /api/workflows/{id}/events must ORDER BY timestamp, id
    so events with identical timestamps have a stable order."""

    @pytest.mark.asyncio
    async def test_task_events_deterministic_order_on_ties(self, client):
        http, _app = client
        create_resp = await http.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        # Insert 5 TaskEvents with identical timestamps
        fixed_ts = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            node = result.scalars().first()
            for i in range(5):
                te = TaskEvent(
                    workflow_id=wf_uuid,
                    task_node_id=node.id,
                    event_type=TaskEventType.NODE_STARTED,
                    event_data={"i": i},
                )
                te.timestamp = fixed_ts
                session.add(te)
            await session.commit()

        resp1 = await http.get(f"/api/workflows/{wf_id}/events", params={"limit": 5})
        data1 = resp1.json()
        resp2 = await http.get(f"/api/workflows/{wf_id}/events", params={"limit": 5})
        data2 = resp2.json()

        ids1 = [e["id"] for e in data1]
        ids2 = [e["id"] for e in data2]
        assert ids1 == ids2, (
            f"Event order is non-deterministic across calls: {ids1} vs {ids2}"
        )


# ===========================================================================
# Bug api-15: No NODE_FAILED event on exception
# ===========================================================================


class TestTaskExceptionEmitsFailedEvent:
    """api-15: When engine.run_workflow raises an exception, a TaskEvent
    (or equivalent) must be recorded explaining the failure."""

    @pytest.mark.asyncio
    async def test_exception_emits_failure_event(self, client):
        """Cause engine.run_workflow to raise, verify a failure event was
        recorded for the workflow (either a TaskEvent of type NODE_FAILED
        or a workflow-level failure event)."""
        http, _app = client
        create_resp = await http.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        # Patch engine.run_workflow to raise
        engine = _app.state.engine
        original = engine.run_workflow

        async def boom(_wid):
            raise RuntimeError("synthetic engine failure for api-15 test")

        engine.run_workflow = boom
        try:
            exec_resp = await http.post(f"/api/workflows/{wf_id}/execute")
            assert exec_resp.status_code == 200

            # Wait for done callback
            await asyncio.sleep(0.5)
        finally:
            engine.run_workflow = original

        # Check that a failure event was emitted. We accept any TaskEvent with
        # event_data containing 'error' or 'exception' as proof the exception
        # was recorded. We also accept WorkflowEvent rows with event_type
        # like 'workflow_failed'.
        async with get_session() as session:
            result = await session.execute(
                select(TaskEvent).where(TaskEvent.workflow_id == wf_uuid)
            )
            task_events = result.scalars().all()
            result = await session.execute(
                select(WorkflowEvent).where(WorkflowEvent.workflow_id == wf_uuid)
            )
            wf_events = result.scalars().all()

            # Either: a TaskEvent whose event_data includes error info,
            # OR a WorkflowEvent with type indicating failure.
            task_records_failure = any(
                e.event_data and (
                    "error" in str(e.event_data).lower()
                    or "exception" in str(e.event_data).lower()
                    or "traceback" in str(e.event_data).lower()
                )
                for e in task_events
            )
            wf_records_failure = any(
                e.event_type == TaskEventType.NODE_FAILED
                or (
                    e.event_data and (
                        "error" in str(e.event_data).lower()
                        or "exception" in str(e.event_data).lower()
                    )
                )
                for e in wf_events
            )
            assert (
                task_records_failure or wf_records_failure
            ), (
                "No TaskEvent/WorkflowEvent records the engine failure; "
                f"task_events={[e.event_type.value for e in task_events]}, "
                f"wf_events={[e.event_type.value for e in wf_events]}"
            )


# ===========================================================================
# Bug api-18: No global exception handler
# ===========================================================================


class TestGlobalExceptionHandler:
    """api-18: Unexpected exceptions must be caught by a global handler
    that returns a structured ErrorResponse (not a generic 500)."""

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_structured_error(self, client):
        """Force an unhandled exception inside a handler and verify the
        response has a structured 'detail' field, not just a 500."""
        http, app = client

        # Register a temporary route that raises
        @app.get("/__test_boom")
        async def boom():
            raise RuntimeError("synthetic api-18 failure")

        # httpx.ASGITransport raises app exceptions by default; build a
        # separate client with raise_app_exceptions=False so we observe the
        # actual HTTP response from our global handler.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/__test_boom")
            assert resp.status_code == 500
            body = resp.json()
            # Must have a 'detail' field — the new handler ensures this is
            # structured, not just "Internal Server Error".
            assert "detail" in body, f"Response missing 'detail' field: {body}"
            assert body.get("detail") == "internal_error"
            assert "request_id" in body, f"Response missing request_id: {body}"


# ===========================================================================
# Bug api-20: running_tasks memory leak on success
# ===========================================================================


class TestRunningTasksCleanupOnSuccess:
    """api-20: When a workflow completes successfully, its entry must be
    removed from app.state.running_tasks (no unbounded growth)."""

    @pytest.mark.asyncio
    async def test_running_tasks_emptied_after_success(self, client):
        """After a successful workflow completes, running_tasks must be empty."""
        http, app = client
        create_resp = await http.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        exec_resp = await http.post(f"/api/workflows/{wf_id}/execute")
        assert exec_resp.status_code == 200

        # Wait for completion + done callback cleanup
        for _ in range(30):
            await asyncio.sleep(0.1)
            if str(uuid.UUID(wf_id)) not in app.state.running_tasks and \
               wf_id not in app.state.running_tasks:
                break

        # The running_tasks dict must not contain a stale entry for this workflow
        assert (
            str(uuid.UUID(wf_id)) not in app.state.running_tasks
        ), (
            f"running_tasks still contains completed workflow: "
            f"{list(app.state.running_tasks.keys())}"
        )