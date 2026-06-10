"""
Anthropic Claude adapter for the multi-provider LLM client layer.

Wraps the official ``anthropic`` Python SDK and translates between the
canonical ``LLMMessage`` / ``LLMResponse`` types and the Anthropic API format.
"""

from __future__ import annotations

import json
from typing import Any

from anthropic import AsyncAnthropic

from celeste_dag.config.settings import EngineSettings
from celeste_dag.core.llm.base import (
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    ToolCallDef,
)


def _translate_messages(
    messages: list[LLMMessage],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Split *messages* into a system prompt and a list of Anthropic-formatted messages.

    Anthropic's API requires the system prompt as a separate parameter, so we
    extract any ``system`` role message here.
    """
    system: str | None = None
    translated: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            system = msg.content
        else:
            translated.append({"role": msg.role, "content": msg.content})

    return system, translated


def _translate_tools(tools: list[ToolCallDef]) -> list[dict[str, Any]]:
    """Translate ``ToolCallDef`` objects to the Anthropic tool schema format."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


class AnthropicClient(BaseLLMClient):
    """LLM client backed by the Anthropic Claude API."""

    def __init__(self, settings: EngineSettings) -> None:
        api_key = (
            settings.LLM_API_KEY.get_secret_value()
            if settings.LLM_API_KEY
            else None
        )
        self._client = AsyncAnthropic(api_key=api_key)
        self._default_model = settings.LLM_MODEL

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[ToolCallDef] | None = None,
    ) -> LLMResponse:
        system, api_messages = _translate_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": api_messages,
        }
        if system is not None:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _translate_tools(tools)

        response = await self._client.messages.create(**kwargs)

        # Extract text content -- collect ALL text blocks, not just the last one
        text_parts = [b.text for b in response.content if b.type == "text"]
        content = "\n".join(text_parts)

        tool_calls: list[dict] | None = None
        for block in response.content:
            if block.type == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input),
                        },
                    }
                )

        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            },
            finish_reason=response.stop_reason,
            tool_calls=tool_calls,
        )

    async def close(self) -> None:
        """Shut down the underlying ``AsyncAnthropic`` client."""
        await self._client.aclose()
