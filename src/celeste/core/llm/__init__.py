"""
Multi-provider LLM client layer.

Provides a unified interface for interacting with LLM providers (Anthropic,
OpenAI, Gemini, Ollama) through a common ``BaseLLMClient`` abstraction.
"""

from __future__ import annotations

from celeste.config.settings import EngineSettings
from celeste.core.llm.base import (
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    ToolCallDef,
)

__all__ = [
    "BaseLLMClient",
    "LLMMessage",
    "LLMResponse",
    "ToolCallDef",
    "create_llm_client",
]


def create_llm_client(settings: EngineSettings) -> BaseLLMClient:
    """Factory function that creates the correct LLM adapter based on settings.

    Parameters
    ----------
    settings:
        The engine settings containing ``LLM_PROVIDER``, ``LLM_MODEL``,
        ``LLM_API_KEY``, and ``LLM_BASE_URL``.

    Returns
    -------
    BaseLLMClient
        A concrete adapter instance for the configured provider.

    Raises
    ------
    ValueError
        If ``settings.LLM_PROVIDER`` is not a recognised provider.
    """
    provider = settings.LLM_PROVIDER

    if provider == "anthropic":
        from celeste.core.llm.anthropic import AnthropicClient

        return AnthropicClient(settings)

    if provider == "openai":
        from celeste.core.llm.openai import OpenAIClient

        return OpenAIClient(settings)

    if provider == "gemini":
        from celeste.core.llm.gemini import GeminiClient

        return GeminiClient(settings)

    if provider == "ollama":
        from celeste.core.llm.ollama import OllamaClient

        return OllamaClient(settings)

    raise ValueError(f"Unsupported LLM provider: {provider}")
