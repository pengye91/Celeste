"""Tests for lifespan shutdown cancelling in-flight /api/runs tasks (Fix B).

The adversarial review found that ``create_app``'s lifespan did NOT cancel
in-flight background ``/api/runs`` tasks on shutdown, leaving them leaked and
the run stuck at status "running" forever.

TDD: this test is written BEFORE the fix. On shutdown the lifespan must:
1. cancel every not-done task in ``app.state.running_run_tasks``,
2. await them with a timeout (shielding CancelledError),
3. flip any run still at status "running" to "failed" (error="shutdown").
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from celeste.api.app import create_app
from celeste.config.settings import EngineSettings
from celeste.core.evaluator import EvaluatorDecision
from celeste.core.planner import DAGFragment, DAGNode

SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


def _tool_node(name: str) -> DAGNode:
    return DAGNode(
        name=name,
        task_type="tool_execution",
        command="read_file",
        arguments={"path": "README.md"},
        dependencies=[],
    )


class _NeverDonePlanner:
    """Planner whose plan() blocks forever (simulates a never-completing run)."""

    async def plan(self, goal, observation=None, tool_schemas=None, history=None, timeout_ms=60000):
        # Block forever so the OPA loop never reaches a terminal status while
        # the test triggers shutdown.
        await asyncio.Event().wait()
        # Unreachable, but keeps the return type sane for the type checker.
        return DAGFragment(nodes=[_tool_node("n")], reasoning="blocked", goal_achieved=False)


def _never_done_planner_factory(settings, toolkits, llm_client):
    return _NeverDonePlanner()


class _NeverDoneEvaluator:
    async def evaluate(self, fragment, goal):
        # Never DONE — keep looping forever.
        await asyncio.Event().wait()
        return EvaluatorDecision.CONTINUE


def _never_done_evaluator_factory(settings, llm_client):
    return _NeverDoneEvaluator()


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
    return EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_PARALLEL_SUBPROCESSES=2,
        WORKSPACE_ENGINE="local_tmp",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLifespanCancelsRuns:
    """Fix B: lifespan shutdown cancels in-flight /api/runs tasks."""

    @pytest.mark.asyncio
    async def test_shutdown_cancels_inflight_run_and_marks_failed(self, settings):
        """A never-completing run must be cancelled on shutdown -> status 'failed'.

        Uses the ASGI lifespan context manager directly (the same path a real
        uvicorn server would take) so we exercise the lifespan teardown.
        """
        app = create_app(
            settings=settings,
            toolkits=[],
            planner_factory=_never_done_planner_factory,
            evaluator_factory=_never_done_evaluator_factory,
        )

        # Enter lifespan (startup) — this is what the lifespan teardown fixes.
        lifespan_cm = app.router.lifespan_context(app)
        await lifespan_cm.__aenter__()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/runs", json={"goal": "never-complete-goal"})
                assert resp.status_code == 202, resp.text
                run_id = resp.json()["run_id"]

                # Give the background task a moment to actually start blocking.
                await asyncio.sleep(0.3)

                # The run is in-flight (running) and the background task is alive.
                task = app.state.running_run_tasks.get(run_id)
                assert task is not None, "background task not registered"
                assert not task.done(), "background task should still be running"

                status_resp = await client.get(f"/api/runs/{run_id}")
                assert status_resp.json()["status"] == "running"
        finally:
            # Trigger lifespan shutdown (teardown). This is the code under test.
            await lifespan_cm.__aexit__(None, None, None)

        # After shutdown: the run must be marked failed (not stuck "running").
        record = app.state.runs.get(run_id)
        assert record is not None, "run record vanished after shutdown"
        assert record["status"] == "failed", (
            f"expected 'failed' after shutdown, got {record['status']!r}"
        )
        assert record.get("error") == "shutdown", (
            f"expected error='shutdown', got {record.get('error')!r}"
        )

        # And the background task must have been cancelled/done.
        task = app.state.running_run_tasks.get(run_id)
        # The lifespan should have cleared the dict (or left a done task).
        if task is not None:
            assert task.done(), "background task was not cancelled on shutdown"
