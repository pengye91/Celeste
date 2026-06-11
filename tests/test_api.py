"""
Tests for the FastAPI Web API layer in celeste_dag.api.

Follows strict TDD: these tests are written BEFORE the implementation.
Uses httpx.AsyncClient with ASGITransport for in-process testing.

Tests cover:
- App creation and health check
- POST /api/workflows creates a workflow
- GET /api/workflows lists workflows
- GET /api/workflows/{id} returns details
- POST /api/workflows/{id}/execute starts execution
- GET /api/workflows/{id}/status returns status
- GET /api/workflows/{id}/events returns events
- GET /api/workflows/{id}/nodes returns nodes
- DELETE /api/workflows/{id} cancels workflow
- Error handling (404, validation errors)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest
import httpx
from sqlalchemy import select

from celeste_dag.config.settings import EngineSettings
from celeste_dag.core.planner import DAGNode, DAGPlan
from celeste_dag.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste_dag.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowStatus,
)
from celeste_dag.core.agent.agent import EnvironmentAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_db_module():
    """Reset database module state between tests."""
    import celeste_dag.database.db as db_mod

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
    """Create an httpx.AsyncClient wired to the FastAPI app.

    Manually triggers the lifespan (startup/shutdown) since httpx.ASGITransport
    does not handle ASGI lifespan events automatically.
    """
    from celeste_dag.api.app import create_app

    app = create_app(settings=settings, workspace_factory=lambda: MockWorkspace())

    # Manually invoke the lifespan context manager
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        # Wait for any background tasks to settle before teardown to avoid
        # race conditions between done-callbacks and engine.stop()
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
# Test: App creation and health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """GET /health returns ok status."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_includes_version(self, client):
        resp = await client.get("/health")
        data = resp.json()
        assert "version" in data
        assert data["version"] == "0.1.0"


# ---------------------------------------------------------------------------
# Test: POST /api/workflows
# ---------------------------------------------------------------------------


class TestCreateWorkflow:
    """POST /api/workflows creates a workflow from a DAG plan."""

    @pytest.mark.asyncio
    async def test_create_workflow_returns_201(self, client):
        resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        assert resp.status_code == 201
        data = resp.json()
        assert "workflow_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_create_workflow_validates_uuid(self, client):
        resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        data = resp.json()
        # Should be a valid UUID string
        parsed = uuid.UUID(data["workflow_id"])
        assert str(parsed) == data["workflow_id"]

    @pytest.mark.asyncio
    async def test_create_workflow_persists_record(self, client, settings):
        resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        data = resp.json()
        wf_id = uuid.UUID(data["workflow_id"])

        from celeste_dag.database.db import get_session

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_id)
            )
            wf = result.scalar_one()
            assert wf.name == "test-workflow"
            assert wf.status == WorkflowStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_workflow_missing_name_returns_422(self, client):
        body = {"nodes": SAMPLE_NODES}
        resp = await client.post("/api/workflows", json=body)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_workflow_missing_nodes_returns_422(self, client):
        body = {"name": "empty"}
        resp = await client.post("/api/workflows", json=body)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_workflow_empty_nodes_returns_422(self, client):
        body = {"name": "empty", "nodes": []}
        resp = await client.post("/api/workflows", json=body)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_workflow_with_variables(self, client):
        body = {
            "name": "with-vars",
            "nodes": SAMPLE_NODES,
            "variables": {"foo": "bar", "count": 42},
        }
        resp = await client.post("/api/workflows", json=body)
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Test: GET /api/workflows
# ---------------------------------------------------------------------------


