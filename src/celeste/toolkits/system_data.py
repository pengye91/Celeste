"""
System Data Toolkit -- core file and data manipulation tools.

Provides tools for reading/writing files, listing directories, and
parsing/serialising structured data formats (CSV, JSON).
"""

from __future__ import annotations

import json
import os
import platform
from typing import Any

from celeste.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


class SystemDataToolkit(BaseToolkit):
    """Core data tools for file I/O and data format conversion."""

    @property
    def name(self) -> str:
        return "system_data"

    @property
    def description(self) -> str:
        return "Core file and data manipulation tools for reading, writing, and transforming structured data."

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    _TOOLS: list[ToolDefinition] = [
        ToolDefinition(
            name="read_file",
            description="Read the contents of a file at the given path.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Absolute or relative path to the file.",
                    required=True,
                ),
            ],
            returns="File contents as a string.",
        ),
        ToolDefinition(
            name="write_file",
            description="Write content to a file at the given path.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Absolute or relative path to the file.",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="Content to write to the file.",
                    required=True,
                ),
            ],
            returns="Confirmation message.",
        ),
        ToolDefinition(
            name="list_directory",
            description="List the contents of a directory.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Absolute or relative path to the directory.",
                    required=True,
                ),
                ToolParameter(
                    name="pattern",
                    type="string",
                    description="Glob pattern to filter results.",
                    required=False,
                    default="*",
                ),
            ],
            returns="List of file and directory names.",
        ),
        ToolDefinition(
            name="parse_csv",
            description="Parse a CSV file into structured records.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Absolute or relative path to the CSV file.",
                    required=True,
                ),
                ToolParameter(
                    name="delimiter",
                    type="string",
                    description="Field delimiter character.",
                    required=False,
                    default=",",
                ),
            ],
            returns="Array of records as objects.",
        ),
        ToolDefinition(
            name="to_json",
            description="Convert structured data to JSON and write to a file.",
            parameters=[
                ToolParameter(
                    name="data",
                    type="object",
                    description="Data to serialise as JSON.",
                    required=True,
                ),
                ToolParameter(
                    name="path",
                    type="string",
                    description="Destination file path.",
                    required=True,
                ),
            ],
            returns="Confirmation message.",
        ),
        ToolDefinition(
            name="parse_json",
            description="Read and parse a JSON file into structured data.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Absolute or relative path to the JSON file.",
                    required=True,
                ),
            ],
            returns="Parsed JSON data as an object.",
        ),
        ToolDefinition(
            name="snapshot",
            description="Walk directories and return a consolidated environment snapshot.",
            parameters=[
                ToolParameter(
                    name="paths",
                    type="array",
                    description="List of directory paths to include in the snapshot.",
                    required=False,
                ),
            ],
            returns="Dict with files map and platform info.",
        ),
        ToolDefinition(
            name="run_command",
            description="Execute a shell command with optional arguments, cwd, and timeout.",
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="The command to execute.",
                    required=True,
                ),
                ToolParameter(
                    name="args",
                    type="array",
                    description="List of arguments to pass to the command.",
                    required=False,
                ),
                ToolParameter(
                    name="cwd",
                    type="string",
                    description="Working directory for the command.",
                    required=False,
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Timeout in seconds.",
                    required=False,
                ),
            ],
            returns="Dict with exit_code, stdout, and stderr.",
        ),
        ToolDefinition(
            name="check_command",
            description="Check whether a command is available in the environment.",
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="The command to check for.",
                    required=True,
                ),
            ],
            returns="Dict with available boolean.",
        ),
        ToolDefinition(
            name="stat",
            description="Return file or directory metadata.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Path to the file or directory.",
                    required=True,
                ),
            ],
            returns="Dict with size, modified_time, and permissions.",
        ),
    ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        return list(self._TOOLS)

    def get_tool(self, name: str) -> ToolDefinition | None:
        for tool in self._TOOLS:
            if tool.name == name:
                return tool
        return None

    async def execute(
        self, name: str, arguments: dict[str, Any], driver: Any | None
    ) -> dict[str, Any]:
        """Execute a system-data tool via the provided driver."""
        if driver is None:
            return {"error": "driver_required", "message": "SystemDataToolkit requires a driver"}

        if name == "read_file":
            path = arguments.get("path", "")
            return await driver.read_file(path)

        if name == "list_directory":
            path = arguments.get("path", "")
            return await driver.list_directory(path)

        if name == "snapshot":
            paths = arguments.get("paths", ["."])
            files: dict[str, Any] = {}
            for p in paths:
                try:
                    result = await driver.list_directory(p)
                    files[p] = result.get("files", [])
                except Exception:
                    files[p] = []
            return {"files": files, "platform": platform.system().lower()}

        if name == "run_command":
            command = arguments.get("command", "")
            args = arguments.get("args", []) or []
            cwd = arguments.get("cwd")
            timeout = arguments.get("timeout")
            return await driver.run_command(command, args=args, cwd=cwd, timeout=timeout)

        if name == "check_command":
            command = arguments.get("command", "")
            try:
                result = await driver.run_command("which", args=[command])
                available = result.get("exit_code", -1) == 0
            except Exception:
                available = False
            return {"available": available}

        if name == "stat":
            path = arguments.get("path", "")
            return await driver.stat(path)

        if name == "write_file":
            path = arguments.get("path", "")
            content = arguments.get("content", "")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return {"success": True, "size": len(content)}
            except Exception as exc:
                return {"error": "write_failed", "message": str(exc)}

        if name == "parse_csv":
            path = arguments.get("path", "")
            delimiter = arguments.get("delimiter", ",")
            try:
                import csv

                with open(path, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    rows = list(reader)
                return {"rows": rows}
            except Exception as exc:
                return {"error": "parse_failed", "message": str(exc)}

        if name == "to_json":
            data = arguments.get("data", {})
            path = arguments.get("path", "")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                return {"success": True}
            except Exception as exc:
                return {"error": "write_failed", "message": str(exc)}

        if name == "parse_json":
            path = arguments.get("path", "")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {"data": data}
            except Exception as exc:
                return {"error": "parse_failed", "message": str(exc)}

        return {"error": "tool_not_found", "tool_name": name}
