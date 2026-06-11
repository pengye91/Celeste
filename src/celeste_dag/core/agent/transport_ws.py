"""WebSocket transport for Celeste-DAG Environment Agent Protocol.

Provides WebSocketTransport for client-side connections and WebSocketServer
for serving agent requests over WebSocket.
"""

import asyncio
import json
import logging
from typing import Any

from celeste_dag.core.agent.transport import BaseTransport
from celeste_dag.core.exceptions import AuthenticationError

logger = logging.getLogger(__name__)


class WebSocketTransport(BaseTransport):
    """Transport that communicates with a remote agent via WebSocket.

    Sends JSON-RPC 2.0 requests over a WebSocket connection and correlates
    responses by request id. Supports auto-reconnect with exponential backoff.
    """

    def __init__(self, url: str, auth_token: str | None = None) -> None:
        self._url = url
        self._auth_token = auth_token
        self._ws: Any | None = None
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future] = {}
        self._receive_task: asyncio.Task | None = None
        self._closed = False

    async def connect(self) -> None:
        """Establish WebSocket connection with optional auth token."""
        import websockets

        headers = {}
        if self._auth_token is not None:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        last_error: Exception | None = None
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                self._ws = await websockets.connect(
                    self._url,
                    additional_headers=headers,
                    open_timeout=5,
                )
                self._closed = False
                self._receive_task = asyncio.create_task(self._receive_loop())
                logger.debug("WebSocket connected to %s", self._url)
                return
            except websockets.exceptions.InvalidStatus as exc:
                last_error = exc
                status_code = exc.response.status_code if hasattr(exc, "response") else None
                if status_code in (401, 403):
                    raise AuthenticationError(
                        f"WebSocket authentication failed: {status_code}",
                        status_code=status_code,
                    ) from exc
                if attempt == max_attempts:
                    break
                wait = 2 ** (attempt - 1)
                logger.debug("WebSocket connect attempt %d failed, retrying in %ds", attempt, wait)
                await asyncio.sleep(wait)
            except Exception as exc:
                last_error = exc
                if attempt == max_attempts:
                    break
                wait = 2 ** (attempt - 1)
                logger.debug("WebSocket connect attempt %d failed, retrying in %ds", attempt, wait)
                await asyncio.sleep(wait)

        raise ConnectionError(
            f"Failed to connect to {self._url} after {max_attempts} attempts"
        ) from last_error

    async def send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC 2.0 request and return the parsed result.

        Auto-reconnects if the connection was lost (max 3 attempts).
        """
        import websockets

        max_attempts = 3
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                return await self._send_request_once(method, params)
            except (websockets.exceptions.ConnectionClosed, ConnectionError) as exc:
                last_error = exc
                if self._closed or attempt == max_attempts:
                    break
                logger.debug("WebSocket request failed, attempting reconnect %d/%d", attempt, max_attempts)
                await self._try_reconnect()

        raise ConnectionError(
            f"WebSocket request failed after {max_attempts} attempts"
        ) from last_error

    async def _send_request_once(self, method: str, params: dict) -> dict:
        """Send a single request without retry logic."""
        if self._ws is None or self._closed:
            raise ConnectionError("WebSocket not connected")

        async with self._lock:
            request_id = self._next_id
            self._next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        try:
            await self._ws.send(json.dumps(payload))
            result = await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise RuntimeError("WebSocket request timed out")
        except Exception:
            self._pending.pop(request_id, None)
            raise

        if "error" in result:
            err = result["error"]
            raise RuntimeError(
                f"JSON-RPC error {err.get('code')}: {err.get('message')}"
            )

        return result.get("result")

    async def _receive_loop(self) -> None:
        """Background task that reads responses and fulfills pending futures."""
        import websockets

        try:
            while self._ws is not None and not self._closed:
                try:
                    message = await self._ws.recv()
                except websockets.exceptions.ConnectionClosed:
                    break

                try:
                    response = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON: %s", message)
                    continue

                req_id = response.get("id")
                if req_id is not None and req_id in self._pending:
                    future = self._pending.pop(req_id)
                    if not future.done():
                        future.set_result(response)
        except Exception as exc:
            logger.debug("WebSocket receive loop ended: %s", exc)
        finally:
            # Fail any remaining pending requests
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("WebSocket connection closed"))
            self._pending.clear()

    async def _try_reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        await self._cleanup_connection()
        try:
            await self.connect()
        except Exception as exc:
            logger.debug("Reconnect failed: %s", exc)
            raise

    async def _cleanup_connection(self) -> None:
        """Clean up the current connection without marking as fully closed."""
        self._closed = True
        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def close(self) -> None:
        """Close the WebSocket connection and release resources."""
        self._closed = True
        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        # Fail any remaining pending requests
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(ConnectionError("WebSocket transport closed"))
        self._pending.clear()


class WebSocketServer:
    """Simple WebSocket server that accepts connections from remote engines.

    Handles JSON-RPC requests: call_tool, list_tools.
    Validates auth_token if configured.
    """

    def __init__(
        self,
        host: str,
        port: int,
        agent: Any,
        auth_token: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._agent = agent
        self._auth_token = auth_token
        self._server: asyncio.Server | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the WebSocket server."""
        import websockets
        from websockets.http11 import Headers, Response

        async def _process_request(connection, request) -> Response | None:
            if self._auth_token is not None:
                auth_header = request.headers.get("Authorization", "")
                if not auth_header.startswith("Bearer "):
                    return Response(
                        status_code=401,
                        reason_phrase="Unauthorized",
                        headers=Headers({"WWW-Authenticate": "Bearer"}),
                    )
                token = auth_header[7:]
                if token != self._auth_token:
                    return Response(
                        status_code=401,
                        reason_phrase="Unauthorized",
                        headers=Headers({"WWW-Authenticate": "Bearer"}),
                    )
            return None

        self._server = await websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
            process_request=_process_request,
        )
        # If port was 0, get the actual assigned port
        if self._port == 0 and self._server.sockets:
            self._port = self._server.sockets[0].getsockname()[1]
        logger.debug("WebSocketServer started on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        logger.debug("WebSocketServer stopped")

    async def _handle_connection(self, websocket) -> None:
        """Handle a single WebSocket connection."""
        import websockets

        try:
            async for message in websocket:
                try:
                    request = json.loads(message)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }))
                    continue

                req_id = request.get("id")
                method = request.get("method", "")
                params = request.get("params", {})

                try:
                    if method == "call_tool":
                        result = await self._agent._handle_call_tool(params)
                    elif method == "list_tools":
                        result = await self._agent._handle_list_tools()
                    else:
                        response = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32601, "message": f"Method not found: {method}"},
                        }
                        await websocket.send(json.dumps(response))
                        continue

                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": result,
                    }
                    await websocket.send(json.dumps(response))
                except Exception as exc:
                    logger.exception("Error handling request")
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32603, "message": str(exc)},
                    }
                    await websocket.send(json.dumps(response))
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as exc:
            logger.debug("Connection handler error: %s", exc)
