"""
System Data Toolkit -- core file and data manipulation tools.

Provides tools for reading/writing files, listing directories, and
parsing/serialising structured data formats (CSV, JSON).
"""

from __future__ import annotations

from celeste_dag.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


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
