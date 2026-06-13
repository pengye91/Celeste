"""Tests for the embedded OPA-loop ``/api/runs`` endpoint.

Follows strict TDD (written before/while implementing the endpoint) and
NEVER calls a real LLM: a fake planner returns a trivial 1-2 node DAG and a
fake evaluator returns DONE after the first cycle.

Covers:
- POST /api/runs starts a background OPA run and returns a run_id (202).
- Polling GET /api/runs/{run_id} reaches a terminal status.
- A Workflow row is persisted + TaskEvent rows are emitted.
- RunStatus.workflow_id is set after the run.
- Missing goal -> 422.
- Unknown run_id -> 404.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from celeste.api.app import create_app
from celeste.config.settings import EngineSettings
from celeste.core.evaluator import EvaluatorDecision
from celeste.core.planner import DAGFragment, DAGNode
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.db import get_session
from celeste.database.models import (
    TaskEvent,
    Workflow,
    WorkflowStatus,
)


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"

_TERMINAL = {"completed", "paused", "failed", "escalated", "cancelled"}


# ---------------------------------------------------------------------------
# Fakes: planner, evaluator, workspace (NO LLM)
# ---------------------------------------------------------------------------


def _tool_node(name: str, command: str, args: dict[str, Any] | None = None) -> DAGNode:
    return DAGNode(
        name=name,
        task_type="tool_execution",
        command=command,
        arguments=args or {},
        dependencies=[],
    )


class _FakePlanner:
    """Planner that returns a single-node fragment invoking ``read_file``.

    The node reads a real file so the in-process agent's ``read_file`` tool
    executes successfully and the OPA loop emits NODE_STARTED/NODE_COMPLETED
    TaskEvent rows. ``goal_achieved=True`` terminates the loop in one cycle.
    """

    def __init__(self, fragment: DAGFragment | None = None) -> None:
        self._fragment = fragment or DAGFragment(
            nodes=[
                _tool_node(
                    "read_readme",
                    command="read_file",
                    args={"path": "README.md"},
                )
            ],
            reasoning="Read the project README to satisfy the goal.",
            goal_achieved=True,
        )

    async def plan(self, goal, observation=None, tool_schemas=None, history=None, timeout_ms=60000):
        return self._fragment


class _FakeEvaluator:
    """Evaluator that returns DONE immediately (no LLM)."""

    def __init__(self, decisions: list[EvaluatorDecision] | None = None) -> None:
        self._decisions = decisions or [EvaluatorDecision.DONE]
        self._i = 0

    async def evaluate(self, fragment, goal):
        d = self._decisions[min(self._i, len(self._decisions) - 1)]
        self._i += 1
        return d


def _fake_planner_factory(fragment: DAGFragment | None = None):
    """Build a planner_factory closure that ignores its args and returns a fake."""

    def _factory(settings, toolkits, llm_client):
        return _FakePlanner(fragment=fragment)

    return _factory


def _fake_evaluator_factory(decisions: list[EvaluatorDecision] | None = None):
    """Build an evaluator_factory closure that returns a fake evaluator."""

    def _factory(settings, llm_client):
        return _FakeEvaluator(decisions=decisions)

    return _factory


class _MockWorkspace(BaseWorkspace):
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
        await asyncio.sleep(0)
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
    return EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_PARALLEL_SUBPROCESSES=2,
        WORKSPACE_ENGINE="local_tmp",
    )


@pytest.fixture
async def client(settings):
    """An httpx.AsyncClient wired to an app with FAKE planner/evaluator.

    The fake planner returns a one-node fragment (read_file on README.md)
    and the fake evaluator returns DONE on the first cycle, so the OPA loop
    runs to completion WITHOUT any LLM call.
    """
    app = create_app(
        settings=settings,
        workspace_factory=lambda: _MockWorkspace(),
        toolkits=[],  # read_file is a built-in agent tool; no toolkit needed
        planner_factory=_fake_planner_factory(),
        evaluator_factory=_fake_evaluator_factory(),
    )

    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        # Cancel any lingering background run tasks before teardown.
        if hasattr(app.state, "running_run_tasks"):
            for rid, task in list(app.state.running_run_tasks.items()):
                if not task.done():
                    task.cancel()
            for rid, task in list(app.state.running_run_tasks.items()):
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            app.state.running_run_tasks.clear()
        await lifespan_cm.__aexit__(None, None, None)


async def _poll_until_terminal(client: httpx.AsyncClient, run_id: str, timeout: float = 30.0) -> dict:
    """Poll GET /api/runs/{id} until terminal or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    last: dict = {}
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/runs/{run_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("status") in _TERMINAL:
            return last
        await asyncio.sleep(0.1)
    return last


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStartRun:
    """POST /api/runs starts a background OPA run."""

    @pytest.mark.asyncio
    async def test_post_returns_202_with_run_id(self, client):
        resp = await client.post("/api/runs", json={"goal": "embedded-test-goal"})
        assert resp.status_code == 202
        data = resp.json()
        assert "run_id" in data
        assert isinstance(data["run_id"], str)
        assert data["run_id"]
        assert data["status"] == "started"

    @pytest.mark.asyncio
    async def test_run_reaches_completed_and_persists_workflow(self, client):
        resp = await client.post("/api/runs", json={"goal": "embedded-complete-goal"})
        run_id = resp.json()["run_id"]

        status = await _poll_until_terminal(client, run_id)
        assert status["status"] == "completed", f"unexpected status: {status}"
        assert status["workflow_id"] is not None

        # A Workflow row exists in the DB.
        import uuid as _uuid

        wf_id = _uuid.UUID(status["workflow_id"])
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_id)
            )
            wf = result.scalar_one_or_none()
            assert wf is not None, "Workflow row not persisted"
            assert wf.status == WorkflowStatus.COMPLETED

            # TaskEvent rows were emitted by the OPA loop.
            events = (
                await session.execute(
                    select(TaskEvent).where(TaskEvent.workflow_id == wf_id)
                )
            ).scalars().all()
            assert len(events) >= 1, "No TaskEvent rows emitted"

    @pytest.mark.asyncio
    async def test_missing_goal_returns_422(self, client):
        resp = await client.post("/api/runs", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_goal_returns_422(self, client):
        resp = await client.post("/api/runs", json={"goal": ""})
        assert resp.status_code == 422


class TestGetRun:
    """GET /api/runs/{run_id} returns status / 404."""

    @pytest.mark.asyncio
    async def test_unknown_run_id_returns_404(self, client):
        resp = await client.get("/api/runs/does-not-exist")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_known_run_id_returns_status(self, client):
        post = await client.post("/api/runs", json={"goal": "embedded-status-goal"})
        run_id = post.json()["run_id"]

        resp = await client.get(f"/api/runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert "status" in data
        # workflow_id may be None while in-flight; that's allowed by the schema.

    @pytest.mark.asyncio
    async def test_run_status_shows_workflow_id_after_terminal(self, client):
        post = await client.post("/api/runs", json={"goal": "embedded-wfid-goal"})
        run_id = post.json()["run_id"]
        await _poll_until_terminal(client, run_id)

        resp = await client.get(f"/api/runs/{run_id}")
        data = resp.json()
        assert data["workflow_id"] is not None
