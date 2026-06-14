"""Tests for the human-in-the-loop resume endpoint (TODO-2).

Follows strict TDD. Covers:
- POST /api/workflows/{id}/resume on a non-existent UUID -> 404.
- POST /api/workflows/{id}/resume on a non-paused workflow -> 409.
- POST /api/workflows/{id}/resume on a paused workflow -> 202-style response
  with status="running" and a resume_id; the workflow transitions to a
  terminal state in the background.
- The recorded HUMAN_INPUT_RECEIVED + WORKFLOW_RESUMED events.
"""

from __future__ import annotations

import asyncio
import uuid
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
    TaskEventType,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


# ---------------------------------------------------------------------------
# Fakes (mirror tests/api/test_runs_endpoint.py)
# ---------------------------------------------------------------------------


def _fragment(goal_achieved: bool = True) -> DAGFragment:
    return DAGFragment(
        nodes=[
            DAGNode(name="step", task_type="tool_execution", command="echo", arguments={})
        ],
        reasoning="r",
        goal_achieved=goal_achieved,
    )


class _FakePlanner:
    async def plan(self, goal, observation=None, tool_schemas=None, history=None, timeout_ms=60000):
        return _fragment(goal_achieved=True)


class _FakeEvaluator:
    async def evaluate(self, fragment, goal):
        return EvaluatorDecision.DONE


def _fake_planner_factory():
    def _factory(settings, toolkits, llm_client):
        return _FakePlanner()

    return _factory


def _fake_evaluator_factory():
    def _factory(settings, llm_client):
        return _FakeEvaluator()

    return _factory


class _MockWorkspace(BaseWorkspace):
    def __init__(self) -> None:
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        self._active = True

    async def execute(self, command, arguments=None, env=None) -> AsyncIterator[WorkspaceEvent]:
        await asyncio.sleep(0)
        yield WorkspaceEvent(event_type="stdout_line", data="mock")
        yield WorkspaceEvent(event_type="execution_completed", data={"exit_code": 0})

    async def teardown(self) -> None:
        self._active = False

    async def get_workspace_path(self) -> str:
        return "/tmp/mock"


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
    return EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL, MAX_PARALLEL_SUBPROCESSES=2)


@pytest.fixture
async def client(settings):
    app = create_app(
        settings=settings,
        workspace_factory=lambda: _MockWorkspace(),
        planner_factory=_fake_planner_factory(),
        evaluator_factory=_fake_evaluator_factory(),
    )
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            # Expose app on the client for state inspection in tests.
            c.app = app  # type: ignore[attr-defined]
            yield c
    finally:
        # Cancel any in-flight resume/run tasks.
        for rid, task in list(getattr(app.state, "running_run_tasks", {}).items()):
            if not task.done():
                task.cancel()
        await lifespan_cm.__aexit__(None, None, None)


async def _seed_paused_workflow(name: str = "paused-wf") -> str:
    """Insert a PAUSED workflow with persisted _opa_state for resume."""
    wf_id = uuid.uuid4()
    async with get_session() as session:
        session.add(
            Workflow(
                id=wf_id,
                name=name,
                status=WorkflowStatus.PAUSED,
                dag_definition={
                    "goal": name,
                    "_opa_state": {
                        "cycle_count": 1,
                        "llm_tokens_accumulated": 100,
                        "history": [],
                    },
                },
            )
        )
    return str(wf_id)


async def _seed_workflow(status: WorkflowStatus, name: str) -> str:
    wf_id = uuid.uuid4()
    async with get_session() as session:
        session.add(
            Workflow(
                id=wf_id,
                name=name,
                status=status,
                dag_definition={"goal": name},
            )
        )
    return str(wf_id)


async def _drain_background(app, timeout: float = 2.0) -> None:
    """Wait for any in-flight background tasks to finish."""
    tasks = [t for t in getattr(app.state, "running_run_tasks", {}).values() if not t.done()]
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_resume_unknown_uuid_returns_404(client):
    bogus = str(uuid.uuid4())
    resp = await client.post(
        f"/api/workflows/{bogus}/resume", json={"human_input": "go ahead"}
    )
    assert resp.status_code == 404


async def test_resume_invalid_uuid_returns_404(client):
    resp = await client.post(
        "/api/workflows/not-a-uuid/resume", json={"human_input": "go ahead"}
    )
    assert resp.status_code == 404


async def test_resume_non_paused_workflow_returns_409(client):
    wf_id = await _seed_workflow(WorkflowStatus.COMPLETED, "completed-wf")
    resp = await client.post(
        f"/api/workflows/{wf_id}/resume", json={"human_input": "go ahead"}
    )
    assert resp.status_code == 409
    assert "only paused workflows can be resumed" in resp.json()["detail"]


async def test_resume_paused_workflow_returns_running_and_resumes(client):
    wf_id = await _seed_paused_workflow("paused-wf")

    resp = await client.post(
        f"/api/workflows/{wf_id}/resume", json={"human_input": "proceed with the plan"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["workflow_id"] == wf_id
    assert body["resume_id"]

    # Let the background resume finish.
    await _drain_background(client.app)  # type: ignore[attr-defined]

    # The workflow should have transitioned out of PAUSED to a terminal state.
    async with get_session() as session:
        result = await session.execute(select(Workflow).where(Workflow.id == uuid.UUID(wf_id)))
        wf = result.scalar_one()
        assert wf.status != WorkflowStatus.PAUSED

    # HUMAN_INPUT_RECEIVED + WORKFLOW_RESUMED events must have been emitted.
    async with get_session() as session:
        ev_result = await session.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_id == uuid.UUID(wf_id))
            .order_by(WorkflowEvent.sequence_number.asc())
        )
        types = [e.event_type for e in ev_result.scalars().all()]
    assert TaskEventType.HUMAN_INPUT_RECEIVED in types
    assert TaskEventType.WORKFLOW_RESUMED in types
