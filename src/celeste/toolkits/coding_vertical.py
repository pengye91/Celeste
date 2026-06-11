"""
Coding Vertical Toolkit -- software engineering tools.

Provides tools for git operations, test execution, linting, and
dependency management in software projects.
"""

from __future__ import annotations

from typing import Any

from celeste.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


class CodingVerticalToolkit(BaseToolkit):
    """Software engineering plugin for git, tests, and linting."""

    @property
    def name(self) -> str:
        return "coding_vertical"

    @property
    def description(self) -> str:
        return "Software engineering tools for git operations, testing, linting, and dependency management."

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    _TOOLS: list[ToolDefinition] = [
        ToolDefinition(
            name="git_status",
            description="Show the git working tree status for a repository.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Path to the git repository.",
                    required=True,
                ),
            ],
            returns="Git status output as a string.",
        ),
        ToolDefinition(
            name="git_diff",
            description="Show the git diff for a repository.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Path to the git repository.",
                    required=True,
                ),
                ToolParameter(
                    name="staged",
                    type="boolean",
                    description="Whether to show the staged diff instead of the working tree diff.",
                    required=False,
                    default=False,
                ),
            ],
            returns="Git diff output as a string.",
        ),
        ToolDefinition(
            name="run_tests",
            description="Run a test suite in the given project path.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Path to the project root.",
                    required=True,
                ),
                ToolParameter(
                    name="command",
                    type="string",
                    description="Test command to execute (e.g. 'pytest -v').",
                    required=True,
                ),
            ],
            returns="Test execution output as a string.",
        ),
        ToolDefinition(
            name="lint_code",
            description="Run a linter on the given project path.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Path to the project root.",
                    required=True,
                ),
                ToolParameter(
                    name="command",
                    type="string",
                    description="Linter command to execute (e.g. 'ruff check .').",
                    required=True,
                ),
            ],
            returns="Linter output as a string.",
        ),
        ToolDefinition(
            name="install_dependencies",
            description="Install project dependencies.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Path to the project root.",
                    required=True,
                ),
                ToolParameter(
                    name="command",
                    type="string",
                    description="Install command to execute (e.g. 'pip install -e .').",
                    required=True,
                ),
            ],
            returns="Installation output as a string.",
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
        """Execute a coding-vertical tool (stub implementation)."""
        known_tools = {
            "git_status",
            "git_diff",
            "run_tests",
            "lint_code",
            "install_dependencies",
        }
        if name in known_tools:
            return {"success": True}
        return {"error": "tool_not_found", "tool_name": name}
