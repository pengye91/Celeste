"""Integration tests for agent attestation (TODO-4).

These exercise the full attestation flow end-to-end, unlike the unit tests
in test_attestation.py which use mocked transports:

1. Registration API: POST /agents/register with public_key_pem → stored →
   GET /agents returns the fingerprint.
2. Real serve ↔ remote WebSocket round-trip: the serve-mode agent signs
   results, the remote-mode agent verifies them over a real WebSocket.
3. Tampered signature blocked over real WebSocket.
4. OPA loop processes signed agent results correctly (execution logic
   sees the inner result, not the envelope).
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import select

from celeste.api.app import create_app
from celeste.config.settings import EngineSettings
from celeste.core.agent.agent import EnvironmentAgent
from celeste.core.attestation import (
    AttestationError,
    AttestationKeypair,
    sign_payload,
    verify_payload,
)
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.db import get_session, init_db
from celeste.database.models import Workflow, WorkflowStatus


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    )


# ---------------------------------------------------------------------------
# 1. Registration API integration
# ---------------------------------------------------------------------------


async def test_register_agent_with_public_key_end_to_end(settings):
    """POST /agents/register with public_key_pem stores it; GET /agents shows it."""
    await init_db(settings=settings)
    kp = AttestationKeypair.generate()

    app = create_app(settings=settings, workspace_factory=lambda: _NoopWorkspace())
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Register with a public key.
            resp = await client.post(
                "/agents/register",
                json={
                    "url": "ws://localhost:9999",
                    "public_key_pem": kp.public_key_pem,
                },
            )
            assert resp.status_code in (200, 201)
            data = resp.json()
            agent_id = data["agent_id"]
            # The fingerprint must match what we'd compute from the PEM.
            assert data["public_key_fingerprint"] is not None
            assert data["public_key_fingerprint"] == kp.key_id

            # GET /agents must show the fingerprint.
            list_resp = await client.get("/agents")
            assert list_resp.status_code == 200
            items = list_resp.json()
            assert len(items) >= 1
            registered = next(a for a in items if a["agent_id"] == agent_id)
            assert registered["public_key_fingerprint"] == kp.key_id

            # The agent_registry must have pinned the key for verification.
            registry_entry = app.state.agent_registry[agent_id]
            assert registry_entry["public_key_pem"] == kp.public_key_pem
    finally:
        await lifespan_cm.__aexit__(None, None, None)


async def test_register_agent_without_public_key(settings):
    """Registration without a public key works (backward-compatible)."""
    await init_db(settings=settings)

    app = create_app(settings=settings, workspace_factory=lambda: _NoopWorkspace())
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agents/register",
                json={"url": "ws://localhost:9999"},
            )
            assert resp.status_code in (200, 201)
            assert resp.json()["public_key_fingerprint"] is None
    finally:
        await lifespan_cm.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# 2. Real serve ↔ remote WebSocket round-trip with attestation
# ---------------------------------------------------------------------------


async def test_serve_remote_roundtrip_with_signing():
    """Serve-mode agent signs results; remote-mode agent verifies them.

    This is the full integration: a real WebSocket server that owns an
    EnvironmentAgent.serve() with a keypair, and a real WebSocket client
    that verifies the signed response.
    """
    websockets = pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketServer

    # Server-side: a real agent that signs its results.
    server_agent = EnvironmentAgent.serve(
        host="127.0.0.1",
        port=0,
        workdir="/tmp",
        toolkits=[],
    )
    server = WebSocketServer(
        host="127.0.0.1",
        port=0,
        agent=server_agent,
    )
    await server.start()
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"

        # Client-side: pin the server's public key and require attestation.
        client_agent = EnvironmentAgent.remote(
            url=url,
            expected_public_key_pem=server_agent.public_key_pem,
            attestation_required=True,
        )

        # The call_tool must succeed — the server signs, the client verifies.
        result = await client_agent.call_tool(
            "run_command", {"command": "echo", "args": ["integration"]}
        )
        # The envelope is stripped by the client — only inner result remains.
        assert "signature" not in result
        assert "exit_code" in result
    finally:
        await server.stop()


async def test_serve_remote_blocks_tampered_over_real_websocket():
    """If the server uses a different key than expected, verification fails.

    We can't easily tamper mid-flight over a real WebSocket, but we CAN
    pin the wrong key on the client side and verify that the real signed
    response is rejected.
    """
    websockets = pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketServer

    server_agent = EnvironmentAgent.serve(
        host="127.0.0.1",
        port=0,
        workdir="/tmp",
        toolkits=[],
    )
    server = WebSocketServer(
        host="127.0.0.1",
        port=0,
        agent=server_agent,
    )
    await server.start()
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"

        # Pin a DIFFERENT key on the client.
        wrong_key = AttestationKeypair.generate()
        client_agent = EnvironmentAgent.remote(
            url=url,
            expected_public_key_pem=wrong_key.public_key_pem,
            attestation_required=True,
        )

        with pytest.raises(AttestationError, match="Signature verification failed"):
            await client_agent.call_tool("run_command", {"command": "echo", "args": ["x"]})
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# 3. OPA loop processes signed agent results correctly
# ---------------------------------------------------------------------------


async def test_opa_loop_processes_signed_agent_results():
    """The OPA loop must handle signed tool results without breaking.

    The WorkflowExecutor calls agent.call_tool() and uses the result dict
    for execution logic (checking exit_code etc.). With attestation, the
    result carries extra 'signature' and 'key_id' keys. These extra keys
    must not break the executor's logic.

    We verify this by running a minimal OPA loop with a stub agent that
    returns signed results, and confirming the loop completes.
    """
    from celeste.core.opa_loop import OPALoop, WorkflowResult
    from celeste.core.planner import DAGFragment, DAGNode
    from celeste.core.evaluator import EvaluatorDecision

    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_OPA_CYCLES=5,
        MAX_LLM_TOKENS=50000,
    )
    await init_db(settings=settings)

    kp = AttestationKeypair.generate()

    class _SigningStubAgent:
        """Stub agent that returns signed tool results (like a real agent)."""

        async def call_tool(self, name, arguments=None, timeout_ms=None):
            if name == "snapshot":
                return sign_payload(kp, {"files": {}, "platform": "darwin"})
            # Tool execution: return a signed result with exit_code.
            return sign_payload(kp, {"exit_code": 0, "stdout": "ok"})

        async def list_tools(self):
            return []

    class _StubPlanner:
        async def plan(self, goal, observation=None, tool_schemas=None, history=None, timeout_ms=60000):
            return DAGFragment(
                nodes=[DAGNode(name="step", task_type="tool_execution", command="echo", arguments={})],
                reasoning="r",
                goal_achieved=True,
            )

    class _StubEvaluator:
        async def evaluate(self, fragment, goal):
            return EvaluatorDecision.DONE

    loop = OPALoop(
        agent=_SigningStubAgent(),
        planner=_StubPlanner(),
        evaluator=_StubEvaluator(),
        settings=settings,
    )
    result = await loop.run(goal="signed result test")

    assert isinstance(result, WorkflowResult)
    # The loop completed despite the agent returning signed (envelope-wrapped)
    # results with extra 'signature'/'key_id' keys.
    assert result.status == "completed"
