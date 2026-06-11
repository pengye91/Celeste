"""End-to-end tests for Celeste-DAG remote agent via WebSocket."""

import pytest

from celeste_dag.core.agent.agent import EnvironmentAgent
from celeste_dag.core.exceptions import AuthenticationError


@pytest.mark.asyncio
async def test_e2e_remote_agent_roundtrip():
    """EnvironmentAgent.remote should connect to a WebSocket server and call tools."""
    pytest.importorskip("websockets")
    from celeste_dag.core.agent.transport_ws import WebSocketServer

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
    from celeste_dag.core.agent.transport_ws import WebSocketServer

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
    from celeste_dag.core.agent.transport_ws import WebSocketServer

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
