"""End-to-end tests for Celeste-DAG remote agent via WebSocket."""

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
