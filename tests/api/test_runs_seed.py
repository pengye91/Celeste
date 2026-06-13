"""Tests for the embedded OPA-loop seed-loading via dependency injection.

These tests pin down Fix A from the embedded-tier adversarial review:

- ``create_app`` must NOT import from ``examples.*`` (HARD CONSTRAINT:
  ``src/celeste/**`` may not import ``examples/**``). Instead it receives a
  ``seed_loader`` callable + ``seed_dir`` path via DI.
- The caller (e.g. ``run_embedded.py``) passes the *correct* seed path.
  The old code computed ``Path(__file__).resolve().parents[2]/examples/...``
  which resolves to ``src/examples/...`` (NONEXISTENT — off by one). The
  caller now owns the path, eliminating that bug at the source.

TDD: these tests are written BEFORE the refactor and FAIL against the old
code (the old code never calls a injected loader, and the old hardcoded
path does not exist).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from celeste.api.app import create_app
from celeste.config.settings import EngineSettings
from celeste.core.evaluator import EvaluatorDecision
from celeste.core.planner import DAGFragment, DAGNode

# Importing the loader from examples is ALLOWED in tests/examples wiring
# (only src/celeste/** is forbidden from doing so).
from examples.pharma_coldchain.seed_data.load import load_seed_data


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"
_TERMINAL = {"completed", "paused", "failed", "escalated", "cancelled"}

# Real seed dir (the hyphenated example directory). The caller knows the
# right path; core never computes it.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_SEED_DIR = _REPO_ROOT / "examples" / "pharma-coldchain" / "seed_data"


def _tool_node(name: str, command: str, args: dict[str, Any] | None = None) -> DAGNode:
    return DAGNode(
        name=name,
        task_type="tool_execution",
        command=command,
        arguments=args or {},
        dependencies=[],
    )


class _FakePlanner:
    """Planner returning a trivial single-node fragment; goal_achieved=True."""

    def __init__(self) -> None:
        self._fragment = DAGFragment(
            nodes=[
                _tool_node("read_readme", command="read_file", args={"path": "README.md"}),
            ],
            reasoning="Read the project README.",
            goal_achieved=True,
        )

    async def plan(self, goal, observation=None, tool_schemas=None, history=None, timeout_ms=60000):
        return self._fragment


class _FakeEvaluator:
    async def evaluate(self, fragment, goal):
        return EvaluatorDecision.DONE


def _fake_planner_factory(settings, toolkits, llm_client):
    return _FakePlanner()


def _fake_evaluator_factory(settings, llm_client):
    return _FakeEvaluator()


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


async def _poll_until_terminal(client: httpx.AsyncClient, run_id: str, timeout: float = 30.0) -> dict:
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


class TestSeedLoaderDI:
    """Fix A: seed loading uses dependency injection (no core->examples import)."""

    @pytest.mark.asyncio
    async def test_seed_loader_invoked_with_existing_seed_dir(self, settings):
        """The injected seed_loader must be called with a seed_dir that EXISTS.

        This pins down the path-correctness bug: the old hardcoded
        ``parents[2]/examples/...`` resolved to ``src/examples/...`` which does
        NOT exist. The injected seed_dir (owned by the caller) must point at
        the real directory.
        """
        received_paths: list[Path] = []

        async def _capturing_loader(db_url: str, seed_dir: Path) -> dict[str, int]:
            received_paths.append(seed_dir)
            # The seed_dir passed in MUST exist — that's the whole point.
            assert seed_dir.exists(), f"seed_dir does not exist: {seed_dir}"
            # Actually run the real loader to prove no FileNotFoundError.
            return await load_seed_data(db_url, seed_dir)

        app = create_app(
            settings=settings,
            toolkits=[],
            planner_factory=_fake_planner_factory,
            evaluator_factory=_fake_evaluator_factory,
            seed_loader=_capturing_loader,
            seed_dir=_REAL_SEED_DIR,
        )

        lifespan_cm = app.router.lifespan_context(app)
        await lifespan_cm.__aenter__()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/runs", json={"goal": "seed-di-test-goal"})
                assert resp.status_code == 202, resp.text
                run_id = resp.json()["run_id"]
                status = await _poll_until_terminal(client, run_id)
                assert status["status"] == "completed", f"unexpected: {status}"
        finally:
            if hasattr(app.state, "running_run_tasks"):
                for task in list(app.state.running_run_tasks.values()):
                    if not task.done():
                        task.cancel()
                for task in list(app.state.running_run_tasks.values()):
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
            await lifespan_cm.__aexit__(None, None, None)

        # The loader was invoked at least once with the injected (existing) path.
        assert len(received_paths) == 1, f"expected 1 invocation, got {received_paths}"
        assert received_paths[0].exists()

    @pytest.mark.asyncio
    async def test_seed_loader_skipped_when_not_provided(self, settings):
        """When seed_loader is None (default), the run still works without seed loading.

        Backward compatibility: existing callers (test fixtures, monitoring)
        pass no seed_loader and the run completes normally.
        """
        # Use a file-based SQLite URL so a real loader (if mistakenly called)
        # could persist; but since seed_loader=None it must never be invoked.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            settings = EngineSettings(
                DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
                MAX_PARALLEL_SUBPROCESSES=2,
                WORKSPACE_ENGINE="local_tmp",
            )
            app = create_app(
                settings=settings,
                toolkits=[],
                planner_factory=_fake_planner_factory,
                evaluator_factory=_fake_evaluator_factory,
                # No seed_loader / seed_dir — default None.
            )
            assert app.state.seed_loader is None
            assert app.state.seed_dir is None

            lifespan_cm = app.router.lifespan_context(app)
            await lifespan_cm.__aenter__()
            try:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post("/api/runs", json={"goal": "no-seed-goal"})
                    assert resp.status_code == 202
                    run_id = resp.json()["run_id"]
                    status = await _poll_until_terminal(client, run_id)
                    assert status["status"] == "completed", f"unexpected: {status}"
            finally:
                if hasattr(app.state, "running_run_tasks"):
                    for task in list(app.state.running_run_tasks.values()):
                        if not task.done():
                            task.cancel()
                    for task in list(app.state.running_run_tasks.values()):
                        try:
                            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError):
                            pass
                await lifespan_cm.__aexit__(None, None, None)


def test_core_does_not_import_examples():
    """HARD CONSTRAINT: src/celeste/** must not import from examples/**.

    Static check: grep the app module source for a forbidden import.
    """
    app_src = Path(create_app.__module__.replace(".", "/") + ".py")
    # Resolve relative to the repo root via the module's actual file.
    import celeste.api.app as _mod

    app_file = Path(_mod.__file__)
    text = app_file.read_text()
    assert "from examples." not in text, (
        "src/celeste/api/app.py must not import from examples.* — use DI"
    )
    assert "import examples." not in text, (
        "src/celeste/api/app.py must not import examples.* — use DI"
    )
