"""
Tests for OPA planner preference of domain-specific toolkits over generic
system tools.

Symptom: in the second pharma run the planner chose SystemDataToolkit
(read_file, run_command) for 7 cycles instead of invoking any of the
pharma-specific tools (parse_telemetry, check_temperature_excursion,
check_import_rules, check_batch_gdp_compliance).

Root cause: the OPA system prompt lists available tools but does not
direct the model to prefer domain-specific toolkits. The fix is to:

1. Order domain-specific toolkits first in the rendered tools section.
2. Add an explicit directive in the OPA system prompt telling the model
   to prefer domain-specific toolkits when available.

These tests assert both behaviors at the prompt-rendering level (no live
LLM required).
"""

from __future__ import annotations

from typing import Any

import pytest

from celeste.core.llm.base import BaseLLMClient, LLMMessage, LLMResponse
from celeste.core.planner import _OPA_SYSTEM_PROMPT_TEMPLATE, Planner
from celeste.toolkits.base import (
    BaseToolkit,
    ToolDefinition,
    ToolParameter,
)


# ---------------------------------------------------------------------------
# Stub fixtures
# ---------------------------------------------------------------------------


class _StubLLMClient(BaseLLMClient):
    """Records structured_output calls and returns a trivial DAGFragment."""

    def __init__(self) -> None:
        self.structured_output_calls: list[dict[str, Any]] = []

    async def complete(self, messages, **kwargs) -> LLMResponse:
        return LLMResponse(content="{}", model="stub", usage={})

    async def structured_output(
        self, messages, response_model, **kwargs
    ) -> Any:
        from celeste.core.planner import DAGFragment

        self.structured_output_calls.append(
            {"messages": messages, "response_model": response_model}
        )
        return DAGFragment.model_construct(nodes=[], reasoning="stub")

    async def close(self) -> None:
        pass


class _DomainToolkit(BaseToolkit):
    """Stub domain toolkit (e.g. pharma_coldchain) with a couple of tools."""

    def __init__(self) -> None:
        self._tools = [
            ToolDefinition(
                name="check_temperature_excursion",
                description="Check whether a vaccine batch has experienced a temperature excursion.",
                parameters=[
                    ToolParameter(
                        name="batch_id",
                        type="string",
                        description="The batch identifier.",
                        required=True,
                    )
                ],
                returns="Dict with excursion status and details.",
            ),
            ToolDefinition(
                name="parse_telemetry",
                description="Parse an IoT telemetry payload and detect excursions.",
                parameters=[
                    ToolParameter(
                        name="payload",
                        type="object",
                        description="Telemetry payload dict.",
                        required=True,
                    )
                ],
                returns="Dict with parsed readings and any alerts.",
            ),
        ]

    @property
    def name(self) -> str:
        return "pharma_coldchain"

    @property
    def description(self) -> str:
        return "Pharma cold-chain tools."

    def get_tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    def get_tool(self, name: str) -> ToolDefinition | None:
        for t in self._tools:
            if t.name == name:
                return t
        return None

    async def execute(self, name: str, arguments: dict, driver: Any | None) -> dict:
        return {"success": True, "tool": name}


