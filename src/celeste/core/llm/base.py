"""
Base types and abstract interface for the multi-provider LLM client layer.

All LLM adapters must inherit from BaseLLMClient and implement the
abstract methods defined here.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Literal, Self

from pydantic import BaseModel


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
        return response_model.model_validate_json(response.content)

    @abstractmethod
    async def close(self) -> None:
        """Clean up client resources."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
