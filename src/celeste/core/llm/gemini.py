"""
Google Gemini adapter for the multi-provider LLM client layer.

Wraps the ``google.generativeai`` SDK and translates between the
canonical ``LLMMessage`` / ``LLMResponse`` types and the Gemini API format.
"""

from __future__ import annotations

from typing import Any

import google.generativeai as genai

from celeste.config.settings import EngineSettings
from celeste.core.llm.base import (
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    ToolCallDef,
)


def _translate_messages(
    messages: list[LLMMessage],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Split *messages* into a system instruction and Gemini-formatted contents.

    Gemini handles system prompts via the ``system_instruction`` parameter on
    the model, so we extract any ``system`` role message here.
    """
    system: str | None = None
    translated: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            system = msg.content
        elif msg.role == "user":
            translated.append({"role": "user", "parts": [msg.content]})
        elif msg.role == "assistant":
            translated.append({"role": "model", "parts": [msg.content]})
        elif msg.role == "tool":
            translated.append({"role": "function", "parts": [msg.content]})

    return system, translated


class GeminiClient(BaseLLMClient):
    """LLM client backed by the Google Gemini API."""

    def __init__(self, settings: EngineSettings) -> None:
        api_key = (
            settings.LLM_API_KEY.get_secret_value()
            if settings.LLM_API_KEY
            else None
        )
        genai.configure(api_key=api_key)
        self._default_model = settings.LLM_MODEL
        self._model_name = settings.LLM_MODEL

    def _get_model(self, model_name: str, system: str | None = None) -> Any:
        """Return a ``GenerativeModel`` instance, optionally with a system instruction."""
        kwargs: dict[str, Any] = {}
        if system:
            kwargs["system_instruction"] = system
        return genai.GenerativeModel(model_name, **kwargs)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[ToolCallDef] | None = None,
    ) -> LLMResponse:
        if tools:
            raise NotImplementedError(
                "Gemini adapter does not yet support tool/function calling. "
                "Use the OpenAI or Anthropic adapter instead."
            )

        model_name = model or self._model_name

        system, contents = _translate_messages(messages)
        gen_model = self._get_model(model_name, system)

        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        response = await gen_model.generate_content_async(
            contents,
            generation_config=generation_config,
        )

        usage = response.usage_metadata
        prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
        completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
        total_tokens = getattr(usage, "total_token_count", 0) or 0

        # Read actual finish_reason from the response
        finish_reason = "stop"
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            reason = getattr(candidate, "finish_reason", None)
            if reason is not None:
                finish_reason = str(reason.name if hasattr(reason, "name") else reason).lower()

        return LLMResponse(
            content=response.text or "",
            model=model_name,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            finish_reason=finish_reason,
        )

    async def close(self) -> None:
        """Clean up Gemini client resources."""
