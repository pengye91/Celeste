"""End-to-end tests for Celeste-DAG remote agent via WebSocket."""

import asyncio
import socket

import pytest

from celeste.core.agent.agent import EnvironmentAgent
from celeste.core.exceptions import AuthenticationError
from celeste.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


# ---------------------------------------------------------------------------
# A toolkit with a distinctly-named tool, used to prove list_tools queries the
# server rather than returning the client's local builtins.
# ---------------------------------------------------------------------------

class _RemoteMarkerToolkit(BaseToolkit):
    """Toolkit exposing a uniquely-named tool that only exists on the server."""

    TOOL_NAME = "celeste_remote_marker_tool"

    @property
    def name(self):
        return "remote_marker"

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
            return {"echo": arguments.get("ping", "pong"), "served_by": "server"}
        return {"error": "tool_not_found", "tool_name": name}


@pytest.mark.asyncio
async def test_e2e_remote_agent_roundtrip():
    """EnvironmentAgent.remote should connect to a WebSocket server and call tools."""
    pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketServer

    # Create a server-side agent
    server_agent = EnvironmentAgent.in_process(workdir=".")
    server = WebSocketServer(host="127.0.0.1", port=0, agent=server_agent)
    await server.start()
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"

        # Create a remote client agent
        client_agent = EnvironmentAgent.remote(url=url)
        await client_agent.start()
        try:
            tools = await client_agent.list_tools()
            assert isinstance(tools, list)
            assert len(tools) > 0
            names = [t["name"] for t in tools]
            assert "read_file" in names
            assert "run_command" in names
        finally:
            await client_agent.stop()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_e2e_remote_auth_failure():
    """EnvironmentAgent.remote should raise AuthenticationError with bad token."""
    pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketServer

    server_agent = EnvironmentAgent.in_process(workdir=".")
    server = WebSocketServer(host="127.0.0.1", port=0, agent=server_agent, auth_token="secret")
    await server.start()
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"

        client_agent = EnvironmentAgent.remote(url=url, auth_token="wrong")
        with pytest.raises(AuthenticationError):
            await client_agent.start()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_e2e_remote_reconnection():
    """Remote agent should auto-reconnect after server restart."""
    pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketServer

    server_agent = EnvironmentAgent.in_process(workdir=".")
    server = WebSocketServer(host="127.0.0.1", port=0, agent=server_agent)
    await server.start()
    addr = None
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"

        client_agent = EnvironmentAgent.remote(url=url)
        await client_agent.start()
        try:
            # Verify initial connection works
            tools = await client_agent.list_tools()
            assert len(tools) > 0

            # Stop and restart server
            await server.stop()
            server = WebSocketServer(host="127.0.0.1", port=addr[1], agent=server_agent)
            await server.start()

            # Should auto-reconnect and work again
            tools = await client_agent.list_tools()
            assert len(tools) > 0
        finally:
            await client_agent.stop()
    finally:
        if server is not None:
            await server.stop()


