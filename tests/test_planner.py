"""
Tests for the DAG planner with fan-out and Saga patterns (Tasks 4.1-4.3)
and OPA Loop planner updates.

Follows strict TDD: these tests are written BEFORE the implementation.
Covers:
- DAGNode model creation, validation, and defaults
- DAGPlan model creation, validation, and defaults
- Planner.get_available_tools() returns MCP schemas from toolkits
- Planner.plan() calls LLM with structured output (mocked)
- Planner.register_toolkit() adds tools dynamically
- Fan-out node generation: correct names, dependencies, argument injection
- Fan-out max_parallel safety limit
- SagaStep and SagaPlan models
- SagaPlan.get_compensations() returns reversed completed steps
- extract_saga_plan() extracts from DAGPlan
- Edge cases: empty plans, single node, large fan-out
- OPA Loop: DAGFragment, new plan() signature, timeout handling
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from celeste_dag.core.llm.base import BaseLLMClient, LLMMessage, LLMResponse
from celeste_dag.toolkits.base import (
    BaseToolkit,
    ToolDefinition,
    ToolParameter,
)


# ---------------------------------------------------------------------------
# Helpers -- concrete test doubles for abstract base classes
# ---------------------------------------------------------------------------


class _StubLLMClient(BaseLLMClient):
    """Concrete LLM client that records calls and returns canned responses."""

    def __init__(self) -> None:
        self.complete_calls: list[dict[str, Any]] = []
        self.structured_output_calls: list[dict[str, Any]] = []
        self._structured_side_effect: Any = None

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        self.complete_calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": tools,
            }
        )
        return LLMResponse(
            content='{"name": "test_plan", "nodes": []}',
            model="stub",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    async def structured_output(
        self,
        messages: list[LLMMessage],
        response_model: type,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        self.structured_output_calls.append(
            {
                "messages": messages,
                "response_model": response_model,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self._structured_side_effect is not None:
            return self._structured_side_effect
        # Default: return a minimal valid instance of the response_model
        return response_model.model_construct(name="auto_plan", nodes=[])

    async def close(self) -> None:
        pass


class _StubToolkit(BaseToolkit):
    """Minimal concrete toolkit for testing."""

    def __init__(self, tools: list[ToolDefinition] | None = None) -> None:
        self._tools = tools or [
            ToolDefinition(
                name="stub_tool",
                description="A stub tool",
                parameters=[
                    ToolParameter(name="input", type="string", description="Input"),
                ],
                returns="string",
            )
        ]

    @property
    def name(self) -> str:
        return "stub_toolkit"

    @property
    def description(self) -> str:
        return "A stub toolkit for tests"

    def get_tools(self) -> list[ToolDefinition]:
        return self._tools

    def get_tool(self, name: str) -> ToolDefinition | None:
        for t in self._tools:
            if t.name == name:
                return t
        return None

    async def execute(self, name: str, arguments: dict, driver: Any | None) -> dict:
        return {"success": True}


# ===========================================================================
# DAGNode
# ===========================================================================


class TestDAGNode:
    """Tests for the DAGNode Pydantic model."""

    def test_create_minimal(self):
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(name="step_1", task_type="llm_call", command="summarize")
        assert node.name == "step_1"
        assert node.task_type == "llm_call"
        assert node.command == "summarize"
        assert node.arguments == {}
        assert node.dependencies == []
        assert node.compensation_command is None
        assert node.compensation_arguments is None

    def test_create_full(self):
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(
            name="write_file",
            task_type="tool_execution",
            command="write_file",
            arguments={"path": "/tmp/out.txt", "content": "hello"},
            dependencies=["step_1"],
            compensation_command="delete_file",
            compensation_arguments={"path": "/tmp/out.txt"},
        )
        assert node.name == "write_file"
        assert node.task_type == "tool_execution"
        assert node.command == "write_file"
        assert node.arguments == {"path": "/tmp/out.txt", "content": "hello"}
        assert node.dependencies == ["step_1"]
        assert node.compensation_command == "delete_file"
        assert node.compensation_arguments == {"path": "/tmp/out.txt"}

    def test_all_valid_task_types(self):
        from celeste_dag.core.planner import DAGNode

        valid_types = ["llm_call", "tool_execution", "fan_out", "map_reduce", "condition"]
        for t in valid_types:
            node = DAGNode(name="n", task_type=t, command="cmd")  # type: ignore[arg-type]
            assert node.task_type == t

    def test_invalid_task_type_rejected(self):
        from celeste_dag.core.planner import DAGNode

        with pytest.raises(Exception):
            DAGNode(name="n", task_type="invalid_type", command="cmd")  # type: ignore[arg-type]

    def test_arguments_default_empty_dict(self):
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(name="n", task_type="llm_call", command="c")
        assert node.arguments == {}

    def test_dependencies_default_empty_list(self):
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(name="n", task_type="llm_call", command="c")
        assert node.dependencies == []

    def test_compensation_fields_optional(self):
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(name="n", task_type="llm_call", command="c")
        assert node.compensation_command is None
        assert node.compensation_arguments is None

    def test_multiple_dependencies(self):
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(
            name="merge",
            task_type="llm_call",
            command="merge_results",
            dependencies=["step_a", "step_b", "step_c"],
        )
        assert node.dependencies == ["step_a", "step_b", "step_c"]

    def test_model_dump(self):
        """Ensure Pydantic model_dump produces a serialisable dict."""
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(name="n", task_type="llm_call", command="c")
        d = node.model_dump()
        assert isinstance(d, dict)
        assert d["name"] == "n"
        json_str = json.dumps(d)  # must be JSON-serialisable
        assert "n" in json_str

    def test_dag_node_merged_model(self):
        """DAGNode has optional task_id, preconditions, postconditions fields."""
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(
            name="step_1",
            task_type="llm_call",
            command="summarize",
            task_id="custom_id",
            preconditions=["data_ready"],
            postconditions=["summary_done"],
        )
        assert node.name == "step_1"
        assert node.task_id == "custom_id"
        assert node.preconditions == ["data_ready"]
        assert node.postconditions == ["summary_done"]

    def test_dag_node_task_id_defaults_to_name(self):
        """When task_id is not provided, it defaults to name."""
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(name="step_1", task_type="llm_call", command="summarize")
        assert node.task_id == "step_1"

    def test_dag_node_preconditions_postconditions_default_none(self):
        """When preconditions/postconditions are not provided, they default to None."""
        from celeste_dag.core.planner import DAGNode

        node = DAGNode(name="step_1", task_type="llm_call", command="summarize")
        assert node.preconditions is None
        assert node.postconditions is None


# ===========================================================================
# DAGPlan
# ===========================================================================


class TestDAGPlan:
    """Tests for the DAGPlan Pydantic model."""

    def test_create_minimal(self):
        from celeste_dag.core.planner import DAGPlan

        plan = DAGPlan(name="my_plan", nodes=[])
        assert plan.name == "my_plan"
        assert plan.description == ""
        assert plan.nodes == []
        assert plan.variables == {}

    def test_create_full(self):
        from celeste_dag.core.planner import DAGNode, DAGPlan

        nodes = [
            DAGNode(name="step_1", task_type="llm_call", command="analyze"),
            DAGNode(
                name="step_2",
                task_type="tool_execution",
                command="write_report",
                dependencies=["step_1"],
            ),
        ]
        plan = DAGPlan(
            name="analysis",
            description="An analysis pipeline",
            nodes=nodes,
            variables={"target": "sales_data"},
        )
        assert plan.name == "analysis"
        assert plan.description == "An analysis pipeline"
        assert len(plan.nodes) == 2
        assert plan.variables == {"target": "sales_data"}

    def test_description_default_empty(self):
        from celeste_dag.core.planner import DAGPlan

        plan = DAGPlan(name="p", nodes=[])
        assert plan.description == ""

    def test_variables_default_empty_dict(self):
        from celeste_dag.core.planner import DAGPlan

        plan = DAGPlan(name="p", nodes=[])
        assert plan.variables == {}

    def test_model_dump_roundtrip(self):
        from celeste_dag.core.planner import DAGNode, DAGPlan

        nodes = [DAGNode(name="s1", task_type="llm_call", command="c")]
        plan = DAGPlan(name="p", nodes=nodes, variables={"k": "v"})
        d = plan.model_dump()
        json_str = json.dumps(d)
        plan2 = DAGPlan.model_validate_json(json_str)
        assert plan2.name == plan.name
        assert len(plan2.nodes) == 1

    def test_single_node_plan(self):
        from celeste_dag.core.planner import DAGNode, DAGPlan

        node = DAGNode(name="only", task_type="llm_call", command="echo")
        plan = DAGPlan(name="single", nodes=[node])
        assert len(plan.nodes) == 1
        assert plan.nodes[0].name == "only"


# ===========================================================================
# Planner (Task 4.1)
# ===========================================================================


class TestPlanner:
    """Tests for the Planner class."""

    def test_init_with_client_only(self):
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        planner = Planner(client)
        assert planner._client is client
        assert planner._toolkits == []

    def test_init_with_toolkits(self):
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        tk1 = _StubToolkit()
        tk2 = _StubToolkit()
        planner = Planner(client, toolkits=[tk1, tk2])
        assert len(planner._toolkits) == 2

    def test_get_available_tools_no_toolkits(self):
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        planner = Planner(client)
        assert planner.get_available_tools() == []

    def test_get_available_tools_with_toolkits(self):
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        tk = _StubToolkit()
        planner = Planner(client, toolkits=[tk])
        tools = planner.get_available_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "stub_tool"

    def test_get_available_tools_multiple_toolkits(self):
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        tk1 = _StubToolkit(
            tools=[
                ToolDefinition(
                    name="t1", description="T1", parameters=[], returns="str"
                )
            ]
        )
        tk2 = _StubToolkit(
            tools=[
                ToolDefinition(
                    name="t2", description="T2", parameters=[], returns="str"
                )
            ]
        )
        planner = Planner(client, toolkits=[tk1, tk2])
        tools = planner.get_available_tools()
        assert len(tools) == 2
        assert tools[0]["name"] == "t1"
        assert tools[1]["name"] == "t2"

    def test_get_available_tools_returns_mcp_schema_format(self):
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        planner = Planner(client, toolkits=[_StubToolkit()])
        tools = planner.get_available_tools()
        for schema in tools:
            assert "name" in schema
            assert "description" in schema
            assert "inputSchema" in schema

    def test_register_toolkit(self):
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        planner = Planner(client)
        assert planner.get_available_tools() == []
        planner.register_toolkit(_StubToolkit())
        assert len(planner.get_available_tools()) == 1

    def test_register_toolkit_appends(self):
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        planner = Planner(client, toolkits=[_StubToolkit()])
        planner.register_toolkit(_StubToolkit())
        # Two toolkits, each with one tool
        assert len(planner.get_available_tools()) == 2

    @pytest.mark.asyncio()
    async def test_plan_calls_structured_output(self):
        """Planner.plan_full_dag() must call the LLM's structured_output with DAGPlan model."""
        from celeste_dag.core.planner import DAGNode, DAGPlan, Planner

        client = _StubLLMClient()
        expected_plan = DAGPlan(
            name="test_plan",
            description="A plan",
            nodes=[DAGNode(name="s1", task_type="llm_call", command="analyze")],
        )
        client._structured_side_effect = expected_plan

        planner = Planner(client)
        result = await planner.plan_full_dag("Analyze sales data")

        assert len(client.structured_output_calls) == 1
        call = client.structured_output_calls[0]
        assert call["response_model"] is DAGPlan
        # Messages should contain system and user messages
        messages = call["messages"]
        assert len(messages) >= 2
        assert messages[0].role == "system"
        assert messages[-1].role == "user"

    @pytest.mark.asyncio()
    async def test_plan_returns_dag_plan(self):
        from celeste_dag.core.planner import DAGNode, DAGPlan, Planner

        client = _StubLLMClient()
        expected = DAGPlan(
            name="plan",
            nodes=[DAGNode(name="s", task_type="llm_call", command="c")],
        )
        client._structured_side_effect = expected

        planner = Planner(client)
        result = await planner.plan_full_dag("Do something")
        assert isinstance(result, DAGPlan)
        assert result.name == "plan"

    @pytest.mark.asyncio()
    async def test_plan_passes_context_to_llm(self):
        """If context is provided, it should be reflected in the messages."""
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        planner = Planner(client)
        await planner.plan_full_dag("Analyze data", context={"project": "acme"})

        call = client.structured_output_calls[0]
        messages = call["messages"]
        # At least one message should reference the context or the user request
        all_content = " ".join(m.content for m in messages)
        assert "Analyze data" in all_content

    @pytest.mark.asyncio()
    async def test_plan_includes_tools_in_system_prompt(self):
        """When toolkits are registered, the system prompt should reference them."""
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        planner = Planner(client, toolkits=[_StubToolkit()])
        await planner.plan_full_dag("Use tools")

        call = client.structured_output_calls[0]
        system_msg = call["messages"][0]
        # The system prompt should mention the available tools
        assert "stub_tool" in system_msg.content or "tool" in system_msg.content.lower()

    @pytest.mark.asyncio()
    async def test_plan_uses_low_temperature(self):
        """Plan generation should use temperature=0 for deterministic output."""
        from celeste_dag.core.planner import Planner

        client = _StubLLMClient()
        planner = Planner(client)
        await planner.plan_full_dag("Test")

        call = client.structured_output_calls[0]
        assert call["temperature"] == 0.0

    @pytest.mark.asyncio()
    async def test_plan_full_dag_backward_compatible(self):
        """plan_full_dag() should still work with the old signature."""
        from celeste_dag.core.planner import DAGNode, DAGPlan, Planner

        client = _StubLLMClient()
        expected_plan = DAGPlan(
            name="test_plan",
            description="A plan",
            nodes=[DAGNode(name="s1", task_type="llm_call", command="analyze")],
        )
        client._structured_side_effect = expected_plan

        planner = Planner(client)
        result = await planner.plan_full_dag("Analyze sales data")

        assert isinstance(result, DAGPlan)
        assert result.name == "test_plan"
        assert len(client.structured_output_calls) == 1
        call = client.structured_output_calls[0]
        assert call["response_model"] is DAGPlan


