"""
Base types and abstract interface for the multi-provider LLM client layer.

All LLM adapters must inherit from BaseLLMClient and implement the
abstract methods defined here.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Literal, Self

from pydantic import BaseModel


# Matches <think>...</think> reasoning blocks emitted by reasoning models
# (e.g. DeepSeek-R1, MiniMax-M3, OpenAI o-series). Non-greedy so multiple
# blocks collapse, and DOTALL so the trace can span newlines.
_REASONING_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Matches ```json ... ``` or ``` ... ``` fences that often wrap structured
# output. Captured group 1 is the inner payload (or the whole fence if the
# language tag is missing).
_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?```",
    re.DOTALL,
)


def _extract_json_payload(content: str) -> str:
    r"""Return the JSON payload from an LLM response that may include
    reasoning traces and markdown code fences.

    The function is forgiving: it strips ``<think>...</think>`` blocks,
    unwraps triple-backtick json fences, and finally trims surrounding
    whitespace.  If nothing matches, the original content is returned
    unchanged so existing pipelines keep working.
    """
    if not content:
        return content

    # 1. Strip reasoning traces first (they often contain prose around the
    #    actual answer, including a fenced JSON block).
    stripped = _REASONING_BLOCK_RE.sub("", content)

    # 2. If a fenced code block exists anywhere in the remaining text,
    #    prefer the LAST one — reasoning models tend to dump intermediate
    #    scratchpads in earlier fences and put the real answer last.
    fences = _JSON_FENCE_RE.findall(stripped)
    if fences:
        return fences[-1].strip()

    return stripped.strip()


class LLMMessage(BaseModel):
    """A single message in a conversation sent to an LLM."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class LLMResponse(BaseModel):
    """Response from an LLM completion call."""

    content: str
    model: str
    usage: dict  # {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
    finish_reason: str | None = None
    tool_calls: list[dict] | None = None  # For function/tool calling


class ToolCallDef(BaseModel):
    """Tool definition for structured output / function calling."""

    name: str
    description: str
    parameters: dict  # JSON schema for parameters


class BaseLLMClient(ABC):
    """Abstract base class for all LLM provider adapters.

    Every concrete adapter must implement ``complete``, ``structured_output``,
    and ``close``.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[ToolCallDef] | None = None,
    ) -> LLMResponse:
        """Standard completion API."""

    async def structured_output(
        self,
        messages: list[LLMMessage],
        response_model: type[BaseModel],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> BaseModel:
        """Structured output with Pydantic model validation.

        Default implementation: call ``complete`` and parse the JSON content
        into the given Pydantic model.  Subclasses may override for
        provider-native structured output.
        """
        response = await self.complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        payload = _extract_json_payload(response.content)
        return response_model.model_validate_json(payload)

    async def structured_output_with_usage(
        self,
        messages: list[LLMMessage],
        response_model: type[BaseModel],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> tuple[LLMResponse | None, BaseModel]:
        """Like :meth:`structured_output` but also returns the raw LLMResponse.

        Default implementation calls ``structured_output`` and returns a
        ``(None, model)`` tuple (no usage captured). Subclasses that have
        provider-native structured output should override this to also
        return the ``LLMResponse`` so callers can harvest ``usage``.
        """
        parsed = await self.structured_output(
            messages,
            response_model,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return None, parsed

    @abstractmethod
    async def close(self) -> None:
        """Clean up client resources."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
