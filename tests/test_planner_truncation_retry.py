"""TDD test: Planner retries once on truncated LLM output.

Reasoning models (e.g. MiniMax-M3, DeepSeek-R1) often burn most of their
output budget on <think> traces and truncate the actual JSON. The planner
should detect the truncation (finish_reason == 'length') and retry once
with a smaller, more directive prompt before giving up.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from celeste.core.llm.base import LLMMessage, LLMResponse
from celeste.core.planner import DAGFragment, Planner


class _FakeClient:
    """LLM client that returns whatever sequence of responses is queued."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[int] = []  # max_tokens used per call
        self.message_history: list[list[LLMMessage]] = []

    async def structured_output_with_usage(
        self,
        messages: list[LLMMessage],
        response_model: type,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> tuple[LLMResponse | None, Any]:
        self.calls.append(max_tokens)
        self.message_history.append(list(messages))
        return self.responses.pop(0), self.responses_validation.pop(0)

    def set_validation(self, validations: list[Any]) -> None:
        self.responses_validation = list(validations)


def test_planner_retries_on_truncated_output():
    """A finish_reason='length' response on the first call triggers a retry."""
    first_resp = LLMResponse(
        content='{"nodes": [{"name": "rea',
        model="test-model",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        finish_reason="length",
        tool_calls=None,
    )
    second_fragment = DAGFragment(
        nodes=[],
        reasoning="truncated recovery",
        estimated_remaining=0,
        goal_achieved=True,
    )
    second_resp = LLMResponse(
        content='{"nodes": [], "reasoning": "truncated recovery", "estimated_remaining": 0, "goal_achieved": true}',
        model="test-model",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        finish_reason="stop",
        tool_calls=None,
    )
    client = _FakeClient([first_resp, second_resp])
    client.set_validation([None, second_fragment])
    planner = Planner(llm_client=client, toolkits=[])

    result = asyncio.run(planner.plan(goal="test goal"))

    # Both calls were made
    assert len(client.calls) == 2
    # First attempt used 8192, second used 12288
    assert client.calls[0] == 8192
    assert client.calls[1] == 12288
    # Second call's message history appended a directive about truncation
    assert any("truncated" in m.content for m in client.message_history[1])
    # The returned fragment is from the second call
    assert result.reasoning == "truncated recovery"
    assert result.goal_achieved is True


def test_planner_succeeds_on_first_call_when_no_truncation():
    """No retry if the first response is well-formed."""
    fragment = DAGFragment(
        nodes=[],
        reasoning="clean",
        estimated_remaining=0,
        goal_achieved=True,
    )
    resp = LLMResponse(
        content='{"nodes": [], "reasoning": "clean", "estimated_remaining": 0, "goal_achieved": true}',
        model="test-model",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        finish_reason="stop",
        tool_calls=None,
    )
    client = _FakeClient([resp])
    client.set_validation([fragment])
    planner = Planner(llm_client=client, toolkits=[])

    result = asyncio.run(planner.plan(goal="test goal"))

    assert len(client.calls) == 1
    assert client.calls[0] == 8192
    assert result.reasoning == "clean"


# ===========================================================================
# F012: Coverage for the for/else "raise last_error" path
# ===========================================================================
#
# The planner's internal retry loop has exactly 3 attempts. When all 3 fail
# (validation error, finish_reason='length', or domain-toolkit mismatch), the
# for/else clause runs and re-raises the last error to the caller. None of
# the existing tests exercise this branch — a regression that turned the
# else clause into a silent pass would not be caught.


class _FailingFakeClient:
    """LLM client whose structured_output_with_usage always raises the
    same exception, so the planner's for/else branch must execute."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls: int = 0

    async def structured_output_with_usage(
        self,
        messages: list[LLMMessage],
        response_model: type,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> tuple[LLMResponse | None, Any]:
        self.calls += 1
        raise self._exc


def test_planner_raises_after_three_validation_failures():
    """F012: When the LLM raises on every attempt (e.g. pydantic
    ValidationError), the planner's for/else clause re-raises the last
    exception to the caller. Without this test, a regression that turns
    the else clause into a silent pass would not be detected."""
    import pydantic

    exc = pydantic.ValidationError.from_exception_data(
        title="DAGFragment",
        line_errors=[
            {
                "type": "missing",
                "loc": ("reasoning",),
                "input": {},
                "ctx": {},
            }
        ],
    )
    client = _FailingFakeClient(exc)
    planner = Planner(llm_client=client, toolkits=[])

    with pytest.raises(pydantic.ValidationError):
        asyncio.run(planner.plan(goal="test goal"))

    # The planner should have made exactly 3 attempts before giving up.
    assert client.calls == 3


def test_planner_raises_after_three_truncations():
    """F012: When finish_reason='length' fires 3 times in a row, the
    planner re-raises ValueError('truncated') to the caller."""

    def make_truncated_response() -> LLMResponse:
        return LLMResponse(
            content='{"nodes": [{"name": "rea',
            model="test-model",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            finish_reason="length",
            tool_calls=None,
        )

    class _TruncatingClient:
        def __init__(self) -> None:
            self.calls = 0

        async def structured_output_with_usage(
            self,
            messages: list[LLMMessage],
            response_model: type,
            *,
            temperature: float = 0.0,
            max_tokens: int = 4096,
        ) -> tuple[LLMResponse | None, Any]:
            self.calls += 1
            return make_truncated_response(), None

    client = _TruncatingClient()
    planner = Planner(llm_client=client, toolkits=[])

    with pytest.raises(ValueError, match="truncated"):
        asyncio.run(planner.plan(goal="test goal"))

    assert client.calls == 3


def test_planner_raises_after_three_domain_tool_failures():
    """F012: When a domain toolkit is registered and the plan never uses
    any of its tools, the planner raises ValueError after 3 attempts."""

    from celeste.core.planner import BaseToolkit
    from celeste.toolkits.base import ToolDefinition, ToolParameter

    domain_tool = ToolDefinition(
        name="domain_specific_tool",
        description="a domain tool",
        parameters=[
            ToolParameter(name="x", type="string", description="arg", required=True)
        ],
        returns="result",
    )

    class _DomainToolkit(BaseToolkit):
        @property
        def name(self) -> str:
            return "domain"

        @property
        def description(self) -> str:
            return "domain toolkit"

        def get_tools(self):
            return [domain_tool]

        def get_tool(self, name):
            return domain_tool if name == domain_tool.name else None

        async def execute(self, name, arguments, driver):
            return {}

        # to_mcp_schemas is a non-abstract default; do not override.

    fragment_using_only_generic = DAGFragment(
        nodes=[],
        reasoning="uses read_file instead of domain_tool",
        estimated_remaining=1,
        goal_achieved=False,
    )

    class _GenericOnlyClient:
        def __init__(self) -> None:
            self.calls = 0

        async def structured_output_with_usage(
            self,
            messages: list[LLMMessage],
            response_model: type,
            *,
            temperature: float = 0.0,
            max_tokens: int = 4096,
        ) -> tuple[LLMResponse | None, Any]:
            self.calls += 1
            resp = LLMResponse(
                content='{"nodes": [], "reasoning": "x", "estimated_remaining": 1, "goal_achieved": false}',
                model="test-model",
                usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                finish_reason="stop",
                tool_calls=None,
            )
            return resp, fragment_using_only_generic

    client = _GenericOnlyClient()
    planner = Planner(llm_client=client, toolkits=[_DomainToolkit()])

    with pytest.raises(ValueError, match="ignored registered domain toolkit"):
        asyncio.run(planner.plan(goal="test goal"))

    assert client.calls == 3
