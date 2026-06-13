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