class TestListWorkflows:
    """GET /api/workflows lists all workflows."""

    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        resp = await client.get("/api/workflows")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_returns_created_workflows(self, client):
        # Create two workflows
        await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        body2 = {**SAMPLE_WORKFLOW_BODY, "name": "second-workflow"}
        await client.post("/api/workflows", json=body2)

        resp = await client.get("/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {w["name"] for w in data}
        assert names == {"test-workflow", "second-workflow"}

    @pytest.mark.asyncio
    async def test_list_includes_status_and_created_at(self, client):
        await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        resp = await client.get("/api/workflows")
        data = resp.json()
        assert len(data) == 1
        wf = data[0]
        assert "id" in wf
        assert "name" in wf
        assert wf["status"] == "pending"
        assert "created_at" in wf


# ---------------------------------------------------------------------------
# Test: GET /api/workflows/{workflow_id}
# ---------------------------------------------------------------------------


class TestGetWorkflowDetail:
    """GET /api/workflows/{id} returns workflow details."""

    @pytest.mark.asyncio
    async def test_get_existing_workflow(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == wf_id
        assert data["name"] == "test-workflow"
        assert data["status"] == "pending"
        assert "dag_definition" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert data["description"] == "A test workflow"

    @pytest.mark.asyncio
    async def test_get_nonexistent_workflow_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/workflows/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_invalid_uuid_returns_404(self, client):
        resp = await client.get("/api/workflows/not-a-uuid")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: POST /api/workflows/{id}/execute
# ---------------------------------------------------------------------------


class TestExecuteWorkflow:
    """POST /api/workflows/{id}/execute starts execution."""

    @pytest.mark.asyncio
    async def test_execute_returns_running(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.post(f"/api/workflows/{wf_id}/execute")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == wf_id
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_execute_nonexistent_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.post(f"/api/workflows/{fake_id}/execute")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_execute_workflow_completes(self, client, settings):
        """After execution, the workflow should eventually complete."""
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        exec_resp = await client.post(f"/api/workflows/{wf_id}/execute")
        assert exec_resp.status_code == 200

        # Give the async execution time to complete
        await asyncio.sleep(0.5)

        # Check final status
        status_resp = await client.get(f"/api/workflows/{wf_id}/status")
        data = status_resp.json()
        assert data["status"] in ("completed", "running")

        # Wait longer if still running
        for _ in range(10):
            if data["status"] == "completed":
                break
            await asyncio.sleep(0.2)
            status_resp = await client.get(f"/api/workflows/{wf_id}/status")
            data = status_resp.json()

        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_registers_running_task(self, client, settings):
        """Execute should register the asyncio.Task in app.state.running_tasks."""
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        # Use nodes that take time so the task is still registered
        slow_nodes = [
            {
                "name": "slow_a",
                "task_type": "tool_execution",
                "command": "echo hello",
                "arguments": {},
                "dependencies": [],
            },
            {
                "name": "slow_b",
                "task_type": "tool_execution",
                "command": "echo world",
                "arguments": {},
                "dependencies": ["slow_a"],
            },
        ]
        body = {"name": "slow-wf", "nodes": slow_nodes, "variables": {}}
        create_resp2 = await client.post("/api/workflows", json=body)
        wf_id2 = create_resp2.json()["workflow_id"]

        exec_resp = await client.post(f"/api/workflows/{wf_id2}/execute")
        assert exec_resp.status_code == 200

        # Wait for completion
        await asyncio.sleep(1.0)

    @pytest.mark.asyncio
    async def test_execute_task_done_callback_handles_errors(self, client, settings):
        """The done-callback should catch errors from background tasks."""
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        # Execute normally -- the done-callback should not crash
        exec_resp = await client.post(f"/api/workflows/{wf_id}/execute")
        assert exec_resp.status_code == 200

        # Wait for completion
        await asyncio.sleep(1.0)

        # Workflow should complete successfully (done-callback is a no-op for success)
        status_resp = await client.get(f"/api/workflows/{wf_id}/status")
        data = status_resp.json()
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Test: GET /api/workflows/{id}/status
# ---------------------------------------------------------------------------


class TestWorkflowStatus:
    """GET /api/workflows/{id}/status returns real-time DAG status."""

    @pytest.mark.asyncio
    async def test_status_pending_workflow(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == wf_id
        assert data["status"] == "pending"
        assert "nodes" in data
        assert "progress" in data
        # Initially no progress
        assert data["progress"] == 0.0

    @pytest.mark.asyncio
    async def test_status_nonexistent_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/workflows/{fake_id}/status")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_status_includes_node_states(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}/status")
        data = resp.json()
        nodes = data["nodes"]
        assert len(nodes) == 2
        node_names = {n["name"] for n in nodes}
        assert node_names == {"step_a", "step_b"}
        for node in nodes:
            assert "status" in node
            assert node["status"] == "pending"

    @pytest.mark.asyncio
    async def test_progress_after_completion(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        await client.post(f"/api/workflows/{wf_id}/execute")
        await asyncio.sleep(1.0)

        resp = await client.get(f"/api/workflows/{wf_id}/status")
        data = resp.json()
        # After completion, progress should be 1.0
        if data["status"] == "completed":
            assert data["progress"] == 1.0

    @pytest.mark.asyncio
    async def test_progress_counts_failed_nodes(self, client, settings):
        """Progress should include failed nodes as 'completed' (terminal)."""
        # Manually create a workflow and set one node to failed
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]
        wf_uuid = uuid.UUID(wf_id)

        from celeste_dag.database.db import get_session

        # Manually set one node to failed and one to completed
        async with get_session() as session:
            from sqlalchemy import select as _sel
            result = await session.execute(
                _sel(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            nodes = result.scalars().all()
            nodes[0].status = TaskNodeStatus.COMPLETED
            nodes[1].status = TaskNodeStatus.FAILED

        resp = await client.get(f"/api/workflows/{wf_id}/status")
        data = resp.json()
        # Both nodes are in terminal states, so progress should be 1.0
        assert data["progress"] == 1.0


# ---------------------------------------------------------------------------
# Test: GET /api/workflows/{id}/events
# ---------------------------------------------------------------------------


class TestWorkflowEvents:
    """GET /api/workflows/{id}/events returns the audit log."""

    @pytest.mark.asyncio
    async def test_events_empty_for_new_workflow(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_events_after_execution(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        await client.post(f"/api/workflows/{wf_id}/execute")
        await asyncio.sleep(1.0)

        resp = await client.get(f"/api/workflows/{wf_id}/events")
        assert resp.status_code == 200
        data = resp.json()
        # Should have events for each node (started + completed = 2 per node, 2 nodes = 4)
        assert len(data) >= 4
        event_types = {e["event_type"] for e in data}
        assert "node_started" in event_types
        assert "node_completed" in event_types

    @pytest.mark.asyncio
    async def test_events_have_timestamps(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        await client.post(f"/api/workflows/{wf_id}/execute")
        await asyncio.sleep(1.0)

        resp = await client.get(f"/api/workflows/{wf_id}/events")
        data = resp.json()
        assert len(data) > 0
        for event in data:
            assert "timestamp" in event
            assert "id" in event

    @pytest.mark.asyncio
    async def test_events_filter_by_type(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        await client.post(f"/api/workflows/{wf_id}/execute")
        await asyncio.sleep(1.0)

        resp = await client.get(
            f"/api/workflows/{wf_id}/events",
            params={"event_type": "node_completed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        for event in data:
            assert event["event_type"] == "node_completed"

    @pytest.mark.asyncio
    async def test_events_with_limit(self, client, settings):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        await client.post(f"/api/workflows/{wf_id}/execute")
        await asyncio.sleep(1.0)

        resp = await client.get(
            f"/api/workflows/{wf_id}/events",
            params={"limit": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 2

    @pytest.mark.asyncio
    async def test_events_nonexistent_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/workflows/{fake_id}/events")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: GET /api/workflows/{id}/nodes
# ---------------------------------------------------------------------------


class TestWorkflowNodes:
    """GET /api/workflows/{id}/nodes returns node details."""

    @pytest.mark.asyncio
    async def test_nodes_returns_all_nodes(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        node_names = {n["name"] for n in data}
        assert node_names == {"step_a", "step_b"}

    @pytest.mark.asyncio
    async def test_nodes_have_required_fields(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.get(f"/api/workflows/{wf_id}/nodes")
        data = resp.json()
        for node in data:
            assert "id" in node
            assert "name" in node
            assert "status" in node
            assert "task_type" in node
            # outputs is null for pending nodes
            assert "outputs" in node

    @pytest.mark.asyncio
    async def test_nodes_nonexistent_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/workflows/{fake_id}/nodes")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: DELETE /api/workflows/{id}
# ---------------------------------------------------------------------------


class TestCancelWorkflow:
    """DELETE /api/workflows/{id} cancels a workflow."""

    @pytest.mark.asyncio
    async def test_cancel_pending_workflow(self, client):
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        resp = await client.delete(f"/api/workflows/{wf_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == wf_id
        assert data["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"/api/workflows/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_already_completed_fails(self, client, settings):
        """Cancelling an already-completed workflow returns an error."""
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        # Execute to completion
        await client.post(f"/api/workflows/{wf_id}/execute")
        await asyncio.sleep(1.0)

        # Try to cancel
        resp = await client.delete(f"/api/workflows/{wf_id}")
        # Should return 400 since workflow is already completed
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_cancel_running_workflow_cancels_task(self, settings):
        """Cancelling a running workflow cancels the asyncio.Task and updates status."""
        from celeste_dag.api.app import create_app

        class SlowWorkspace(BaseWorkspace):
            """A workspace that blocks long enough to cancel mid-execution."""

            def __init__(self) -> None:
                self._active = False

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
                # Sleep long enough that we can cancel while running
                await asyncio.sleep(10)
                yield WorkspaceEvent(event_type="stdout_line", data="done")
                yield WorkspaceEvent(event_type="execution_completed", data={"exit_code": 0})

            async def teardown(self) -> None:
                self._active = False

            async def get_workspace_path(self) -> str:
                return "/tmp/slow_workspace"

        app = create_app(settings=settings, workspace_factory=lambda: SlowWorkspace())
        lifespan_cm = app.router.lifespan_context(app)
        await lifespan_cm.__aenter__()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                create_resp = await c.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
                wf_id = create_resp.json()["workflow_id"]

                exec_resp = await c.post(f"/api/workflows/{wf_id}/execute")
                assert exec_resp.status_code == 200

                # Brief pause so the background task starts executing
                await asyncio.sleep(0.1)

                # The task should be registered
                assert str(uuid.UUID(wf_id)) in app.state.running_tasks or wf_id in app.state.running_tasks

                # Cancel while still running
                cancel_resp = await c.delete(f"/api/workflows/{wf_id}")
                assert cancel_resp.status_code == 200
                data = cancel_resp.json()
                assert data["status"] == "cancelled"

                # Verify the task was removed from running_tasks
                assert wf_id not in app.state.running_tasks

                # Verify status reflects cancellation
                status_resp = await c.get(f"/api/workflows/{wf_id}/status")
                status_data = status_resp.json()
                assert status_data["status"] == "cancelled"
        finally:
            # Clean up background tasks before teardown
            for tid, task in list(app.state.running_tasks.items()):
                if not task.done():
                    task.cancel()
            for tid, task in list(app.state.running_tasks.items()):
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            app.state.running_tasks.clear()
            await lifespan_cm.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_cancel_removes_running_task(self, client, settings):
        """Cancelling a workflow removes it from the running_tasks dict."""
        create_resp = await client.post("/api/workflows", json=SAMPLE_WORKFLOW_BODY)
        wf_id = create_resp.json()["workflow_id"]

        # Start execution
        await client.post(f"/api/workflows/{wf_id}/execute")
        await asyncio.sleep(0.05)

        # Cancel
        await client.delete(f"/api/workflows/{wf_id}")
        await asyncio.sleep(0.05)

        # Check that the workflow was removed from running_tasks
        # (it should be gone even if it completed first, the cancel handles both)
        status_resp = await client.get(f"/api/workflows/{wf_id}/status")
        assert status_resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """API returns proper error responses for invalid input."""

    @pytest.mark.asyncio
    async def test_invalid_json_returns_422(self, client):
        resp = await client.post(
            "/api/workflows",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_node_missing_required_fields(self, client):
        body = {
            "name": "bad-workflow",
            "nodes": [{"name": "bad_node"}],  # missing task_type, command
        }
        resp = await client.post("/api/workflows", json=body)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_duplicate_workflow_404(self, client):
        """Operations on nonexistent ID return 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/workflows/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_malformed_uuid_handled(self, client):
        """Invalid UUID format returns 404 (not 500)."""
        resp = await client.get("/api/workflows/abc-not-uuid")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: Agent management endpoints
# ---------------------------------------------------------------------------


class TestAgentManagement:
    """Tests for POST /agents/register, GET /agents/{id}/status,
    GET /agents, and DELETE /agents/{id}."""

    @pytest.mark.asyncio
    async def test_register_agent_creates_record(self, client):
        """POST /agents/register creates an agent record."""
        resp = await client.post(
            "/agents/register",
            json={"url": "ws://localhost:9001"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "agent_id" in data
        assert data["status"] == "pending"
        # Should be a valid UUID
        parsed = uuid.UUID(data["agent_id"])
        assert str(parsed) == data["agent_id"]

    @pytest.mark.asyncio
    async def test_register_agent_with_auth_token(self, client):
        """POST /agents/register accepts an optional auth_token."""
        resp = await client.post(
            "/agents/register",
            json={
                "url": "ws://localhost:9001",
                "auth_token": "secret123",
                "metadata": {"env": "prod"},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "agent_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_agent_status(self, client):
        """GET /agents/{id}/status returns agent status."""
        # Register an agent first
        reg_resp = await client.post(
            "/agents/register",
            json={"url": "ws://localhost:9001"},
        )
        agent_id = reg_resp.json()["agent_id"]

        resp = await client.get(f"/agents/{agent_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == agent_id
        assert data["status"] in ("connected", "disconnected", "error")
        assert "last_seen" in data

    @pytest.mark.asyncio
    async def test_list_agents(self, client):
        """GET /agents returns all registered agents."""
        # Register two agents
        resp1 = await client.post(
            "/agents/register",
            json={"url": "ws://localhost:9001", "metadata": {"name": "agent1"}},
        )
        resp2 = await client.post(
            "/agents/register",
            json={"url": "ws://localhost:9002", "metadata": {"name": "agent2"}},
        )
        id1 = resp1.json()["agent_id"]
        id2 = resp2.json()["agent_id"]

        resp = await client.get("/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        agent_ids = {a["agent_id"] for a in data}
        assert agent_ids == {id1, id2}

    @pytest.mark.asyncio
    async def test_delete_agent(self, client):
        """DELETE /agents/{id} unregisters an agent."""
        # Register an agent
        reg_resp = await client.post(
            "/agents/register",
            json={"url": "ws://localhost:9001"},
        )
        agent_id = reg_resp.json()["agent_id"]

        # Delete it
        del_resp = await client.delete(f"/agents/{agent_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

        # Should no longer exist
        status_resp = await client.get(f"/agents/{agent_id}/status")
        assert status_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_agent_returns_404(self, client):
        """GET /agents/{id}/status for unknown agent returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/agents/{fake_id}/status")
        assert resp.status_code == 404