class _SystemDataToolkit(BaseToolkit):
    """Stub generic system toolkit (mirrors SystemDataToolkit.name)."""

    def __init__(self) -> None:
        self._tools = [
            ToolDefinition(
                name="read_file",
                description="Read the contents of a file at the given path.",
                parameters=[
                    ToolParameter(
                        name="path",
                        type="string",
                        description="Absolute or relative path to the file.",
                        required=True,
                    )
                ],
                returns="File contents as a string.",
            ),
            ToolDefinition(
                name="run_command",
                description="Execute a shell command with optional arguments.",
                parameters=[
                    ToolParameter(
                        name="command",
                        type="string",
                        description="The command to execute.",
                        required=True,
                    )
                ],
                returns="Dict with exit_code, stdout, stderr.",
            ),
        ]

    @property
    def name(self) -> str:
        return "system_data"

    @property
    def description(self) -> str:
        return "Core file and data manipulation tools."

    def get_tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    def get_tool(self, name: str) -> ToolDefinition | None:
        for t in self._tools:
            if t.name == name:
                return t
        return None

    async def execute(self, name: str, arguments: dict, driver: Any | None) -> dict:
        return {"success": True, "tool": name}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOPASystemPromptPrefersDomainToolkits:
    """OPA system prompt should direct the model to prefer domain toolkits."""

    def test_opa_template_contains_domain_preference_directive(self):
        """The OPA prompt template must explicitly direct the model to prefer
        domain-specific toolkits when they are available."""
        prompt = _OPA_SYSTEM_PROMPT_TEMPLATE
        # Lowercased for case-insensitive containment.
        lowered = prompt.lower()
        assert "domain" in lowered, (
            "OPA system prompt must mention 'domain' toolkits"
        )
        # Must explicitly express preference for domain over generic.
        assert "prefer" in lowered, (
            "OPA system prompt must direct the model to prefer domain toolkits"
        )

    def test_opa_template_names_system_data_as_generic(self):
        """The directive must point at the system_data toolkit as the generic
        baseline, so the prompt is actionable rather than abstract."""
        prompt = _OPA_SYSTEM_PROMPT_TEMPLATE
        assert "system_data" in prompt, (
            "OPA system prompt should name the system_data toolkit as the "
            "generic baseline"
        )


class TestPlannerRendersDomainToolkitFirst:
    """The rendered tools section must list domain toolkits before generic."""

    def test_domain_toolkit_appears_before_system_data(self):
        """The rendered section must list at least one domain tool before
        the first generic ``system_data`` tool (read_file)."""
        planner = Planner(
            _StubLLMClient(),
            toolkits=[_SystemDataToolkit(), _DomainToolkit()],
        )
        section = planner._build_tools_section()
        # Use specific tool names since the rendered section lists tools
        # (not toolkit names).
        domain_idx = section.find("check_temperature_excursion")
        system_idx = section.find("read_file")
        assert domain_idx != -1, "domain tool should appear in tools section"
        assert system_idx != -1, "system_data tool should appear in tools section"
        assert domain_idx < system_idx, (
            f"domain tool must be listed before system_data tool in the "
            f"tools section (domain_idx={domain_idx}, system_idx={system_idx})"
        )

    def test_domain_tool_tool_appears_before_system_tool(self):
        """A specific domain tool (e.g. check_temperature_excursion) must be
        listed in the tools section before a generic one (e.g. read_file)."""
        planner = Planner(
            _StubLLMClient(),
            toolkits=[_SystemDataToolkit(), _DomainToolkit()],
        )
        section = planner._build_tools_section()
        domain_tool_idx = section.find("check_temperature_excursion")
        system_tool_idx = section.find("read_file")
        assert domain_tool_idx != -1
        assert system_tool_idx != -1
        assert domain_tool_idx < system_tool_idx, (
            "domain tool should appear before generic tool in tools section"
        )


class TestPlannerPlanCallIncludesDomainDirective:
    """plan() must produce a system prompt with the directive and the
    domain toolkit listed before the generic one."""

    @pytest.mark.asyncio()
    async def test_plan_system_prompt_contains_directive_and_order(self):
        client = _StubLLMClient()
        planner = Planner(
            client,
            toolkits=[_SystemDataToolkit(), _DomainToolkit()],
        )
        await planner.plan(goal="Resolve cold-chain excursion for batch B-42")

        assert len(client.structured_output_calls) == 1
        call = client.structured_output_calls[0]
        messages = call["messages"]
        system_msg = next(m for m in messages if m.role == "system")
        content = system_msg.content
        lowered = content.lower()
        # The directive must be present in the rendered system message.
        assert "domain" in lowered
        assert "prefer" in lowered
        # The system_data toolkit is named as the generic baseline.
        assert "system_data" in content
        # The domain tool must appear before the generic tool in the
        # rendered available-tools list.
        domain_idx = content.find("check_temperature_excursion")
        system_idx = content.find("read_file")
        assert domain_idx != -1 and system_idx != -1
        assert domain_idx < system_idx, (
            "domain tool must be listed before read_file in the "
            "rendered OPA system prompt"
        )