# ===========================================================================
# OPA Loop Planner (new plan() signature)
# ===========================================================================


class _StubLLMClientFragment(BaseLLMClient):
    """LLM client that returns DAGFragment for OPA loop tests."""

    def __init__(self) -> None:
        self.complete_calls: list[dict[str, Any]] = []
        self.structured_output_calls: list[dict[str, Any]] = []
        self._structured_side_effect: Any = None

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        self.complete_calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": tools,
            }
        )
        return LLMResponse(
            content='{"nodes": [], "reasoning": "test"}',
            model="stub",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    async def structured_output(
        self,
        messages: list[LLMMessage],
        response_model: type,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        self.structured_output_calls.append(
            {
                "messages": messages,
                "response_model": response_model,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self._structured_side_effect is not None:
            return self._structured_side_effect
        from celeste_dag.core.planner import DAGFragment

        return DAGFragment.model_construct(nodes=[], reasoning="test")

    async def close(self) -> None:
        pass


class TestPlannerOPALoop:
    """Tests for the new OPA Loop Planner.plan() interface."""

    @pytest.mark.asyncio()
    async def test_planner_accepts_observation_context(self):
        """plan() accepts goal, observation, tool_schemas, and history."""
        from celeste_dag.core.planner import DAGFragment, Planner

        client = _StubLLMClientFragment()
        planner = Planner(client)

        observation = {"cwd": "/tmp", "files": ["a.txt"]}
        tool_schemas = [{"name": "read_file", "description": "Read a file"}]
        history = [{"action": "previous_step", "result": "ok"}]

        result = await planner.plan(
            goal="Read a file",
            observation=observation,
            tool_schemas=tool_schemas,
            history=history,
        )

        assert isinstance(result, DAGFragment)
        assert len(client.structured_output_calls) == 1
        call = client.structured_output_calls[0]
        messages = call["messages"]
        all_content = " ".join(m.content for m in messages)
        assert "Read a file" in all_content
        assert "/tmp" in all_content or "a.txt" in all_content
        assert "read_file" in all_content
        assert "previous_step" in all_content

    @pytest.mark.asyncio()
    async def test_planner_returns_dag_fragment(self):
        """plan() returns a DAGFragment with nodes, reasoning, etc."""
        from celeste_dag.core.planner import DAGFragment, DAGNode, Planner

        client = _StubLLMClientFragment()
        expected = DAGFragment(
            nodes=[
                DAGNode(
                    name="step_1",
                    task_type="tool_execution",
                    command="read_file",
                    arguments={"path": "/tmp/a.txt"},
                )
            ],
            reasoning="Need to read the file first.",
            estimated_remaining=2,
            goal_achieved=False,
        )
        client._structured_side_effect = expected

        planner = Planner(client)
        result = await planner.plan(goal="Read a file")

        assert isinstance(result, DAGFragment)
        assert result.reasoning == "Need to read the file first."
        assert result.estimated_remaining == 2
        assert result.goal_achieved is False
        assert len(result.nodes) == 1
        assert result.nodes[0].name == "step_1"

    @pytest.mark.asyncio()
    async def test_planner_timeout_raises_planner_timeout_error(self):
        """plan() wraps LLM call in asyncio.wait_for and raises PlannerTimeoutError."""
        import asyncio

        from celeste_dag.core.exceptions import PlannerTimeoutError
        from celeste_dag.core.planner import Planner

        class _SlowLLMClient(BaseLLMClient):
            async def complete(self, messages, **kwargs):
                await asyncio.sleep(10)
                return LLMResponse(
                    content="{}",
                    model="slow",
                    usage={},
                )

            async def close(self):
                pass

        client = _SlowLLMClient()
        planner = Planner(client)

        with pytest.raises(PlannerTimeoutError):
            await planner.plan(goal="Do something", timeout_ms=50)

    @pytest.mark.asyncio()
    async def test_planner_timeout_ms_default(self):
        """plan() should work with default timeout_ms."""
        from celeste_dag.core.planner import DAGFragment, Planner

        client = _StubLLMClientFragment()
        planner = Planner(client)
        result = await planner.plan(goal="Test")
        assert isinstance(result, DAGFragment)

    def test_dag_fragment_model(self):
        """DAGFragment model has the expected fields and defaults."""
        from celeste_dag.core.planner import DAGFragment, DAGNode

        fragment = DAGFragment(
            nodes=[DAGNode(name="n", task_type="llm_call", command="c")],
            reasoning="test reasoning",
            estimated_remaining=3,
            goal_achieved=True,
        )
        assert len(fragment.nodes) == 1
        assert fragment.reasoning == "test reasoning"
        assert fragment.estimated_remaining == 3
        assert fragment.goal_achieved is True

    def test_dag_fragment_defaults(self):
        """DAGFragment defaults for optional fields."""
        from celeste_dag.core.planner import DAGFragment

        fragment = DAGFragment(nodes=[], reasoning="done")
        assert fragment.estimated_remaining is None
        assert fragment.goal_achieved is False


# ===========================================================================
# Fan-Out Spec & Node Generation (Task 4.2)
# ===========================================================================


class TestFanOutSpec:
    """Tests for the FanOutSpec model."""

    def test_create_fan_out_spec(self):
        from celeste_dag.core.planner import DAGNode, FanOutSpec

        template = DAGNode(name="process", task_type="tool_execution", command="process_item")
        spec = FanOutSpec(
            source_node="split",
            template_node=template,
            max_parallel=5,
        )
        assert spec.source_node == "split"
        assert spec.template_node.name == "process"
        assert spec.max_parallel == 5

    def test_fan_out_spec_default_max_parallel(self):
        from celeste_dag.core.planner import DAGNode, FanOutSpec

        template = DAGNode(name="t", task_type="llm_call", command="c")
        spec = FanOutSpec(source_node="src", template_node=template)
        assert spec.max_parallel == 10


class TestGenerateFanOutNodes:
    """Tests for generate_fan_out_nodes()."""

    def test_basic_fan_out(self):
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(
            name="process_item",
            task_type="tool_execution",
            command="process",
            arguments={"item": None},
        )
        items = ["alpha", "beta", "gamma"]
        nodes = generate_fan_out_nodes("splitter", items, template)

        assert len(nodes) == 3
        assert nodes[0].name == "process_item_0"
        assert nodes[1].name == "process_item_1"
        assert nodes[2].name == "process_item_2"

    def test_fan_out_dependencies(self):
        """Each fan-out node must depend on the parent."""
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(name="w", task_type="tool_execution", command="work")
        nodes = generate_fan_out_nodes("parent", [1, 2], template)
        for node in nodes:
            assert "parent" in node.dependencies

    def test_fan_out_argument_injection(self):
        """Each node should have the current array element injected into arguments."""
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(
            name="proc",
            task_type="tool_execution",
            command="process",
            arguments={"item": None},
        )
        items = ["x", "y"]
        nodes = generate_fan_out_nodes("src", items, template)

        # The arguments should contain the injected item
        assert nodes[0].arguments.get("item") == "x"
        assert nodes[1].arguments.get("item") == "y"

    def test_fan_out_preserves_template_command(self):
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(name="p", task_type="tool_execution", command="my_command")
        nodes = generate_fan_out_nodes("s", [1], template)
        assert nodes[0].command == "my_command"

    def test_fan_out_preserves_task_type(self):
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(name="p", task_type="tool_execution", command="c")
        nodes = generate_fan_out_nodes("s", [1], template)
        assert nodes[0].task_type == "tool_execution"

    def test_fan_out_inherits_compensation(self):
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(
            name="p",
            task_type="tool_execution",
            command="create",
            compensation_command="delete",
            compensation_arguments={"cleanup": True},
        )
        nodes = generate_fan_out_nodes("s", [1], template)
        assert nodes[0].compensation_command == "delete"
        assert nodes[0].compensation_arguments == {"cleanup": True}

    def test_fan_out_empty_input(self):
        """Empty array produces no nodes."""
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(name="p", task_type="llm_call", command="c")
        nodes = generate_fan_out_nodes("s", [], template)
        assert nodes == []

    def test_fan_out_single_item(self):
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(name="p", task_type="llm_call", command="c")
        nodes = generate_fan_out_nodes("s", [42], template)
        assert len(nodes) == 1
        assert nodes[0].name == "p_0"

    def test_fan_out_max_parallel_limits_output(self):
        """When input exceeds max_parallel, output is capped."""
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(name="p", task_type="llm_call", command="c")
        items = list(range(100))
        nodes = generate_fan_out_nodes("s", items, template, max_parallel=5)
        assert len(nodes) == 5

    def test_fan_out_max_parallel_exact(self):
        """When input equals max_parallel, all items are included."""
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(name="p", task_type="llm_call", command="c")
        nodes = generate_fan_out_nodes("s", [1, 2, 3], template, max_parallel=3)
        assert len(nodes) == 3

    def test_fan_out_default_max_parallel(self):
        """Default max_parallel is 10."""
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(name="p", task_type="llm_call", command="c")
        items = list(range(20))
        nodes = generate_fan_out_nodes("s", items, template)
        assert len(nodes) == 10

    def test_fan_out_unique_names(self):
        """Each generated node must have a unique name."""
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(name="w", task_type="llm_call", command="c")
        nodes = generate_fan_out_nodes("s", list(range(10)), template)
        names = [n.name for n in nodes]
        assert len(names) == len(set(names))

    def test_fan_out_dict_items(self):
        """Fan-out should work with dict items as well as primitives."""
        from celeste_dag.core.planner import DAGNode, generate_fan_out_nodes

        template = DAGNode(
            name="proc",
            task_type="tool_execution",
            command="process",
            arguments={"item": None},
        )
        items = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        nodes = generate_fan_out_nodes("s", items, template)
        assert len(nodes) == 2
        assert nodes[0].arguments["item"] == {"id": 1, "name": "a"}
        assert nodes[1].arguments["item"] == {"id": 2, "name": "b"}


# ===========================================================================
# SagaStep & SagaPlan (Task 4.3)
# ===========================================================================


class TestSagaStep:
    """Tests for the SagaStep model."""

    def test_create_saga_step(self):
        from celeste_dag.core.planner import SagaStep

        step = SagaStep(
            node_name="write_db",
            action="insert_record",
            compensation="delete_record",
            compensation_arguments={"table": "users"},
        )
        assert step.node_name == "write_db"
        assert step.action == "insert_record"
        assert step.compensation == "delete_record"
        assert step.compensation_arguments == {"table": "users"}
        assert step.completed is False

    def test_saga_step_default_completed_false(self):
        from celeste_dag.core.planner import SagaStep

        step = SagaStep(
            node_name="n", action="a", compensation="c"
        )
        assert step.completed is False

    def test_saga_step_default_compensation_arguments_empty(self):
        from celeste_dag.core.planner import SagaStep

        step = SagaStep(node_name="n", action="a", compensation="c")
        assert step.compensation_arguments == {}

    def test_saga_step_completed_true(self):
        from celeste_dag.core.planner import SagaStep

        step = SagaStep(
            node_name="n", action="a", compensation="c", completed=True
        )
        assert step.completed is True


class TestSagaPlan:
    """Tests for the SagaPlan model and get_compensations()."""

    def _make_steps(self):
        from celeste_dag.core.planner import SagaStep

        return [
            SagaStep(
                node_name="step_1",
                action="create_user",
                compensation="delete_user",
                completed=True,
            ),
            SagaStep(
                node_name="step_2",
                action="send_email",
                compensation="recall_email",
                completed=True,
            ),
            SagaStep(
                node_name="step_3",
                action="charge_payment",
                compensation="refund_payment",
                completed=False,
            ),
        ]

    def test_create_saga_plan(self):
        from celeste_dag.core.planner import SagaPlan

        plan = SagaPlan(workflow_name="signup", steps=self._make_steps())
        assert plan.workflow_name == "signup"
        assert len(plan.steps) == 3

    def test_get_compensations_returns_reversed_completed(self):
        """Compensations are for completed steps before the failure, in reverse."""
        from celeste_dag.core.planner import SagaPlan

        plan = SagaPlan(workflow_name="signup", steps=self._make_steps())
        # Failure at index 2 (step_3)
        compensations = plan.get_compensations(failed_step_index=2)
        assert len(compensations) == 2
        # Reversed order: step_2 first, then step_1
        assert compensations[0].node_name == "step_2"
        assert compensations[1].node_name == "step_1"

    def test_get_compensations_failure_at_first_step(self):
        """No compensations if the first step fails."""
        from celeste_dag.core.planner import SagaPlan

        plan = SagaPlan(workflow_name="test", steps=self._make_steps())
        compensations = plan.get_compensations(failed_step_index=0)
        assert compensations == []

    def test_get_compensations_failure_at_second_step(self):
        """Only step_1 is compensated if step_2 fails."""
        from celeste_dag.core.planner import SagaPlan

        plan = SagaPlan(workflow_name="test", steps=self._make_steps())
        compensations = plan.get_compensations(failed_step_index=1)
        assert len(compensations) == 1
        assert compensations[0].node_name == "step_1"

    def test_get_compensations_skips_uncompleted_steps(self):
        """Only completed steps before failure should be compensated."""
        from celeste_dag.core.planner import SagaPlan, SagaStep

        steps = [
            SagaStep(node_name="s1", action="a", compensation="c", completed=True),
            SagaStep(node_name="s2", action="a", compensation="c", completed=False),
            SagaStep(node_name="s3", action="a", compensation="c", completed=True),
        ]
        plan = SagaPlan(workflow_name="test", steps=steps)
        # Failure at index 3: s1 and s3 are completed, s2 is not
        compensations = plan.get_compensations(failed_step_index=3)
        # s2 was not completed, so only s3 and s1 should be compensated (reversed)
        assert len(compensations) == 2
        assert compensations[0].node_name == "s3"
        assert compensations[1].node_name == "s1"

    def test_get_compensations_all_completed_before_failure(self):
        from celeste_dag.core.planner import SagaPlan, SagaStep

        steps = [
            SagaStep(node_name="a", action="a", compensation="ca", completed=True),
            SagaStep(node_name="b", action="b", compensation="cb", completed=True),
            SagaStep(node_name="c", action="c", compensation="cc", completed=True),
        ]
        plan = SagaPlan(workflow_name="test", steps=steps)
        compensations = plan.get_compensations(failed_step_index=3)
        assert len(compensations) == 3
        assert compensations[0].node_name == "c"
        assert compensations[1].node_name == "b"
        assert compensations[2].node_name == "a"


class TestExtractSagaPlan:
    """Tests for extract_saga_plan() function."""

    def test_extract_from_dag_plan(self):
        from celeste_dag.core.planner import (
            DAGNode,
            DAGPlan,
            extract_saga_plan,
        )

        plan = DAGPlan(
            name="workflow",
            nodes=[
                DAGNode(
                    name="create_user",
                    task_type="tool_execution",
                    command="create_user",
                    compensation_command="delete_user",
                    compensation_arguments={"cascade": True},
                ),
                DAGNode(
                    name="send_email",
                    task_type="tool_execution",
                    command="send_email",
                    compensation_command="recall_email",
                ),
                DAGNode(
                    name="log_action",
                    task_type="tool_execution",
                    command="log",
                ),
            ],
        )
        saga = extract_saga_plan(plan)
        assert saga.workflow_name == "workflow"
        assert len(saga.steps) == 3

    def test_extract_saga_step_fields(self):
        from celeste_dag.core.planner import (
            DAGNode,
            DAGPlan,
            extract_saga_plan,
        )

        plan = DAGPlan(
            name="test",
            nodes=[
                DAGNode(
                    name="create",
                    task_type="tool_execution",
                    command="insert_db",
                    compensation_command="delete_db",
                    compensation_arguments={"table": "orders"},
                ),
            ],
        )
        saga = extract_saga_plan(plan)
        step = saga.steps[0]
        assert step.node_name == "create"
        assert step.action == "insert_db"
        assert step.compensation == "delete_db"
        assert step.compensation_arguments == {"table": "orders"}
        assert step.completed is False

    def test_extract_saga_no_compensation(self):
        """Nodes without compensation_command get empty compensation string."""
        from celeste_dag.core.planner import (
            DAGNode,
            DAGPlan,
            extract_saga_plan,
        )

        plan = DAGPlan(
            name="test",
            nodes=[
                DAGNode(name="readonly", task_type="llm_call", command="analyze"),
            ],
        )
        saga = extract_saga_plan(plan)
        step = saga.steps[0]
        assert step.compensation == ""

    def test_extract_saga_empty_plan(self):
        from celeste_dag.core.planner import DAGPlan, extract_saga_plan

        plan = DAGPlan(name="empty", nodes=[])
        saga = extract_saga_plan(plan)
        assert saga.workflow_name == "empty"
        assert saga.steps == []

    def test_extract_saga_preserves_order(self):
        """Steps should be in the same order as DAG nodes."""
        from celeste_dag.core.planner import (
            DAGNode,
            DAGPlan,
            extract_saga_plan,
        )

        plan = DAGPlan(
            name="test",
            nodes=[
                DAGNode(name="a", task_type="llm_call", command="a"),
                DAGNode(name="b", task_type="llm_call", command="b"),
                DAGNode(name="c", task_type="llm_call", command="c"),
            ],
        )
        saga = extract_saga_plan(plan)
        assert [s.node_name for s in saga.steps] == ["a", "b", "c"]

    def test_extract_saga_default_compensation_arguments(self):
        """When compensation_command exists but no compensation_arguments."""
        from celeste_dag.core.planner import (
            DAGNode,
            DAGPlan,
            extract_saga_plan,
        )

        plan = DAGPlan(
            name="test",
            nodes=[
                DAGNode(
                    name="n",
                    task_type="tool_execution",
                    command="do_thing",
                    compensation_command="undo_thing",
                ),
            ],
        )
        saga = extract_saga_plan(plan)
        step = saga.steps[0]
        assert step.compensation == "undo_thing"
        assert step.compensation_arguments == {}
