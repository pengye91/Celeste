"""
Pluggable toolkit interface for domain tool registries.

Defines ToolParameter, ToolDefinition (MCP-compatible), and the abstract
BaseToolkit that concrete toolkits must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from celeste.core.agent.driver import BaseDriver


# Type alias for valid JSON Schema types accepted as parameter types.
_VALID_PARAM_TYPES = {"string", "integer", "boolean", "array", "object"}


@dataclass(frozen=True)
class ToolParameter:
    """Describes a single tool parameter.

    Attributes:
        name: Parameter identifier.
        type: JSON Schema type -- one of "string", "integer", "boolean",
              "array", "object".
        description: Human-readable explanation of the parameter.
        required: Whether this parameter must be provided.  Defaults to True.
        default: Default value used when the parameter is omitted.
        enum: Optional list of allowed values.
    """

    name: str
    type: str
    description: str
    required: bool = True
    default: Any | None = None
    enum: list[str] | None = None

    def __post_init__(self) -> None:
        if self.type not in _VALID_PARAM_TYPES:
            raise ValueError(
                f"Invalid parameter type '{self.type}'. "
                f"Must be one of {sorted(_VALID_PARAM_TYPES)}"
            )

    def to_property_schema(self) -> dict[str, Any]:
        """Convert to a JSON Schema property dict for MCP inputSchema."""
        prop: dict[str, Any] = {
            "type": self.type,
            "description": self.description,
        }
        if self.default is not None:
            prop["default"] = self.default
        if self.enum is not None:
            prop["enum"] = self.enum
        return prop


@dataclass(frozen=True)
class ToolDefinition:
    """MCP-compatible tool schema.

    Attributes:
        name: Tool identifier (unique within a toolkit).
        description: Human-readable description of what the tool does.
        parameters: Ordered list of parameter definitions.
        returns: Description of the tool's return value.
    """

    name: str
    description: str
    parameters: list[ToolParameter]
    returns: str

    def to_mcp_schema(self) -> dict[str, Any]:
        """Convert to Model Context Protocol tool schema format.

        Returns a dict matching the MCP specification::

            {
                "name": ...,
                "description": ...,
                "inputSchema": {
                    "type": "object",
                    "properties": { ... },
                    "required": [ ... ],
                },
            }
        """
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in self.parameters:
            properties[param.name] = param.to_property_schema()
            if param.required:
                required.append(param.name)

        input_schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            input_schema["required"] = required
        else:
            input_schema["required"] = []

        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": input_schema,
        }


class BaseToolkit(ABC):
    """Abstract interface for pluggable domain tool registries.

    Concrete toolkits must implement the ``name``, ``description``,
    ``get_tools``, and ``get_tool`` members.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Toolkit name identifier."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable toolkit description."""

    @abstractmethod
    def get_tools(self) -> list[ToolDefinition]:
        """Return all tools registered in this toolkit."""

    @abstractmethod
    def get_tool(self, name: str) -> ToolDefinition | None:
        """Look up a specific tool by name."""

    @abstractmethod
    async def execute(
        self, name: str, arguments: dict[str, Any], driver: "BaseDriver" | None
    ) -> dict[str, Any]:
        """Execute a tool by name with the given arguments via a driver.

        Args:
            name: Tool identifier (must match a tool registered in this toolkit).
            arguments: Tool-specific arguments parsed from the LLM output.
            driver: Environment driver providing filesystem, shell, and HTTP
                operations.  May be ``None`` for tools that do not need a driver.

        Returns:
            A dict with the tool's result.  On error, returns a dict with an
            ``"error"`` key describing the failure.
        """

    def to_mcp_schemas(self) -> list[dict[str, Any]]:
        """Convert all tools to MCP schemas.

        Each schema is augmented with a ``_toolkit`` key carrying the toolkit
        name so callers can group or filter tools by their source registry.
        """
        out: list[dict[str, Any]] = []
        for tool in self.get_tools():
            schema = tool.to_mcp_schema()
            schema["_toolkit"] = self.name
            out.append(schema)
        return out
