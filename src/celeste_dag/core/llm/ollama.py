"""
Ollama adapter for the multi-provider LLM client layer.

Uses ``httpx`` to make HTTP requests to an Ollama (or compatible vLLM)
endpoint, translating between the canonical ``LLMMessage`` / ``LLMResponse``
types and the Ollama chat API format.
"""

from __future__ import annotations

from typing import Any

import httpx

from celeste_dag.config.settings import EngineSettings
from celeste_dag.core.llm.base import (
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    ToolCallDef,
)


def _translate_messages(messages: list[LLMMessage]) -> list[dict[str, str]]:
    """Translate ``LLMMessage`` objects to the Ollama chat message format."""
    return [{"role": msg.role, "content": msg.content} for msg in messages]


class OllamaClient(BaseLLMClient):
    """LLM client backed by an Ollama HTTP endpoint."""

    def __init__(self, settings: EngineSettings) -> None:
        self._base_url = (settings.LLM_BASE_URL or "http://localhost:11434").rstrip("/")
        self._default_model = settings.LLM_MODEL
        self._client = httpx.AsyncClient()

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[ToolCallDef] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": _translate_messages(messages),
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        response = await self._client.post(
            f"{self._base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        prompt_tokens = data.get("prompt_eval_count", 0) or 0
        completion_tokens = data.get("eval_count", 0) or 0

        return LLMResponse(
            content=data["message"]["content"],
            model=data.get("model", model or self._default_model),
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            finish_reason="stop" if data.get("done") else None,
        )

    async def close(self) -> None:
        """Shut down the underlying ``httpx.AsyncClient``."""
        await self._client.aclose()
