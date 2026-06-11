"""Tests for Celeste-DAG Environment Agent transport layer."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest



# ---------------------------------------------------------------------------
# MockAgent — minimal stand-in for an EnvironmentAgent instance
# ---------------------------------------------------------------------------

class MockAgent:
    """Minimal mock agent that implements the two internal handler methods."""

    def __init__(self):
        self._handle_call_tool = AsyncMock(return_value={"files": {}, "platform": "darwin"})
        self._handle_list_tools = AsyncMock(return_value=[
            {"name": "read_file", "description": "Read a file", "inputSchema": {}},
            {"name": "snapshot", "description": "Take a snapshot", "inputSchema": {}},
        ])


# ---------------------------------------------------------------------------
# Phase 1: InProcessTransport
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_in_process_transport_direct_call():
    """InProcessTransport should call agent methods directly without serialization."""
    from celeste.core.agent.transport import InProcessTransport

    agent = MockAgent()
    transport = InProcessTransport(agent)

    result = await transport.send_request("call_tool", {"name": "snapshot", "args": {}})

    assert isinstance(result, dict)
    assert "files" in result
    agent._handle_call_tool.assert_awaited_once_with({"name": "snapshot", "args": {}})


@pytest.mark.asyncio
async def test_in_process_transport_list_tools():
    """InProcessTransport should delegate list_tools to agent._handle_list_tools."""
    from celeste.core.agent.transport import InProcessTransport

    agent = MockAgent()
    transport = InProcessTransport(agent)

    result = await transport.send_request("list_tools", {})

    assert isinstance(result, list)
    assert len(result) == 2
    agent._handle_list_tools.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_in_process_transport_close_is_noop():
    """InProcessTransport.close() should be a no-op."""
    from celeste.core.agent.transport import InProcessTransport

    agent = MockAgent()
    transport = InProcessTransport(agent)

    await transport.close()


# ---------------------------------------------------------------------------
# Phase 1: StdioTransport
# ---------------------------------------------------------------------------

class FakeStreamReader:
    """Fake asyncio.StreamReader for stdout mocking."""

    def __init__(self):
        self._queue = asyncio.Queue()

    def queue_response(self, response_dict: dict) -> None:
        """Queue a JSON-RPC response line."""
        self._queue.put_nowait(json.dumps(response_dict).encode("utf-8") + b"\n")

    async def readline(self) -> bytes:
        """Return the next queued response as bytes."""
        return await self._queue.get()


class FakeStreamWriter:
    """Fake asyncio.StreamWriter for stdin mocking."""

    def __init__(self):
        self._written: list[bytes] = []
        self._closed = False

    def write(self, data: bytes) -> None:
        """Record written bytes."""
        self._written.append(data)

    async def drain(self) -> None:
        """No-op drain."""
        return None

    def close(self) -> None:
        """Mark as closed."""
        self._closed = True

    async def wait_closed(self) -> None:
        """No-op wait_closed."""
        return None

    @property
    def written(self) -> list[bytes]:
        """Return all written byte chunks."""
        return self._written


class FakeProcess:
    """A fake asyncio subprocess for testing StdioTransport."""

    def __init__(self):
        self.stdin = FakeStreamWriter()
        self.stdout = FakeStreamReader()

    def queue_response(self, response_dict: dict) -> None:
        """Queue a JSON-RPC response on the fake stdout."""
        self.stdout.queue_response(response_dict)


@pytest.mark.asyncio
async def test_stdio_transport_json_rpc():
    """StdioTransport should send JSON-RPC 2.0 requests and correlate responses by id."""
    from celeste.core.agent.transport_stdio import StdioTransport

    fake_proc = FakeProcess()
    fake_proc.queue_response({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"files": {"a.txt": "hello"}, "platform": "linux"},
    })

    transport = StdioTransport(fake_proc)

    result = await transport.send_request("call_tool", {"name": "snapshot", "args": {}})

    assert isinstance(result, dict)
    assert result["files"] == {"a.txt": "hello"}
    assert result["platform"] == "linux"

    # Verify JSON-RPC request was written to stdin
    assert len(fake_proc.stdin.written) == 1
    written = fake_proc.stdin.written[0].decode("utf-8")
    request = json.loads(written)
    assert request["jsonrpc"] == "2.0"
    assert request["method"] == "call_tool"
    assert request["params"] == {"name": "snapshot", "args": {}}
    assert request["id"] == 1


@pytest.mark.asyncio
async def test_stdio_transport_multiple_requests():
    """StdioTransport should handle multiple sequential requests with incrementing ids."""
    from celeste.core.agent.transport_stdio import StdioTransport

    fake_proc = FakeProcess()
    fake_proc.queue_response({"jsonrpc": "2.0", "id": 1, "result": "first"})
    fake_proc.queue_response({"jsonrpc": "2.0", "id": 2, "result": "second"})

    transport = StdioTransport(fake_proc)

    result1 = await transport.send_request("call_tool", {"name": "a"})
    result2 = await transport.send_request("call_tool", {"name": "b"})

    assert result1 == "first"
    assert result2 == "second"

    req1 = json.loads(fake_proc.stdin.written[0].decode("utf-8"))
    req2 = json.loads(fake_proc.stdin.written[1].decode("utf-8"))
    assert req1["id"] == 1
    assert req2["id"] == 2


@pytest.mark.asyncio
async def test_stdio_transport_error_response():
    """StdioTransport should raise on JSON-RPC error responses."""
    from celeste.core.agent.transport_stdio import StdioTransport

    fake_proc = FakeProcess()
    fake_proc.queue_response({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "Method not found"},
    })

    transport = StdioTransport(fake_proc)

    with pytest.raises(RuntimeError, match="Method not found"):
        await transport.send_request("unknown_method", {})


@pytest.mark.asyncio
async def test_stdio_transport_close():
    """StdioTransport.close() should close stdin to signal EOF to the subprocess."""
    from celeste.core.agent.transport_stdio import StdioTransport

    fake_proc = FakeProcess()

    transport = StdioTransport(fake_proc)
    await transport.close()

    assert fake_proc.stdin._closed is True


# ---------------------------------------------------------------------------
# Phase 4: WebSocketTransport
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_websocket_transport_roundtrip():
    """WebSocketTransport should send JSON-RPC requests and receive responses."""
    websockets = pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketTransport, WebSocketServer

    agent = MockAgent()
    server = WebSocketServer(host="127.0.0.1", port=0, agent=agent)
    await server.start()
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"
        transport = WebSocketTransport(url)
        await transport.connect()
        try:
            result = await transport.send_request("call_tool", {"name": "snapshot", "args": {}})
            assert isinstance(result, dict)
            assert "files" in result
            agent._handle_call_tool.assert_awaited_once_with({"name": "snapshot", "args": {}})
        finally:
            await transport.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_websocket_transport_auth_failure():
    """WebSocketTransport should raise AuthenticationError when token is rejected."""
    websockets = pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketTransport, WebSocketServer
    from celeste.core.exceptions import AuthenticationError

    agent = MockAgent()
    server = WebSocketServer(host="127.0.0.1", port=0, agent=agent, auth_token="secret")
    await server.start()
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"
        transport = WebSocketTransport(url, auth_token="wrong")
        with pytest.raises(AuthenticationError):
            await transport.connect()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_websocket_transport_reconnection():
    """WebSocketTransport should auto-reconnect with exponential backoff (max 3 attempts)."""
    websockets = pytest.importorskip("websockets")
    from celeste.core.agent.transport_ws import WebSocketTransport, WebSocketServer

    agent = MockAgent()
    server = WebSocketServer(host="127.0.0.1", port=0, agent=agent)
    await server.start()
    addr = None
    try:
        addr = server._server.sockets[0].getsockname()
        url = f"ws://{addr[0]}:{addr[1]}"
        transport = WebSocketTransport(url)
        await transport.connect()
        try:
            # Stop the server to force disconnect
            await server.stop()
            server = None

            # Start a new server on the same port
            server = WebSocketServer(host="127.0.0.1", port=addr[1], agent=agent)
            await server.start()

            # Request should succeed after auto-reconnect
            result = await transport.send_request("call_tool", {"name": "snapshot", "args": {}})
            assert isinstance(result, dict)
            assert "files" in result
        finally:
            await transport.close()
    finally:
        if server is not None:
            await server.stop()


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

def test_module_exports():
    """The agent module should export all expected symbols."""
    from celeste.core import agent

    assert hasattr(agent, "BaseTransport")
    assert hasattr(agent, "InProcessTransport")
    assert hasattr(agent, "StdioTransport")
    assert hasattr(agent, "WebSocketTransport")
    assert hasattr(agent, "WebSocketServer")
