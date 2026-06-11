"""Stdio transport for Celeste-DAG Environment Agent Protocol.

Sends JSON-RPC 2.0 requests over a subprocess's stdin and reads responses
from stdout.  Used for CLI tools, local integrations, and testing.
"""

import asyncio
import json
from typing import Any

from .transport import BaseTransport


class StdioTransport(BaseTransport):
    """Transport that communicates with an agent via stdin/stdout JSON-RPC.

    Each request is serialized as a single JSON line (JSONL) and written to
    ``process.stdin``.  The response is read as a single JSON line from
    ``process.stdout`` and correlated back to the caller via the ``id`` field.
    """

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC 2.0 request and return the parsed result.

        Args:
            method: JSON-RPC method name.
            params: Method parameters.

        Returns:
            The ``result`` field from the JSON-RPC response.

        Raises:
            RuntimeError: If the response contains a JSON-RPC error.
        """
        async with self._lock:
            request_id = self._next_id
            self._next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }
        line = json.dumps(payload) + "\n"

        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()

        # Read response line
        response_bytes = await self._process.stdout.readline()
        if not response_bytes:
            raise RuntimeError("Subprocess closed stdout before responding")

        response = json.loads(response_bytes.decode("utf-8"))

        if "error" in response:
            err = response["error"]
            raise RuntimeError(
                f"JSON-RPC error {err.get('code')}: {err.get('message')}"
            )

        return response.get("result")

    async def close(self) -> None:
        """Close stdin to signal EOF to the subprocess."""
        if self._process.stdin is not None:
            self._process.stdin.close()
            await self._process.stdin.wait_closed()
