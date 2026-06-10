"""
DAG planner with fan-out and Saga patterns (Tasks 4.1-4.3).

The Planner is the "Cognitive Right Brain" that compiles user requests into
executable DAG plans using an LLM.  It is model-agnostic -- any
``BaseLLMClient`` adapter can be used.

Public API:
- DAGNode / DAGPlan -- Pydantic models for compiled execution plans
- Planner -- LLM-backed compiler from natural-language requests to DAGPlans
- FanOutSpec / generate_fan_out_nodes -- dynamic fan-out expansion
- SagaStep / SagaPlan / extract_saga_plan -- Saga compensation pattern
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from celeste_dag.core.llm.base import BaseLLMClient, LLMMessage
from celeste_dag.toolkits.base import BaseToolkit


# =========================================================================
# Task 4.1 -- DAG models & Planner
# =========================================================================


class DAGNode(BaseModel):
    """A single node in the compiled DAG plan."""

    name: str
    task_type: Literal[
        "llm_call", "tool_execution", "fan_out", "map_reduce", "condition"
    ]
    command: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    compensation_command: str | None = None
    compensation_arguments: dict[str, Any] | None = None


class DAGPlan(BaseModel):
    """A complete DAG execution plan."""

    name: str
    description: str = ""
    nodes: list[DAGNode] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)


_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert workflow planner.  Your job is to compile the user's \
request into an executable DAG (directed acyclic graph) plan.

Each node in the DAG represents a discrete step:
- **llm_call**: Invoke an LLM with a prompt.
- **tool_execution**: Run a registered tool.
- **fan_out**: Dynamically spawn parallel sub-tasks from an array output.
- **map_reduce**: Apply a transformation to each element and merge results.
- **condition**: Branch based on a predicate.

Available tools:
{tools_section}

Output a valid JSON object matching the DAGPlan schema:
{{
  "name": "<plan_name>",
  "description": "<human-readable description>",
  "nodes": [
    {{
      "name": "<unique_node_name>",
      "task_type": "<one of: llm_call, tool_execution, fan_out, map_reduce, condition>",
      "command": "<command or tool name>",
      "arguments": {{}},
      "dependencies": ["<names of upstream nodes>"],
      "compensation_command": "<optional rollback command>",
      "compensation_arguments": {{}}
    }}
  ],
  "variables": {{}}
}}

Rules:
1. Node names must be unique within a plan.
2. Dependencies must reference existing node names.
3. State-mutating operations (writes, creates, sends) MUST have compensation_command.
4. Read-only operations do NOT need compensation.
5. Order nodes so dependencies come before dependents.
"""


class Planner:
    """Cognitive Right Brain: Compiles user requests into DAG execution plans."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        toolkits: list[BaseToolkit] | None = None,
    ) -> None:
        self._client = llm_client
        self._toolkits: list[BaseToolkit] = toolkits or []

    # -- public API --------------------------------------------------------

    async def plan(
        self,
        user_request: str,
        context: dict | None = None,
    ) -> DAGPlan:
        """Compile a user request into an executable DAG plan.

        Uses the LLM to:
        1. Understand the user's intent
        2. Map available tools to required actions
        3. Generate a DAG with proper dependency ordering
        4. Include compensation commands for state-mutating operations
        """
        tools_section = self._build_tools_section()
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(tools_section=tools_section)

        messages: list[LLMMessage] = [LLMMessage(role="system", content=system_prompt)]

        if context:
            context_str = json.dumps(context, default=str)
            messages.append(
                LLMMessage(
                    role="user",
                    content=f"Context:\n{context_str}\n\nRequest:\n{user_request}",
                )
            )
        else:
            messages.append(LLMMessage(role="user", content=user_request))

        return await self._client.structured_output(
            messages,
            DAGPlan,
            temperature=0.0,
        )

    def get_available_tools(self) -> list[dict[str, Any]]:
        """Return MCP schemas of all available tools from registered toolkits."""
        tools: list[dict[str, Any]] = []
        for toolkit in self._toolkits:
            tools.extend(toolkit.to_mcp_schemas())
        return tools

    def register_toolkit(self, toolkit: BaseToolkit) -> None:
        """Add a toolkit to the planner's available tools."""
        self._toolkits.append(toolkit)

    # -- private helpers ---------------------------------------------------

    def _build_tools_section(self) -> str:
        """Render available tools as a human-readable section for the prompt."""
        tools = self.get_available_tools()
        if not tools:
            return "(no tools registered)"
        lines: list[str] = []
        for t in tools:
            lines.append(f"- {t['name']}: {t['description']}")
            schema = t.get("inputSchema", {})
            props = schema.get("properties", {})
            for pname, pdef in props.items():
                lines.append(f"    - {pname} ({pdef.get('type', 'any')}): {pdef.get('description', '')}")
        return "\n".join(lines)


# =========================================================================
# Task 4.2 -- Dynamic Fan-Out Generation
# =========================================================================


class FanOutSpec(BaseModel):
    """Specification for a fan-out expansion."""

    source_node: str
    template_node: DAGNode
    max_parallel: int = 10


def generate_fan_out_nodes(
    parent_node_name: str,
    parent_output: list[Any],
    template: DAGNode,
    max_parallel: int = 10,
) -> list[DAGNode]:
    """Generate N child DAG nodes from a parent's array output.

    Each child node:
    - Gets a unique name: ``"{template.name}_{i}"``
    - Depends on the parent node
    - Has the current array element injected into *arguments* under the key
      ``"item"``
    - Inherits compensation from *template*
    """
    capped = parent_output[:max_parallel]
    nodes: list[DAGNode] = []
    for idx, element in enumerate(capped):
        # Merge template arguments with the injected item
        merged_args = {**template.arguments, "item": element}
        node = DAGNode(
            name=f"{template.name}_{idx}",
            task_type=template.task_type,
            command=template.command,
            arguments=merged_args,
            dependencies=[parent_node_name, *template.dependencies],
            compensation_command=template.compensation_command,
            compensation_arguments=template.compensation_arguments,
        )
        nodes.append(node)
    return nodes


# =========================================================================
# Task 4.3 -- Saga Compensation Pattern
# =========================================================================


class SagaStep(BaseModel):
    """A step in a Saga with its compensation."""

    node_name: str
    action: str
    compensation: str
    compensation_arguments: dict[str, Any] = Field(default_factory=dict)
    completed: bool = False


class SagaPlan(BaseModel):
    """Complete Saga execution plan with compensations."""

    workflow_name: str
    steps: list[SagaStep] = Field(default_factory=list)

    def get_compensations(self, failed_step_index: int) -> list[SagaStep]:
        """Get compensations for all completed steps before the failure.

        Returns steps in **reverse order** so that the most recently completed
        step is compensated first.
        """
        completed = [
            s for s in self.steps[:failed_step_index] if s.completed
        ]
        return list(reversed(completed))


def extract_saga_plan(dag_plan: DAGPlan) -> SagaPlan:
    """Extract a Saga plan from a DAG plan.

    Scans all nodes for ``compensation_command`` fields.  Nodes without
    compensations are still tracked but have an empty compensation string.
    """
    steps: list[SagaStep] = []
    for node in dag_plan.nodes:
        steps.append(
            SagaStep(
                node_name=node.name,
                action=node.command,
                compensation=node.compensation_command or "",
                compensation_arguments=node.compensation_arguments or {},
            )
        )
    return SagaPlan(workflow_name=dag_plan.name, steps=steps)
