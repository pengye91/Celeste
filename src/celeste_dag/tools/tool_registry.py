"""
Strict deterministic allowlist for tool execution.

Translates registered tools into MCP tool schemas and validates that
commands use only allowed binaries.
"""

from __future__ import annotations

import os

from celeste_dag.toolkits.base import BaseToolkit, ToolDefinition


class ToolRegistry:
    """Strict deterministic allowlist for tool execution.

    Maintains two registries:
    - **Tools** -- registered from :class:`BaseToolkit` instances.  Each tool
      has a name, description, and MCP-compatible schema.
    - **Commands** -- registered binary names mapped to their absolute paths.
      Used to validate that shell commands only invoke allowed binaries.
    """

    def __init__(self) -> None:
        self._allowed_tools: dict[str, ToolDefinition] = {}
        self._allowed_commands: dict[str, str] = {}  # command_name -> binary_path

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_toolkit(self, toolkit: BaseToolkit) -> None:
        """Register all tools from a toolkit."""
        for tool in toolkit.get_tools():
            self._allowed_tools[tool.name] = tool

    def register_command(self, name: str, binary_path: str) -> None:
        """Register an allowed command binary."""
        self._allowed_commands[name] = binary_path

    # ------------------------------------------------------------------
    # Tool allowlist
    # ------------------------------------------------------------------

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is in the allowlist."""
        return tool_name in self._allowed_tools

    def get_tool_schema(self, tool_name: str) -> dict | None:
        """Get MCP schema for a tool, or ``None`` if not allowed."""
        tool = self._allowed_tools.get(tool_name)
        if tool is None:
            return None
        return tool.to_mcp_schema()

    def get_all_schemas(self) -> list[dict]:
        """Get MCP schemas for all registered tools."""
        return [tool.to_mcp_schema() for tool in self._allowed_tools.values()]

    # ------------------------------------------------------------------
    # Command validation
    # ------------------------------------------------------------------

    def validate_command(self, command: str) -> bool:
        """Validate that a command uses only allowed binaries.

        Extracts the leading binary name (first whitespace-delimited token)
        from *command* and checks it against the registered commands.
        If the token is an absolute path, only the final path component
        (the binary name) is checked.
        """
        if not command or not command.strip():
            return False

        # Extract the first token (the binary / command name)
        first_token = command.strip().split()[0]

        # If it's an absolute path, extract just the binary name
        if "/" in first_token:
            binary_name = os.path.basename(first_token)
        else:
            binary_name = first_token

        return binary_name in self._allowed_commands