# ---------------------------------------------------------------------------
# Transport-routing tests: call_tool / list_tools must go through the
# WebSocket transport (server-side execution) rather than executing locally.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_remote_call_tool():
    """EnvironmentAgent.remote.call_tool must execute on the SERVER.

    A remote (client) agent has no drivers/toolkits, so call_tool only works
    if it routes the request through the WebSocket transport to the server
    agent, which actually executes run_command.
    """
    pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketServer

    # Server agent is a real in-process agent WITH a ShellDriver.
    server_agent = EnvironmentAgent.in_process(workdir=".")
    server = WebSocketServer(host="127.0.0.1", port=0, agent=server_agent)
    await server.start()
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"

        # Client agent built via remote() has a transport but NO drivers.
        client_agent = EnvironmentAgent.remote(url=url)
        await client_agent.start()
        try:
            result = await client_agent.call_tool(
                "run_command", {"command": "echo", "args": ["celeste-remote"]}
            )
            # The result must reflect execution on the server: stdout contains
            # the echoed marker string. A local-execution path would have no
            # driver and return {"error": "no_driver"}.
            assert isinstance(result, dict)
            assert "error" not in result, f"unexpected error: {result}"
            stdout = result.get("stdout", "")
            assert "celeste-remote" in stdout
        finally:
            await client_agent.stop()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_e2e_remote_list_tools_toolkit():
    """EnvironmentAgent.remote.list_tools must query the SERVER's toolkits.

    Register a toolkit with a distinctly-named tool on the SERVER agent only.
    The client agent's list_tools() must include that tool, proving it queries
    the server rather than returning only its own local builtins.
    """
    pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketServer

    marker = _RemoteMarkerToolkit()
    server_agent = EnvironmentAgent.in_process(workdir=".", toolkits=[marker])
    server = WebSocketServer(host="127.0.0.1", port=0, agent=server_agent)
    await server.start()
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"

        client_agent = EnvironmentAgent.remote(url=url)
        # Confirm the client does NOT have the marker toolkit registered locally,
        # so the only way it can see the tool is by asking the server.
        assert not any(
            t.name == _RemoteMarkerToolkit.TOOL_NAME
            for t in client_agent._toolkits
        )
        await client_agent.start()
        try:
            tools = await client_agent.list_tools()
            names = [t["name"] for t in tools]
            assert _RemoteMarkerToolkit.TOOL_NAME in names
        finally:
            await client_agent.stop()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_e2e_remote_call_tool_toolkit():
    """A remote client must be able to invoke a server-only toolkit tool."""
    pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketServer

    marker = _RemoteMarkerToolkit()
    server_agent = EnvironmentAgent.in_process(workdir=".", toolkits=[marker])
    server = WebSocketServer(host="127.0.0.1", port=0, agent=server_agent)
    await server.start()
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"

        client_agent = EnvironmentAgent.remote(url=url)
        await client_agent.start()
        try:
            result = await client_agent.call_tool(
                _RemoteMarkerToolkit.TOOL_NAME, {"ping": "hello-from-client"}
            )
            assert isinstance(result, dict)
            assert result.get("echo") == "hello-from-client"
            assert result.get("served_by") == "server"
        finally:
            await client_agent.stop()
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# Serve-mode lifecycle: EnvironmentAgent.serve(...).start() must bind a port
# and stop() must release it (regression guard for the serve() runner).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serve_mode_start_binds_port_stop_releases():
    """EnvironmentAgent.serve(...).start() binds a port; stop() releases it.

    The serve() factory sets agent._server; start() must start the
    WebSocketServer (not just connect a transport), and stop() must release
    the bound socket so the port is free again.
    """
    pytest.importorskip("websockets")

    agent = EnvironmentAgent.serve(host="127.0.0.1", port=0, workdir=".")
    # _server must be set by the serve() factory.
    assert getattr(agent, "_server", None) is not None

    await agent.start()
    assert agent.is_running

    # The server must have bound a real port (port=0 -> OS-assigned).
    bound_port = agent._server._port
    assert isinstance(bound_port, int) and bound_port > 0

    try:
        # A client should be able to connect to the served agent and list tools.
        url = f"ws://127.0.0.1:{bound_port}"
        client = EnvironmentAgent.remote(url=url)
        await client.start()
        try:
            tools = await client.list_tools()
            assert isinstance(tools, list)
            names = [t["name"] for t in tools]
            # Built-in tools must be advertised by the served agent.
            assert "read_file" in names
        finally:
            await client.stop()
    finally:
        await agent.stop()

    # After stop(), the agent is no longer running and the server socket is gone.
    assert not agent.is_running
    assert agent._server._server is None


