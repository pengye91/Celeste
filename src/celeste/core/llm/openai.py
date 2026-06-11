"""
OpenAI GPT adapter for the multi-provider LLM client layer.

Wraps the official ``openai`` Python SDK and translates between the
canonical ``LLMMessage`` / ``LLMResponse`` types and the OpenAI API format.
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from celeste.config.settings import EngineSettings
from celeste.core.llm.base import (
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    ToolCallDef,
)


def _translate_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    """Translate ``LLMMessage`` objects to the OpenAI chat message format."""
    result: list[dict[str, Any]] = []
    for msg in messages:
        d: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.name is not None:
            d["name"] = msg.name
        if msg.tool_call_id is not None:
            d["tool_call_id"] = msg.tool_call_id
        result.append(d)
    return result


def _translate_tools(tools: list[ToolCallDef]) -> list[dict[str, Any]]:
    """Translate ``ToolCallDef`` objects to the OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


class OpenAIClient(BaseLLMClient):
    """LLM client backed by the OpenAI GPT API."""

    def __init__(self, settings: EngineSettings) -> None:
        api_key = (
            settings.LLM_API_KEY.get_secret_value()
            if settings.LLM_API_KEY
            else None
        )
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=settings.LLM_BASE_URL,
        )
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
        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": _translate_messages(messages),
        }
        if tools:
            kwargs["tools"] = _translate_tools(tools)

        response = await self._client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[dict] | None = None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        return LLMResponse(
            content=msg.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            finish_reason=choice.finish_reason,
            tool_calls=tool_calls,
        )

    async def close(self) -> None:
        """Shut down the underlying ``AsyncOpenAI`` client."""
