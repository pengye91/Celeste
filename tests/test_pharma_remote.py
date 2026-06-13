"""Tests for the pharma cold-chain REMOTE tier.

Verifies the real WebSocket remote wiring end-to-end (no LLM):
- ``run_pharma_remote`` is importable and async-callable.
- A stub planner/evaluator drives the OPA loop over a real WebSocket,
  and a toolkit tool that exists ONLY server-side is invoked, proving
  ``call_tool`` crossed to the server.
- The OPA loop creates a Workflow row and emits WorkflowEvent rows.

Tests follow strict TDD and never call a real LLM: a stub planner returns
a fragment that invokes a server-only tool, and a stub evaluator returns
DONE on the first cycle.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from celeste.core.agent.agent import EnvironmentAgent
from celeste.core.agent.transport_ws import WebSocketServer
from celeste.core.evaluator import EvaluatorDecision
from celeste.core.planner import DAGFragment, DAGNode
from celeste.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


# ---------------------------------------------------------------------------
# DB reset fixture (mirrors tests/test_engine.py)
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


# ---------------------------------------------------------------------------
# Example dir on sys.path so run_remote (a sibling script) imports cleanly.
# ---------------------------------------------------------------------------


def _add_example_to_path() -> None:
    example_dir = str(
        Path(__file__).resolve().parent.parent
        / "examples"
        / "pharma-coldchain"
    )
    if example_dir not in sys.path:
        sys.path.insert(0, example_dir)


# ---------------------------------------------------------------------------
# Server-only toolkit: a tool that exists ONLY on the server agent. If the
# client executes call_tool locally it would return tool_not_found; the only
# way to get the echo back is for the request to cross the WebSocket.
# ---------------------------------------------------------------------------


class _ServerOnlyToolkit(BaseToolkit):
    """Toolkit exposing a uniquely-named tool registered server-side only."""

    TOOL_NAME = "pharma_remote_marker_tool"

    @property
    def name(self):
        return "server_only"

    @property
    def description(self):
        return "Toolkit whose sole tool is registered server-side only."

    def get_tools(self):
        return [
            ToolDefinition(
                name=self.TOOL_NAME,
                description="A tool that exists only on the server agent.",
                parameters=[
                    ToolParameter(
                        name="ping",
                        type="string",
                        description="Value echoed back by the server.",
                        required=False,
                        default="pong",
                    ),
                ],
                returns="An echo dict with the ping value.",
            ),
        ]

    def get_tool(self, name):
        for tool in self.get_tools():
            if tool.name == name:
                return tool
        return None

    async def execute(self, name, arguments, driver):
        if name == self.TOOL_NAME:
            return {
                "echo": arguments.get("ping", "pong"),
                "served_by": "server",
            }
        return {"error": "tool_not_found", "tool_name": name}


# ---------------------------------------------------------------------------
# Stub planner / evaluator (no LLM)
# ---------------------------------------------------------------------------


def _tool_node(name: str, command: str, args: dict[str, Any] | None = None) -> DAGNode:
    return DAGNode(
        name=name,
        task_type="tool_execution",
        command=command,
        arguments=args or {},
        dependencies=[],
    )


class _StubPlanner:
    """Stub planner that returns a fragment invoking a server-only tool."""

    def __init__(self, fragment: DAGFragment) -> None:
        self._fragment = fragment
        self.plan_calls = 0

    async def plan(self, goal, observation=None, tool_schemas=None, history=None, timeout_ms=60000):
        self.plan_calls += 1
        return self._fragment


class _StubEvaluator:
    """Stub evaluator that returns DONE immediately."""

    def __init__(self, decisions: list[EvaluatorDecision] | None = None) -> None:
        self._decisions = decisions or [EvaluatorDecision.DONE]
        self._i = 0

    async def evaluate(self, fragment, goal):
        d = self._decisions[min(self._i, len(self._decisions) - 1)]
        self._i += 1
        return d


# ---------------------------------------------------------------------------
# Importability / async-callable
# ---------------------------------------------------------------------------


def test_run_pharma_remote_is_async_callable():
    """run_pharma_remote must be importable and async-callable (coroutine)."""
    _add_example_to_path()
    import run_remote

    import inspect

    assert hasattr(run_remote, "run_pharma_remote")
    assert callable(run_remote.run_pharma_remote)
    assert inspect.iscoroutinefunction(run_remote.run_pharma_remote)


# ---------------------------------------------------------------------------
# End-to-end remote OPA loop over a real WebSocket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_opa_loop_invokes_server_tool():
    """Drive the OPA loop over a real WebSocket; the client's call_tool must
    cross to the server and invoke a server-only toolkit tool.

    A stub planner returns a fragment whose node invokes
    ``pharma_remote_marker_tool`` (which exists ONLY on the server). If the
    request executed locally the tool would be missing; the only way it
    succeeds is through the WebSocket transport.
    """
    pytest.importorskip("websockets")

    # Server: in-process agent WITH the server-only toolkit.
    server_toolkit = _ServerOnlyToolkit()
    server_agent = EnvironmentAgent.in_process(
        workdir=".", toolkits=[server_toolkit]
    )
    server = WebSocketServer(host="127.0.0.1", port=0, agent=server_agent)
    await server.start()

    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"

        # Client: remote agent (transport only; no drivers/toolkits).
        client_agent = EnvironmentAgent.remote(url=url)
        await client_agent.start()

        try:
            # Sanity: the client must NOT have the marker toolkit locally.
            assert not any(
                t.name == _ServerOnlyToolkit.TOOL_NAME
                for t in client_agent._toolkits
            )

            # list_tools must cross to the server and include the marker tool.
            tools = await client_agent.list_tools()
            names = [t["name"] for t in tools]
            assert _ServerOnlyToolkit.TOOL_NAME in names

            # call_tool must cross to the server and execute the marker tool.
            result = await client_agent.call_tool(
                _ServerOnlyToolkit.TOOL_NAME, {"ping": "hello-remote"}
            )
            assert isinstance(result, dict)
            assert "error" not in result, f"unexpected error: {result}"
            assert result.get("echo") == "hello-remote"
            assert result.get("served_by") == "server"
        finally:
            await client_agent.stop()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_opa_loop_creates_workflow_row():
    """Driving OPALoop.run with a remote client creates a Workflow row + events.

    Uses an in-memory SQLite DB (via EngineSettings) so the OPA loop can
    persist its Workflow / WorkflowEvent rows. The remote client forwards
    the snapshot + marker-tool calls to the server.
    """
    pytest.importorskip("websockets")
    from celeste.config.settings import EngineSettings
    from celeste.core.opa_loop import OPALoop
    from celeste.database.db import get_session
    from celeste.database.models import Workflow, WorkflowEvent

    # In-memory SQLite so OPA loop can write Workflow rows.
    settings = EngineSettings(DATABASE_URL="sqlite+aiosqlite://")  # type: ignore[arg-type]
    settings.MAX_PARALLEL_SUBPROCESSES = 1

    # Server: in-process agent WITH the server-only toolkit.
    server_toolkit = _ServerOnlyToolkit()
    server_agent = EnvironmentAgent.in_process(
        workdir=".", toolkits=[server_toolkit]
    )
    server = WebSocketServer(host="127.0.0.1", port=0, agent=server_agent)
    await server.start()

    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"
        client_agent = EnvironmentAgent.remote(url=url)
        await client_agent.start()

        try:
            # Planner: one fragment invoking the server-only marker tool,
            # goal_achieved=True so the loop terminates in a single cycle.
            fragment = DAGFragment(
                nodes=[
                    _tool_node(
                        "remote_marker_call",
                        command=_ServerOnlyToolkit.TOOL_NAME,
                        args={"ping": "from-opa"},
                    )
                ],
                reasoning="Invoke the server-only tool over the WebSocket.",
                goal_achieved=True,
            )
            planner = _StubPlanner(fragment=fragment)
            evaluator = _StubEvaluator(decisions=[EvaluatorDecision.DONE])

            loop = OPALoop(agent=client_agent, planner=planner, evaluator=evaluator)
            result = await loop.run(goal="remote pharma cold-chain goal")

            # The loop completed.
            assert result.status == "completed"
            assert result.workflow_id is not None

            # A Workflow row exists in the DB with the expected status.
            async with get_session() as session:
                wf_rows = (
                    await session.execute(
                        select(Workflow).where(Workflow.id == result.workflow_id)
                    )
                ).scalar_one_or_none()
                assert wf_rows is not None, "Workflow row not persisted"

                # At least one WorkflowEvent was emitted.
                event_rows = (
                    await session.execute(
                        select(WorkflowEvent).where(
                            WorkflowEvent.workflow_id == result.workflow_id
                        )
                    )
                ).scalars().all()
                assert len(event_rows) >= 1, "No WorkflowEvent rows emitted"
        finally:
            await client_agent.stop()
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# ExampleRunner.run_remote integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_example_runner_run_remote():
    """ExampleRunner.run_remote spins up an in-process server + remote client
    and drives the OPA loop, returning an ExampleResult with mode='remote'."""
    pytest.importorskip("websockets")
    from celeste.config.settings import EngineSettings
    from celeste.core.evaluator import EvaluatorDecision
    from celeste.core.opa_loop import OPALoop  # noqa: F401  (sanity import)
    from celeste.examples.runner import ExampleRunner

    server_toolkit = _ServerOnlyToolkit()

    # Stub planner fragment that completes immediately (no tool node needed
    # to exercise the runner's plumbing).
    fragment = DAGFragment(
        nodes=[],
        reasoning="Goal achieved",
        goal_achieved=True,
    )
    planner = _StubPlanner(fragment=fragment)
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.DONE])

    runner = ExampleRunner(example_dir="examples/pharma-coldchain")
    result = await runner.run_remote(
        goal="runner remote goal",
        agent=None,  # runner builds its own client
        planner=planner,
        evaluator=evaluator,
        server_toolkits=[server_toolkit],
    )

    assert result.mode == "remote"
    # The stub planner finishes in one cycle; the workflow should complete.
    assert result.errors == []
    assert result.workflow_result is not None
    assert result.workflow_result.status == "completed"


# ---------------------------------------------------------------------------
# serve_agent._load_seed_best_effort retry loop (Fix C)
# ---------------------------------------------------------------------------
# A transient "postgres healthy but still finishing initdb" window used to
# silently leave the DB unseeded because a single load_seed_data failure was
# caught and logged with no retry. Fix C adds a small retry loop (a few
# attempts with short backoff) so transient failures recover, while still
# being best-effort (logs + continues on final failure).

def _import_serve_agent():
    """Import examples/pharma-coldchain/serve_agent.py (hyphenated dir)."""
    _add_example_to_path()
    import serve_agent

    return serve_agent


@pytest.mark.asyncio
async def test_load_seed_best_effort_retries_transient_failure_then_succeeds(monkeypatch):
    """A transient load_seed_data failure must be retried until it succeeds.

    Fix C: _load_seed_best_effort wraps load_seed_data in a small retry loop
    (2-3 attempts with short backoff). If the first 1-2 attempts fail
    transiently (e.g. the DB is healthy per the probe but still finishing
    initdb), a later attempt must succeed and the function must NOT raise and
    NOT log a final-failure warning.
    """
    serve_agent = _import_serve_agent()

    attempts: list[int] = []

    async def _flaky_load(db_url, seed_dir, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient: relation does not exist yet")
        return {"hubs": 5, "batches": 10}

    monkeypatch.setattr(serve_agent, "load_seed_data", _flaky_load)
    # Shorten backoff so the test is fast: patch asyncio.sleep used inside.
    import asyncio as _asyncio

    real_sleep = _asyncio.sleep

    async def _fast_sleep(delay):
        # Collapse any backoff delay to near-zero for the test.
        return await real_sleep(0)

    monkeypatch.setattr(serve_agent.asyncio, "sleep", _fast_sleep)

    # Should NOT raise: the third attempt succeeds.
    await serve_agent._load_seed_best_effort("postgresql+asyncpg://x/y")

    assert len(attempts) == 3, (
        f"_load_seed_best_effort should retry until success; got "
        f"{len(attempts)} attempts (expected 3: 2 transient failures + 1 success)"
    )


@pytest.mark.asyncio
async def test_load_seed_best_effort_final_failure_is_best_effort(monkeypatch):
    """If ALL attempts fail, _load_seed_best_effort must log + continue (not raise).

    Fix C keeps the best-effort contract: after exhausting retries it logs a
    warning and returns normally so a seed-load bug never masks a real bug
    or aborts serving.
    """
    serve_agent = _import_serve_agent()

    attempts: list[int] = []

    async def _always_fails(db_url, seed_dir, **kwargs):
        attempts.append(1)
        raise RuntimeError("persistent failure")

    monkeypatch.setattr(serve_agent, "load_seed_data", _always_fails)
    import asyncio as _asyncio

    real_sleep = _asyncio.sleep

    async def _fast_sleep(delay):
        return await real_sleep(0)

    monkeypatch.setattr(serve_agent.asyncio, "sleep", _fast_sleep)

    # Should NOT raise: best-effort logs and continues.
    await serve_agent._load_seed_best_effort("postgresql+asyncpg://x/y")

    # It must have retried at least twice (i.e. the loop exists), not given up
    # after a single attempt.
    assert len(attempts) >= 2, (
        f"_load_seed_best_effort should retry on failure; got {len(attempts)} "
        "attempt(s) — expected at least 2 (retry loop missing)"
    )