@pytest.mark.asyncio
async def test_serve_mode_idempotent_stop():
    """Calling stop() on a serve-mode agent twice must not raise."""
    pytest.importorskip("websockets")

    agent = EnvironmentAgent.serve(host="127.0.0.1", port=0, workdir=".")
    await agent.start()
    await agent.stop()
    # Second stop() must be a safe no-op (idempotent teardown).
    await agent.stop()
    assert not agent.is_running


@pytest.mark.asyncio
async def test_serve_module_serve_coroutine_runs_and_cancels():
    """celeste.core.agent.serve.serve() runs until cancelled, then stops cleanly."""
    pytest.importorskip("websockets")
    from celeste.core.agent.serve import serve

    task = asyncio.create_task(
        serve(host="127.0.0.1", port=0, workdir=".", toolkits=None)
    )
    # Give the server a moment to bind.
    await asyncio.sleep(0.3)
    assert not task.done(), "serve() should still be running (blocking)"

    # Cancel -> graceful shutdown via the finally clause.
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.done()


# ---------------------------------------------------------------------------
# serve() start() failure cleanup (Fix A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serve_cleans_up_when_start_fails_bound_port():
    """serve() must call agent.stop() even when agent.start() raises.

    Regression guard (Fix A): ``await agent.start()`` used to live OUTSIDE the
    try/finally in serve(), so a start() failure (e.g. port already in use,
    permission denied) left the partially-built agent's resources / server
    task un-cleaned. After the fix, start() is inside the try block, so the
    finally clause always runs ``agent.stop()``.

    We occupy a real port with a blocking socket so websockets.serve() raises
    OSError on bind, then assert:
      1. serve() re-raises the start failure (does not swallow it).
      2. cleanup ran: the agent's stop() was invoked (spied), and the agent
         reports it is not running.
      3. no other exception leaks beyond the start failure.
    """
    pytest.importorskip("websockets")
    from celeste.core.agent import agent as agent_mod
    from celeste.core.agent.serve import serve

    # Occupy a port so the agent's start() cannot bind it.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    occupied_port = blocker.getsockname()[1]

    # Spy on EnvironmentAgent.stop to prove the finally clause runs it.
    stop_calls: list[bool] = []
    real_stop = agent_mod.EnvironmentAgent.stop

    async def _spying_stop(self):
        stop_calls.append(True)
        return await real_stop(self)

    # Spy on start to also confirm it actually raised (sanity).
    start_calls: list[bool] = []
    real_start = agent_mod.EnvironmentAgent.start

    async def _spying_start(self):
        start_calls.append(True)
        return await real_start(self)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(agent_mod.EnvironmentAgent, "stop", _spying_stop)
    monkeypatch.setattr(agent_mod.EnvironmentAgent, "start", _spying_start)

    raised_exc: BaseException | None = None
    try:
        await serve(
            host="127.0.0.1",
            port=occupied_port,
            workdir=".",
            toolkits=None,
        )
    except OSError as exc:
        raised_exc = exc
    finally:
        monkeypatch.undo()
        blocker.close()

    # 1. The start failure propagated (not swallowed).
    assert raised_exc is not None, (
        "serve() should have raised OSError on the bound port"
    )
    assert isinstance(raised_exc, OSError)
    assert start_calls, "agent.start() must have been attempted"

    # 2. Cleanup ran: stop() was called by the finally clause.
    assert stop_calls, (
        "serve() must call agent.stop() on start() failure (Fix A: start() "
        "must be inside the try/finally so cleanup always runs)"
    )

    # 3. No lingering serve task: there is no background asyncio task left
    #    running serve() (it returned/raised, so it is not still blocking).
    current = asyncio.current_task()
    for t in asyncio.all_tasks():
        if t is current:
            continue
        # serve() should NOT be among the running tasks; only pytest infra may be.
        coro_name = getattr(t.get_coro(), "__name__", "") if t.get_coro() else ""
        assert coro_name != "serve", (
            "serve() task is still running after start() failure — resources leaked"
        )
