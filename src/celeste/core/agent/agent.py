"""Celeste-DAG Environment Agent Protocol — EnvironmentAgent.

The EnvironmentAgent is the engine's sole interface to a target environment.
It provides observation (read-only queries) and execution (state modification)
capabilities via a unified tool-calling protocol.

Supports three deployment modes:
- In-process: direct Python function calls (no serialization)
- Remote: WebSocket connection to a distant agent
- Serve: standalone WebSocket server (stub for Phase 4)
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from typing import Any

from celeste.core.agent.driver import (
    BaseDriver,
    CommandResult,
    FileResult,
    ShellDriver,
    FilesystemDriver,
)
from celeste.core.agent.transport import BaseTransport, InProcessTransport
from celeste.core.exceptions import ToolTimeoutError
from celeste.toolkits.base import BaseToolkit


# ---------------------------------------------------------------------------
# Built-in tool schemas (MCP-compatible)
# ---------------------------------------------------------------------------

_BUILTIN_TOOLS = [
    {
        "name": "snapshot",
        "description": "Return a consolidated environment snapshot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "description": "List of directory paths to include.",
                },
                "include_processes": {
                    "type": "boolean",
                    "description": "Whether to include process info.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_directory",
        "description": "List the contents of a directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": "Execute a shell command with arguments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute.",
                },
                "args": {
                    "type": "array",
                    "description": "List of arguments.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "mkdir",
        "description": "Create a directory tree.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to create.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "discover_tools",
        "description": "Discover all available tools in this environment.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "check_command",
        "description": "Check whether a command is available.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to check.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "stat",
        "description": "Return file or directory metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to inspect.",
                },
            },
            "required": ["path"],
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_result(value: Any) -> Any:
    """Convert dataclass instances to plain dicts for JSON serialization."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        result = dataclasses.asdict(value)
        # Remove None values for cleaner output
        return {k: v for k, v in result.items() if v is not None}
    if isinstance(value, dict):
        return {k: _normalize_result(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_result(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# EnvironmentAgent
# ---------------------------------------------------------------------------

class EnvironmentAgent:
    """MCP-compatible environment agent.

    The agent is the engine's sole interface to a target environment.
    All observation and execution flows through it.
    """

    def __init__(
        self,
        transport: BaseTransport | None = None,
        shell_driver: BaseDriver | None = None,
        fs_driver: BaseDriver | None = None,
        workdir: str = ".",
        toolkits: list[BaseToolkit] | None = None,
        security_auditor: Any | None = None,
        tool_registry: Any | None = None,
    ) -> None:
        self._transport = transport
        self._shell_driver = shell_driver
        self._fs_driver = fs_driver
        self._workdir = workdir
        self._toolkits: list[BaseToolkit] = list(toolkits) if toolkits else []
        self._security_auditor = security_auditor
        self._tool_registry = tool_registry
        self._running = False

        # In-process transport needs a reference to this agent
        if isinstance(self._transport, InProcessTransport):
            # Re-create with this agent instance
            self._transport = InProcessTransport(self)

        # Map tool name -> (toolkit, tool_definition) for routing
        self._tool_routes: dict[str, tuple[BaseToolkit, Any]] = {}
        for toolkit in self._toolkits:
            for tool in toolkit.get_tools():
                self._tool_routes[tool.name] = (toolkit, tool)

    # -- factory methods -----------------------------------------------------

    @classmethod
    def in_process(
        cls,
        workdir: str = ".",
        toolkits: list[BaseToolkit] | None = None,
        security_auditor: Any | None = None,
        tool_registry: Any | None = None,
    ) -> "EnvironmentAgent":
        """Create an in-process agent for local development.

        Uses direct Python function calls with no serialization overhead.
        """
        shell_driver = ShellDriver(cwd=workdir)
        fs_driver = FilesystemDriver(base_path=workdir)
        agent = cls(
            transport=None,
            shell_driver=shell_driver,
            fs_driver=fs_driver,
            workdir=workdir,
            toolkits=toolkits,
            security_auditor=security_auditor,
            tool_registry=tool_registry,
        )
        # Create transport after agent exists
        agent._transport = InProcessTransport(agent)
        return agent

    @classmethod
    def remote(
        cls,
        url: str,
        auth_token: str | None = None,
    ) -> "EnvironmentAgent":
        """Create an agent that connects to a remote agent via WebSocket."""
        from celeste.core.agent.transport_ws import WebSocketTransport

        transport = WebSocketTransport(url, auth_token=auth_token)
        agent = cls(transport=transport, workdir=".")
        return agent

    @classmethod
    def serve(
        cls,
        host: str,
        port: int,
        workdir: str = ".",
        toolkits: list[BaseToolkit] | None = None,
        auth_token: str | None = None,
    ) -> "EnvironmentAgent":
        """Create an agent that runs as a standalone WebSocket server."""
        from celeste.core.agent.transport_ws import WebSocketServer

        agent = cls(
            transport=None,
            shell_driver=ShellDriver(cwd=workdir),
            fs_driver=FilesystemDriver(base_path=workdir),
            workdir=workdir,
            toolkits=toolkits,
        )
        agent._server = WebSocketServer(
            host=host, port=port, agent=agent, auth_token=auth_token
        )
        return agent

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Start the agent. In-process: no-op. Remote: start connection. Serve: start server."""
        if self._transport is not None and hasattr(self._transport, "connect"):
            await self._transport.connect()
        if hasattr(self, "_server") and self._server is not None:
            await self._server.start()
        self._running = True

    async def stop(self) -> None:
        """Stop the agent gracefully."""
        if self._transport is not None:
            await self._transport.close()
        if hasattr(self, "_server") and self._server is not None:
            await self._server.stop()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    # -- public API ----------------------------------------------------------

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool on the agent.

        Security pipeline:
        1. Engine-side SecurityAuditor validates the tool call.
        2. ToolRegistry allowlist check.
        3. Route to built-in or toolkit implementation.
        4. Apply timeout.
        """
        args = arguments or {}

        # 1. Security audit (engine-side)
        if self._security_auditor is not None and name == "run_command":
            command_str = args.get("command", "")
            args_list = args.get("args", []) or []
            full_command = command_str + " " + " ".join(str(a) for a in args_list)
            verdict = await self._security_auditor.audit_command(full_command)
            if not verdict.is_safe:
                return {
                    "error": "security_audit_failed",
                    "reason": getattr(verdict, "reason", "blocked by security auditor"),
                }

        # 2. ToolRegistry allowlist check
        if self._tool_registry is not None:
            if not self._tool_registry.is_tool_allowed(name):
                return {"error": "tool_not_allowed", "tool_name": name}

        # 3. Route to implementation
        try:
            if timeout_ms is not None:
                result = await asyncio.wait_for(
                    self._execute_tool(name, args),
                    timeout=timeout_ms / 1000.0,
                )
            else:
                result = await self._execute_tool(name, args)
        except asyncio.TimeoutError:
            return {"error": "tool_timeout", "timeout_ms": timeout_ms}

        return _normalize_result(result)

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover available tools (built-in + registered toolkit tools)."""
        tools: list[dict[str, Any]] = []

        # Built-in tools
        tools.extend(_BUILTIN_TOOLS)

        # Toolkit tools
        for toolkit in self._toolkits:
            tools.extend(toolkit.to_mcp_schemas())

        return tools

    def register_toolkit(self, toolkit: BaseToolkit) -> None:
        """Register additional tools from a toolkit."""
        self._toolkits.append(toolkit)
        for tool in toolkit.get_tools():
            self._tool_routes[tool.name] = (toolkit, tool)

    # -- internal handlers (called by InProcessTransport) --------------------

    async def _handle_call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle a call_tool request from the transport layer."""
        name = params.get("name", "")
        args = params.get("args", {})
        timeout = params.get("timeout_ms")
        return await self.call_tool(name, args, timeout_ms=timeout)

    async def _handle_list_tools(self) -> list[dict[str, Any]]:
        """Handle a list_tools request from the transport layer."""
        return await self.list_tools()

    # -- tool execution ------------------------------------------------------

    async def _execute_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Any:
        """Execute a built-in tool or route to a toolkit."""
        # Built-in tools
        if name == "snapshot":
            return await self._builtin_snapshot(arguments)
        if name == "list_directory":
            return await self._builtin_list_directory(arguments)
        if name == "read_file":
            return await self._builtin_read_file(arguments)
        if name == "run_command":
            return await self._builtin_run_command(arguments)
        if name == "write_file":
            return await self._builtin_write_file(arguments)
        if name == "delete_file":
            return await self._builtin_delete_file(arguments)
        if name == "mkdir":
            return await self._builtin_mkdir(arguments)
        if name == "discover_tools":
            return await self.list_tools()
        if name == "check_command":
            return await self._builtin_check_command(arguments)
        if name == "stat":
            return await self._builtin_stat(arguments)

        # Toolkit tools
        route = self._tool_routes.get(name)
        if route is not None:
            toolkit, _ = route
            # Prefer fs_driver for file ops, shell_driver for commands
            driver = self._fs_driver or self._shell_driver
            return await toolkit.execute(name, arguments, driver)

        return {"error": "tool_not_found", "tool_name": name}

    # -- built-in implementations --------------------------------------------

    async def _builtin_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        paths = arguments.get("paths", [self._workdir])
        files: dict[str, Any] = {}
        driver = self._fs_driver or self._shell_driver
        if driver is not None:
            for p in paths:
                try:
                    result = await driver.list_directory(p)
                    files[p] = result.files if hasattr(result, "files") else result.get("files", [])
                except Exception:
                    files[p] = []
        return {"files": files, "platform": sys.platform}

    async def _builtin_list_directory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path", self._workdir)
        driver = self._fs_driver or self._shell_driver
        if driver is None:
            return {"error": "no_driver"}
        return await driver.list_directory(path)

    async def _builtin_read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path", "")
        driver = self._fs_driver or self._shell_driver
        if driver is None:
            return {"error": "no_driver"}
        return await driver.read_file(path)

    async def _builtin_run_command(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = arguments.get("command", "")
        args = arguments.get("args", []) or []
        cwd = arguments.get("cwd", self._workdir)
        timeout = arguments.get("timeout")
        driver = self._shell_driver
        if driver is None:
            return {"error": "no_driver"}
        result = await driver.run_command(command, args=args, cwd=cwd, timeout=timeout)
        # Detect process killed
        if hasattr(result, "killed_by_signal") and result.killed_by_signal is not None:
            return {
                "error": "process_killed",
                "signal": result.killed_by_signal,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        return result

    async def _builtin_write_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path", "")
        content = arguments.get("content", "")
        driver = self._fs_driver or self._shell_driver
        if driver is None:
            return {"error": "no_driver"}
        result = await driver.write_file(path, content)
        if hasattr(result, "content"):
            return {"success": True, "size": result.size}
        return result

    async def _builtin_delete_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path", "")
        driver = self._fs_driver or self._shell_driver
        if driver is None:
            return {"error": "no_driver"}
        await driver.delete_file(path)
        return {"success": True}

    async def _builtin_mkdir(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path", "")
        driver = self._fs_driver or self._shell_driver
        if driver is None:
            return {"error": "no_driver"}
        await driver.mkdir(path)
        return {"success": True}

    async def _builtin_check_command(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = arguments.get("command", "")
        driver = self._shell_driver
        if driver is None:
            return {"error": "no_driver"}
        try:
            result = await driver.run_command("which", args=[command])
            exit_code = result.exit_code if hasattr(result, "exit_code") else result.get("exit_code", -1)
            available = exit_code == 0
        except Exception:
            available = False
        return {"available": available}

    async def _builtin_stat(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path", "")
        driver = self._fs_driver or self._shell_driver
        if driver is None:
            return {"error": "no_driver"}
        return await driver.stat(path)
