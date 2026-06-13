"""
Tests for the multi-provider LLM client layer in core/llm/.

Follows strict TDD: these tests are written BEFORE the implementation.
All external API calls are mocked -- no real network requests.
"""

from __future__ import annotations

import json
from abc import ABC
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from celeste.config.settings import EngineSettings
from celeste.core.llm.base import (
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    ToolCallDef,
)


# ===========================================================================
# Pydantic models: LLMMessage
# ===========================================================================


class TestLLMMessage:
    """LLMMessage must be a valid Pydantic model with role/content fields."""

    def test_valid_system_message(self) -> None:
        msg = LLMMessage(role="system", content="You are a helpful assistant.")
        assert msg.role == "system"
        assert msg.content == "You are a helpful assistant."
        assert msg.tool_call_id is None
        assert msg.name is None

    def test_valid_user_message(self) -> None:
        msg = LLMMessage(role="user", content="Hello!")
        assert msg.role == "user"
        assert msg.content == "Hello!"

    def test_valid_assistant_message(self) -> None:
        msg = LLMMessage(role="assistant", content="Hi there!")
        assert msg.role == "assistant"

    def test_valid_tool_message(self) -> None:
        msg = LLMMessage(role="tool", content="result", tool_call_id="call_123")
        assert msg.role == "tool"
        assert msg.tool_call_id == "call_123"

    def test_message_with_name(self) -> None:
        msg = LLMMessage(role="assistant", content="", name="get_weather")
        assert msg.name == "get_weather"

    def test_invalid_role_raises(self) -> None:
        with pytest.raises(ValidationError):
            LLMMessage(role="invalid", content="test")

    def test_missing_content_raises(self) -> None:
        with pytest.raises(ValidationError):
            LLMMessage(role="user")  # type: ignore[call-arg]

    def test_missing_role_raises(self) -> None:
        with pytest.raises(ValidationError):
            LLMMessage(content="test")  # type: ignore[call-arg]

    def test_optional_fields_default_none(self) -> None:
        msg = LLMMessage(role="user", content="hi")
        assert msg.tool_call_id is None
        assert msg.name is None

    def test_model_dump(self) -> None:
        msg = LLMMessage(role="user", content="hi")
        d = msg.model_dump()
        assert d == {"role": "user", "content": "hi", "tool_call_id": None, "name": None}


# ===========================================================================
# Pydantic models: LLMResponse
# ===========================================================================


class TestLLMResponse:
    """LLMResponse must hold content, model, usage, finish_reason, and optional tool_calls."""

    def test_basic_response(self) -> None:
        resp = LLMResponse(
            content="Hello!",
            model="gpt-4o",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )
        assert resp.content == "Hello!"
        assert resp.model == "gpt-4o"
        assert resp.usage["total_tokens"] == 15
        assert resp.finish_reason == "stop"
        assert resp.tool_calls is None

    def test_response_with_tool_calls(self) -> None:
        tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "SF"}'},
            }
        ]
        resp = LLMResponse(
            content="",
            model="claude-3-5-sonnet-20241022",
            usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            finish_reason="tool_calls",
            tool_calls=tool_calls,
        )
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["function"]["name"] == "get_weather"

    def test_usage_dict_fields(self) -> None:
        resp = LLMResponse(
            content="",
            model="test",
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )
        assert resp.usage["prompt_tokens"] == 1
        assert resp.usage["completion_tokens"] == 2
        assert resp.usage["total_tokens"] == 3

    def test_missing_required_fields_raises(self) -> None:
        with pytest.raises(ValidationError):
            LLMResponse(content="hi")  # type: ignore[call-arg]

    def test_finish_reason_optional(self) -> None:
        resp = LLMResponse(
            content="hi",
            model="test",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )
        assert resp.finish_reason is None


# ===========================================================================
# Pydantic models: ToolCallDef
# ===========================================================================


class TestToolCallDef:
    """ToolCallDef must define name, description, and parameter schema."""

    def test_basic_tool_def(self) -> None:
        tool = ToolCallDef(
            name="get_weather",
            description="Get current weather for a city",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        )
        assert tool.name == "get_weather"
        assert tool.description == "Get current weather for a city"
        assert "properties" in tool.parameters
        assert "city" in tool.parameters["properties"]

    def test_missing_fields_raise(self) -> None:
        with pytest.raises(ValidationError):
            ToolCallDef(name="test")  # type: ignore[call-arg]

    def test_parameters_is_dict(self) -> None:
        tool = ToolCallDef(
            name="test", description="desc", parameters={"type": "object"}
        )
        assert isinstance(tool.parameters, dict)


# ===========================================================================
# BaseLLMClient is abstract
# ===========================================================================


class TestBaseLLMClientAbstract:
    """BaseLLMClient must be abstract and not directly instantiable."""

    def test_is_abstract(self) -> None:
        assert issubclass(BaseLLMClient, ABC)

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            BaseLLMClient()  # type: ignore[abstract]

    def test_has_complete_method(self) -> None:
        assert hasattr(BaseLLMClient, "complete")

    def test_has_structured_output_method(self) -> None:
        assert hasattr(BaseLLMClient, "structured_output")

    def test_has_close_method(self) -> None:
        assert hasattr(BaseLLMClient, "close")

    def test_complete_is_async(self) -> None:
        import inspect

        assert inspect.iscoroutinefunction(BaseLLMClient.complete)

    def test_structured_output_is_async(self) -> None:
        import inspect

        assert inspect.iscoroutinefunction(BaseLLMClient.structured_output)

    def test_close_is_async(self) -> None:
        import inspect

        assert inspect.iscoroutinefunction(BaseLLMClient.close)

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """BaseLLMClient should support async context manager protocol."""
        close_called = False

        class _CtxClient(BaseLLMClient):
            async def complete(self, messages, *, model=None, temperature=0.7, max_tokens=4096, tools=None):
                return LLMResponse(
                    content="test",
                    model="test",
                    usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                )

            async def close(self) -> None:
                nonlocal close_called
                close_called = True

        async with _CtxClient() as client:
            assert isinstance(client, _CtxClient)

        assert close_called, "close() should have been called on __aexit__"


# ===========================================================================
# Concrete subclass for testing default structured_output
# ===========================================================================


class _ConcreteClient(BaseLLMClient):
    """Minimal concrete client for testing default structured_output behavior."""

    def __init__(self, raw_json: str) -> None:
        self._raw_json = raw_json

    async def complete(self, messages, *, model=None, temperature=0.7, max_tokens=4096, tools=None):
        return LLMResponse(
            content=self._raw_json,
            model="test-model",
            usage={"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            finish_reason="stop",
        )

    async def close(self) -> None:
        pass


class _FailingClient(BaseLLMClient):
    """Client that returns non-JSON content to test error handling."""

    async def complete(self, messages, *, model=None, temperature=0.7, max_tokens=4096, tools=None):
        return LLMResponse(
            content="This is not valid JSON",
            model="test-model",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
        )

    async def close(self) -> None:
        pass


class _ToolCallClient(BaseLLMClient):
    """Client that returns tool calls."""

    async def complete(self, messages, *, model=None, temperature=0.7, max_tokens=4096, tools=None):
        return LLMResponse(
            content="",
            model="test-model",
            usage={"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            finish_reason="tool_calls",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": '{"query": "test"}'},
                }
            ],
        )

    async def close(self) -> None:
        pass


class TestDefaultStructuredOutput:
    """Default structured_output implementation should parse JSON from complete()."""

    @pytest.mark.asyncio
    async def test_parses_valid_json_into_model(self) -> None:
        class MyModel(BaseModel):
            name: str
            age: int

        client = _ConcreteClient('{"name": "Alice", "age": 30}')
        result = await client.structured_output(
            [LLMMessage(role="user", content="test")],
            response_model=MyModel,
        )
        assert isinstance(result, MyModel)
        assert result.name == "Alice"
        assert result.age == 30

    @pytest.mark.asyncio
    async def test_raises_on_invalid_json(self) -> None:
        class MyModel(BaseModel):
            name: str

        client = _FailingClient()
        with pytest.raises((ValueError, ValidationError)):
            await client.structured_output(
                [LLMMessage(role="user", content="test")],
                response_model=MyModel,
            )

    @pytest.mark.asyncio
    async def test_uses_temperature_zero(self) -> None:
        """structured_output should default to temperature=0.0 for deterministic output."""

        class MyModel(BaseModel):
            x: int

        captured_kwargs: dict = {}

        class _CapturingClient(BaseLLMClient):
            async def complete(self, messages, *, model=None, temperature=0.7, max_tokens=4096, tools=None):
                captured_kwargs["temperature"] = temperature
                return LLMResponse(
                    content='{"x": 1}',
                    model="test",
                    usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    finish_reason="stop",
                )

            async def close(self):
                pass

        client = _CapturingClient()
        await client.structured_output(
            [LLMMessage(role="user", content="test")],
            response_model=MyModel,
        )
        assert captured_kwargs["temperature"] == 0.0


# ===========================================================================
# Anthropic adapter
# ===========================================================================


class TestAnthropicAdapter:
    """AnthropicClient must translate messages and tools to Anthropic SDK format."""

    def _make_settings(self, **overrides) -> EngineSettings:
        defaults = {
            "LLM_PROVIDER": "anthropic",
            "LLM_MODEL": "claude-3-5-sonnet-20241022",
            "LLM_API_KEY": "sk-test-key",
        }
        defaults.update(overrides)
        return EngineSettings(**defaults)

    @pytest.mark.asyncio
    async def test_complete_translates_messages(self) -> None:
        """Messages should be translated to Anthropic's format (system separate)."""
        from celeste.core.llm.anthropic import AnthropicClient

        settings = self._make_settings()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Paris is the capital of France."

        mock_create = AsyncMock()
        mock_create.return_value = MagicMock(
            content=[text_block],
            model="claude-3-5-sonnet-20241022",
            usage=MagicMock(input_tokens=10, output_tokens=8),
            stop_reason="end_turn",
        )

        with patch("celeste.core.llm.anthropic.AsyncAnthropic") as MockAsyncAnthropic:
            mock_instance = MagicMock()
            mock_instance.messages = MagicMock()
            mock_instance.messages.create = mock_create
            MockAsyncAnthropic.return_value = mock_instance

            client = AnthropicClient(settings)
            messages = [
                LLMMessage(role="system", content="You are a geography expert."),
                LLMMessage(role="user", content="What is the capital of France?"),
            ]
            result = await client.complete(messages)

            assert isinstance(result, LLMResponse)
            assert result.content == "Paris is the capital of France."
            assert result.model == "claude-3-5-sonnet-20241022"

            # Verify the Anthropic SDK was called with system as separate param
            call_kwargs = mock_create.call_args
            assert "system" in call_kwargs.kwargs or len(call_kwargs.args) > 0

    @pytest.mark.asyncio
    async def test_complete_passes_model_override(self) -> None:
        """Model override should be passed through to Anthropic SDK."""
        from celeste.core.llm.anthropic import AnthropicClient

        settings = self._make_settings()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "hi"

        mock_create = AsyncMock()
        mock_create.return_value = MagicMock(
            content=[text_block],
            model="claude-3-haiku-20240307",
            usage=MagicMock(input_tokens=5, output_tokens=1),
            stop_reason="end_turn",
        )

        with patch("celeste.core.llm.anthropic.AsyncAnthropic") as MockAsyncAnthropic:
            mock_instance = MagicMock()
            mock_instance.messages.create = mock_create
            MockAsyncAnthropic.return_value = mock_instance

            client = AnthropicClient(settings)
            await client.complete(
                [LLMMessage(role="user", content="hi")],
                model="claude-3-haiku-20240307",
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["model"] == "claude-3-haiku-20240307"

    @pytest.mark.asyncio
    async def test_tool_schema_translation(self) -> None:
        """ToolCallDef should be translated to Anthropic's tool schema format."""
        from celeste.core.llm.anthropic import AnthropicClient

        settings = self._make_settings()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = ""

        mock_create = AsyncMock()
        mock_create.return_value = MagicMock(
            content=[text_block],
            model="claude-3-5-sonnet-20241022",
            usage=MagicMock(input_tokens=10, output_tokens=5),
            stop_reason="tool_use",
        )

        with patch("celeste.core.llm.anthropic.AsyncAnthropic") as MockAsyncAnthropic:
            mock_instance = MagicMock()
            mock_instance.messages.create = mock_create
            MockAsyncAnthropic.return_value = mock_instance

            client = AnthropicClient(settings)
            tools = [
                ToolCallDef(
                    name="get_weather",
                    description="Get weather for a city",
                    parameters={
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                )
            ]
            await client.complete(
                [LLMMessage(role="user", content="Weather in Paris?")],
                tools=tools,
            )

            call_kwargs = mock_create.call_args.kwargs
            assert "tools" in call_kwargs
            assert call_kwargs["tools"][0]["name"] == "get_weather"
            assert call_kwargs["tools"][0]["input_schema"]["properties"]["city"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_close_cleans_up(self) -> None:
        """close() should call aclose() on the underlying AsyncAnthropic client."""
        from celeste.core.llm.anthropic import AnthropicClient

        settings = self._make_settings()
        with patch("celeste.core.llm.anthropic.AsyncAnthropic") as MockAsyncAnthropic:
            mock_instance = MagicMock()
            mock_instance.aclose = AsyncMock()
            MockAsyncAnthropic.return_value = mock_instance

            client = AnthropicClient(settings)
            await client.close()
            mock_instance.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_api_key_passed_to_sdk(self) -> None:
        """The API key from settings should be passed to the Anthropic SDK."""
        from celeste.core.llm.anthropic import AnthropicClient

        settings = self._make_settings(LLM_API_KEY="sk-test-my-key")
        with patch("celeste.core.llm.anthropic.AsyncAnthropic") as MockAsyncAnthropic:
            MockAsyncAnthropic.return_value = MagicMock()
            AnthropicClient(settings)
            MockAsyncAnthropic.assert_called_once()
            call_kwargs = MockAsyncAnthropic.call_args.kwargs
            assert call_kwargs["api_key"] == "sk-test-my-key"

    @pytest.mark.asyncio
    async def test_multi_text_blocks_joined(self) -> None:
        """When response has multiple text blocks, all should be joined with newline."""
        from celeste.core.llm.anthropic import AnthropicClient

        settings = self._make_settings()
        block1 = MagicMock()
        block1.type = "text"
        block1.text = "First paragraph."

        block2 = MagicMock()
        block2.type = "text"
        block2.text = "Second paragraph."

        mock_create = AsyncMock()
        mock_create.return_value = MagicMock(
            content=[block1, block2],
            model="claude-3-5-sonnet-20241022",
            usage=MagicMock(input_tokens=10, output_tokens=15),
            stop_reason="end_turn",
        )

        with patch("celeste.core.llm.anthropic.AsyncAnthropic") as MockAsyncAnthropic:
            mock_instance = MagicMock()
            mock_instance.messages.create = mock_create
            MockAsyncAnthropic.return_value = mock_instance

            client = AnthropicClient(settings)
            result = await client.complete(
                [LLMMessage(role="user", content="Tell me two things")]
            )

            assert result.content == "First paragraph.\nSecond paragraph."

    @pytest.mark.asyncio
    async def test_tool_use_input_serialized_as_json(self) -> None:
        """tool_use block.input should be serialized with json.dumps, not str()."""
        from celeste.core.llm.anthropic import AnthropicClient

        settings = self._make_settings()
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "call_123"
        tool_block.name = "get_weather"
        tool_block.input = {"city": "Paris", "units": "metric"}

        mock_create = AsyncMock()
        mock_create.return_value = MagicMock(
            content=[tool_block],
            model="claude-3-5-sonnet-20241022",
            usage=MagicMock(input_tokens=10, output_tokens=5),
            stop_reason="tool_use",
        )

        with patch("celeste.core.llm.anthropic.AsyncAnthropic") as MockAsyncAnthropic:
            mock_instance = MagicMock()
            mock_instance.messages.create = mock_create
            MockAsyncAnthropic.return_value = mock_instance

            client = AnthropicClient(settings)
            result = await client.complete(
                [LLMMessage(role="user", content="Weather?")],
                tools=[ToolCallDef(
                    name="get_weather",
                    description="Get weather",
                    parameters={"type": "object"},
                )],
            )

            assert result.tool_calls is not None
            args = result.tool_calls[0]["function"]["arguments"]
            # json.dumps produces valid JSON; str() on a dict does NOT
            parsed = json.loads(args)
            assert parsed == {"city": "Paris", "units": "metric"}


# ===========================================================================
# OpenAI adapter
# ===========================================================================


class TestOpenAIAdapter:
    """OpenAIClient must translate messages and tools to OpenAI SDK format."""

    def _make_settings(self, **overrides) -> EngineSettings:
        defaults = {
            "LLM_PROVIDER": "openai",
            "LLM_MODEL": "gpt-4o",
            "LLM_API_KEY": "sk-test-openai",
        }
        defaults.update(overrides)
        return EngineSettings(**defaults)

    @pytest.mark.asyncio
    async def test_complete_translates_messages(self) -> None:
        """Messages should be sent directly to OpenAI format."""
        from celeste.core.llm.openai import OpenAIClient

        settings = self._make_settings()
        mock_create = AsyncMock()
        mock_create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(content="The answer is 42."),
                    finish_reason="stop",
                )
            ],
            model="gpt-4o",
            usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        with patch("celeste.core.llm.openai.AsyncOpenAI") as MockAsyncOpenAI:
            mock_instance = MagicMock()
            mock_instance.chat = MagicMock()
            mock_instance.chat.completions = MagicMock()
            mock_instance.chat.completions.create = mock_create
            MockAsyncOpenAI.return_value = mock_instance

            client = OpenAIClient(settings)
            messages = [
                LLMMessage(role="system", content="You are a math tutor."),
                LLMMessage(role="user", content="What is 6 * 7?"),
            ]
            result = await client.complete(messages)

            assert isinstance(result, LLMResponse)
            assert result.content == "The answer is 42."
            assert result.model == "gpt-4o"
            assert result.usage["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_tool_schema_translation(self) -> None:
        """ToolCallDef should be translated to OpenAI's function calling format."""
        from celeste.core.llm.openai import OpenAIClient

        settings = self._make_settings()
        func_mock = MagicMock()
        func_mock.name = "search"
        func_mock.arguments = '{"query": "test"}'

        tc_mock = MagicMock()
        tc_mock.id = "call_1"
        tc_mock.type = "function"
        tc_mock.function = func_mock

        msg_mock = MagicMock()
        msg_mock.content = ""
        msg_mock.tool_calls = [tc_mock]

        choice_mock = MagicMock()
        choice_mock.message = msg_mock
        choice_mock.finish_reason = "tool_calls"

        mock_create = AsyncMock()
        mock_create.return_value = MagicMock(
            choices=[choice_mock],
            model="gpt-4o",
            usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        with patch("celeste.core.llm.openai.AsyncOpenAI") as MockAsyncOpenAI:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = mock_create
            MockAsyncOpenAI.return_value = mock_instance

            client = OpenAIClient(settings)
            tools = [
                ToolCallDef(
                    name="search",
                    description="Search the web",
                    parameters={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                )
            ]
            result = await client.complete(
                [LLMMessage(role="user", content="search for cats")],
                tools=tools,
            )

            assert result.tool_calls is not None
            assert result.tool_calls[0]["function"]["name"] == "search"
            call_kwargs = mock_create.call_args.kwargs
            assert "tools" in call_kwargs

    @pytest.mark.asyncio
    async def test_structured_output_native(self) -> None:
        """OpenAI adapter should support structured output via response_format or JSON mode."""
        from celeste.core.llm.openai import OpenAIClient

        settings = self._make_settings()

        class MyOutput(BaseModel):
            answer: str
            confidence: float

        mock_create = AsyncMock()
        mock_create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(content='{"answer": "Paris", "confidence": 0.95}'),
                    finish_reason="stop",
                )
            ],
            model="gpt-4o",
            usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        with patch("celeste.core.llm.openai.AsyncOpenAI") as MockAsyncOpenAI:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = mock_create
            MockAsyncOpenAI.return_value = mock_instance

            client = OpenAIClient(settings)
            result = await client.structured_output(
                [LLMMessage(role="user", content="Capital of France?")],
                response_model=MyOutput,
            )
            assert isinstance(result, MyOutput)
            assert result.answer == "Paris"
            assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_close_cleans_up(self) -> None:
        """F013: OpenAIClient.close() must close the underlying AsyncOpenAI
        client (httpx connection pool). The previous implementation had an
        empty body that silently leaked connections.
        """
        from celeste.core.llm.openai import OpenAIClient

        settings = self._make_settings()
        with patch("celeste.core.llm.openai.AsyncOpenAI") as MockAsyncOpenAI:
            mock_instance = MagicMock()
            mock_instance.close = AsyncMock()
            MockAsyncOpenAI.return_value = mock_instance
            client = OpenAIClient(settings)
            await client.close()
            mock_instance.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_api_key_passed_to_sdk(self) -> None:
        from celeste.core.llm.openai import OpenAIClient

        settings = self._make_settings(LLM_API_KEY="sk-openai-test")
        with patch("celeste.core.llm.openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            OpenAIClient(settings)
            call_kwargs = MockAsyncOpenAI.call_args.kwargs
            assert call_kwargs["api_key"] == "sk-openai-test"


# ===========================================================================
# Gemini adapter
# ===========================================================================


class TestGeminiAdapter:
    """GeminiClient must translate messages to Google Generative AI SDK format."""

    def _make_settings(self, **overrides) -> EngineSettings:
        defaults = {
            "LLM_PROVIDER": "gemini",
            "LLM_MODEL": "gemini-2.0-flash",
            "LLM_API_KEY": "google-test-key",
        }
        defaults.update(overrides)
        return EngineSettings(**defaults)

    @pytest.mark.asyncio
    async def test_complete_translates_messages(self) -> None:
        from celeste.core.llm.gemini import GeminiClient

        settings = self._make_settings()

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Berlin is the capital of Germany."
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=10,
            candidates_token_count=8,
            total_token_count=18,
        )
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)

        with patch("celeste.core.llm.gemini.genai") as mock_genai:
            mock_genai.GenerativeModel.return_value = mock_model
            client = GeminiClient(settings)

            messages = [
                LLMMessage(role="user", content="Capital of Germany?"),
            ]
            result = await client.complete(messages)

            assert isinstance(result, LLMResponse)
            assert result.content == "Berlin is the capital of Germany."

    @pytest.mark.asyncio
    async def test_system_message_handled(self) -> None:
        """System messages should be translated to Gemini's system_instruction."""
        from celeste.core.llm.gemini import GeminiClient

        settings = self._make_settings()

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Done."
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=5,
            candidates_token_count=1,
            total_token_count=6,
        )
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)

        with patch("celeste.core.llm.gemini.genai") as mock_genai:
            mock_genai.GenerativeModel.return_value = mock_model
            client = GeminiClient(settings)

            messages = [
                LLMMessage(role="system", content="Be concise."),
                LLMMessage(role="user", content="Hi"),
            ]
            result = await client.complete(messages)
            assert result.content == "Done."

    @pytest.mark.asyncio
    async def test_api_key_configured(self) -> None:
        from celeste.core.llm.gemini import GeminiClient

        settings = self._make_settings(LLM_API_KEY="google-test-key")
        with patch("celeste.core.llm.gemini.genai") as mock_genai:
            mock_genai.GenerativeModel.return_value = MagicMock()
            client = GeminiClient(settings)
            mock_genai.configure.assert_called_once()
            call_kwargs = mock_genai.configure.call_args.kwargs
            assert call_kwargs["api_key"] == "google-test-key"

    @pytest.mark.asyncio
    async def test_close_cleans_up(self) -> None:
        from celeste.core.llm.gemini import GeminiClient

        settings = self._make_settings()
        with patch("celeste.core.llm.gemini.genai") as mock_genai:
            mock_genai.GenerativeModel.return_value = MagicMock()
            client = GeminiClient(settings)
            await client.close()

    @pytest.mark.asyncio
    async def test_tools_raises_not_implemented(self) -> None:
        """Gemini adapter should raise NotImplementedError when tools are provided."""
        from celeste.core.llm.gemini import GeminiClient

        settings = self._make_settings()
        with patch("celeste.core.llm.gemini.genai") as mock_genai:
            mock_genai.GenerativeModel.return_value = MagicMock()
            client = GeminiClient(settings)

            with pytest.raises(NotImplementedError, match="tool"):
                await client.complete(
                    [LLMMessage(role="user", content="test")],
                    tools=[ToolCallDef(
                        name="test_tool",
                        description="A test",
                        parameters={"type": "object"},
                    )],
                )

    @pytest.mark.asyncio
    async def test_model_override_does_not_mutate_instance(self) -> None:
        """Passing model= should not permanently change the default model."""
        from celeste.core.llm.gemini import GeminiClient

        settings = self._make_settings()

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello"
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=5,
            candidates_token_count=3,
            total_token_count=8,
        )
        mock_response.candidates = []
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)

        with patch("celeste.core.llm.gemini.genai") as mock_genai:
            mock_genai.GenerativeModel.return_value = mock_model
            client = GeminiClient(settings)
            original_model = client._model_name

            await client.complete(
                [LLMMessage(role="user", content="hi")],
                model="gemini-1.5-pro",
            )
            # _model_name should NOT have been mutated
            assert client._model_name == original_model

    @pytest.mark.asyncio
    async def test_finish_reason_from_response(self) -> None:
        """Gemini adapter should read actual finish_reason from the response."""
        from celeste.core.llm.gemini import GeminiClient

        settings = self._make_settings()

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Stopped because of safety."
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=5,
            candidates_token_count=3,
            total_token_count=8,
        )
        # Simulate a SAFETY finish reason
        mock_reason = MagicMock()
        mock_reason.name = "SAFETY"
        mock_candidate = MagicMock()
        mock_candidate.finish_reason = mock_reason
        mock_response.candidates = [mock_candidate]
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)

        with patch("celeste.core.llm.gemini.genai") as mock_genai:
            mock_genai.GenerativeModel.return_value = mock_model
            client = GeminiClient(settings)

            result = await client.complete(
                [LLMMessage(role="user", content="something risky")],
            )
            assert result.finish_reason == "safety"


# ===========================================================================
# Ollama adapter
# ===========================================================================


class TestOllamaAdapter:
    """OllamaClient must make correct HTTP requests to Ollama API endpoints."""

    def _make_settings(self, **overrides) -> EngineSettings:
        defaults = {
            "LLM_PROVIDER": "ollama",
            "LLM_MODEL": "llama3",
            "LLM_BASE_URL": "http://localhost:11434",
        }
        defaults.update(overrides)
        return EngineSettings(**defaults)

    @pytest.mark.asyncio
    async def test_complete_makes_http_request(self) -> None:
        from celeste.core.llm.ollama import OllamaClient

        settings = self._make_settings()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Hello from Ollama!"},
            "model": "llama3",
            "prompt_eval_count": 10,
            "eval_count": 5,
            "done": True,
        }
        mock_response.raise_for_status = MagicMock()

        mock_post = AsyncMock(return_value=mock_response)

        with patch("celeste.core.llm.ollama.httpx.AsyncClient") as MockAsyncClient:
            mock_client_instance = MagicMock()
            mock_client_instance.post = mock_post
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            MockAsyncClient.return_value = mock_client_instance

            client = OllamaClient(settings)
            result = await client.complete(
                [LLMMessage(role="user", content="Hello")]
            )

            assert isinstance(result, LLMResponse)
            assert result.content == "Hello from Ollama!"
            assert result.model == "llama3"

            # Verify correct endpoint
            call_args = mock_post.call_args
            url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
            assert "/api/chat" in url

    @pytest.mark.asyncio
    async def test_complete_passes_model_and_messages(self) -> None:
        from celeste.core.llm.ollama import OllamaClient

        settings = self._make_settings()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "response"},
            "model": "llama3",
            "prompt_eval_count": 5,
            "eval_count": 2,
            "done": True,
        }
        mock_response.raise_for_status = MagicMock()
        mock_post = AsyncMock(return_value=mock_response)

        with patch("celeste.core.llm.ollama.httpx.AsyncClient") as MockAsyncClient:
            mock_client_instance = MagicMock()
            mock_client_instance.post = mock_post
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            MockAsyncClient.return_value = mock_client_instance

            client = OllamaClient(settings)
            await client.complete(
                [LLMMessage(role="user", content="test")],
                model="mistral",
                temperature=0.5,
                max_tokens=2048,
            )

            call_kwargs = mock_post.call_args
            body = call_kwargs.kwargs.get("json", {})
            assert body.get("model") == "mistral"
            assert body.get("stream") is False

    @pytest.mark.asyncio
    async def test_close_cleans_up(self) -> None:
        from celeste.core.llm.ollama import OllamaClient

        settings = self._make_settings()

        with patch("celeste.core.llm.ollama.httpx.AsyncClient") as MockAsyncClient:
            mock_instance = MagicMock()
            mock_instance.aclose = AsyncMock()
            MockAsyncClient.return_value = mock_instance

            client = OllamaClient(settings)
            await client.close()

    @pytest.mark.asyncio
    async def test_no_api_key_needed(self) -> None:
        """Ollama should work without an API key."""
        from celeste.core.llm.ollama import OllamaClient

        settings = self._make_settings(LLM_API_KEY=None)
        with patch("celeste.core.llm.ollama.httpx.AsyncClient") as MockAsyncClient:
            mock_instance = MagicMock()
            MockAsyncClient.return_value = mock_instance
            client = OllamaClient(settings)
            assert client is not None

    @pytest.mark.asyncio
    async def test_uses_base_url(self) -> None:
        """Ollama client should use LLM_BASE_URL from settings."""
        from celeste.core.llm.ollama import OllamaClient

        settings = self._make_settings(LLM_BASE_URL="http://my-ollama:11434")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "hi"},
            "model": "llama3",
            "prompt_eval_count": 5,
            "eval_count": 2,
            "done": True,
        }
        mock_response.raise_for_status = MagicMock()
        mock_post = AsyncMock(return_value=mock_response)

        with patch("celeste.core.llm.ollama.httpx.AsyncClient") as MockAsyncClient:
            mock_client_instance = MagicMock()
            mock_client_instance.post = mock_post
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            MockAsyncClient.return_value = mock_client_instance

            client = OllamaClient(settings)
            await client.complete([LLMMessage(role="user", content="hi")])

            url = mock_post.call_args.args[0]
            assert url.startswith("http://my-ollama:11434")


# ===========================================================================
# Factory function: create_llm_client
# ===========================================================================


class TestCreateLLMClient:
    """create_llm_client must return the correct adapter type based on settings."""

    def test_anthropic_provider(self) -> None:
        from celeste.core.llm import create_llm_client
        from celeste.core.llm.anthropic import AnthropicClient

        settings = EngineSettings(
            LLM_PROVIDER="anthropic",
            LLM_MODEL="claude-3-5-sonnet-20241022",
            LLM_API_KEY="sk-test",
        )
        with patch("celeste.core.llm.anthropic.AsyncAnthropic"):
            client = create_llm_client(settings)
            assert isinstance(client, AnthropicClient)

    def test_openai_provider(self) -> None:
        from celeste.core.llm import create_llm_client
        from celeste.core.llm.openai import OpenAIClient

        settings = EngineSettings(
            LLM_PROVIDER="openai",
            LLM_MODEL="gpt-4o",
            LLM_API_KEY="sk-test",
        )
        with patch("celeste.core.llm.openai.AsyncOpenAI"):
            client = create_llm_client(settings)
            assert isinstance(client, OpenAIClient)

    def test_gemini_provider(self) -> None:
        from celeste.core.llm import create_llm_client
        from celeste.core.llm.gemini import GeminiClient

        settings = EngineSettings(
            LLM_PROVIDER="gemini",
            LLM_MODEL="gemini-2.0-flash",
            LLM_API_KEY="test-key",
        )
        with patch("celeste.core.llm.gemini.genai"):
            client = create_llm_client(settings)
            assert isinstance(client, GeminiClient)

    def test_ollama_provider(self) -> None:
        from celeste.core.llm import create_llm_client
        from celeste.core.llm.ollama import OllamaClient

        settings = EngineSettings(
            LLM_PROVIDER="ollama",
            LLM_MODEL="llama3",
            LLM_BASE_URL="http://localhost:11434",
        )
        with patch("celeste.core.llm.ollama.httpx.AsyncClient"):
            client = create_llm_client(settings)
            assert isinstance(client, OllamaClient)

    def test_returns_base_llm_client(self) -> None:
        """All adapters should be instances of BaseLLMClient."""
        from celeste.core.llm import create_llm_client

        settings = EngineSettings(
            LLM_PROVIDER="openai",
            LLM_MODEL="gpt-4o",
            LLM_API_KEY="sk-test",
        )
        with patch("celeste.core.llm.openai.AsyncOpenAI"):
            client = create_llm_client(settings)
            assert isinstance(client, BaseLLMClient)

    def test_unknown_provider_raises(self) -> None:
        """An unsupported provider should raise ValueError."""
        from celeste.core.llm import create_llm_client

        # We can't create an EngineSettings with an invalid provider directly,
        # so we test with a mocked settings object
        mock_settings = MagicMock()
        mock_settings.LLM_PROVIDER = "unknown_provider"
        mock_settings.LLM_MODEL = "test"
        mock_settings.LLM_API_KEY = None
        mock_settings.LLM_BASE_URL = None

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            create_llm_client(mock_settings)


# ===========================================================================
# Error handling
# ===========================================================================


class TestErrorHandling:
    """LLM clients should handle errors gracefully."""

    @pytest.mark.asyncio
    async def test_anthropic_api_error(self) -> None:
        """AnthropicClient should propagate API errors."""
        from celeste.core.llm.anthropic import AnthropicClient

        settings = EngineSettings(
            LLM_PROVIDER="anthropic",
            LLM_MODEL="claude-3-5-sonnet-20241022",
            LLM_API_KEY="sk-test",
        )

        with patch("celeste.core.llm.anthropic.AsyncAnthropic") as MockAsyncAnthropic:
            mock_instance = MagicMock()
            mock_instance.messages.create = AsyncMock(
                side_effect=Exception("API rate limit exceeded")
            )
            MockAsyncAnthropic.return_value = mock_instance

            client = AnthropicClient(settings)
            with pytest.raises(Exception, match="API rate limit exceeded"):
                await client.complete(
                    [LLMMessage(role="user", content="test")]
                )

    @pytest.mark.asyncio
    async def test_openai_api_error(self) -> None:
        """OpenAIClient should propagate API errors."""
        from celeste.core.llm.openai import OpenAIClient

        settings = EngineSettings(
            LLM_PROVIDER="openai",
            LLM_MODEL="gpt-4o",
            LLM_API_KEY="sk-test",
        )

        with patch("celeste.core.llm.openai.AsyncOpenAI") as MockAsyncOpenAI:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = AsyncMock(
                side_effect=Exception("Server error")
            )
            MockAsyncOpenAI.return_value = mock_instance

            client = OpenAIClient(settings)
            with pytest.raises(Exception, match="Server error"):
                await client.complete(
                    [LLMMessage(role="user", content="test")]
                )

    @pytest.mark.asyncio
    async def test_ollama_connection_error(self) -> None:
        """OllamaClient should handle connection errors."""
        from celeste.core.llm.ollama import OllamaClient

        settings = EngineSettings(
            LLM_PROVIDER="ollama",
            LLM_MODEL="llama3",
            LLM_BASE_URL="http://localhost:11434",
        )

        with patch("celeste.core.llm.ollama.httpx.AsyncClient") as MockAsyncClient:
            mock_instance = MagicMock()
            mock_instance.post = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockAsyncClient.return_value = mock_instance

            client = OllamaClient(settings)
            with pytest.raises(Exception, match="Connection refused"):
                await client.complete(
                    [LLMMessage(role="user", content="test")]
                )

    @pytest.mark.asyncio
    async def test_structured_output_validation_error(self) -> None:
        """structured_output should raise when JSON doesn't match the Pydantic model."""
        client = _ConcreteClient('{"wrong_field": "value"}')

        class StrictModel(BaseModel):
            required_name: str
            required_age: int

        with pytest.raises((ValidationError, ValueError)):
            await client.structured_output(
                [LLMMessage(role="user", content="test")],
                response_model=StrictModel,
            )


# ===========================================================================
# Re-exports from __init__.py
# ===========================================================================


class TestReexports:
    """Public API should be re-exported from core.llm package."""

    def test_create_llm_client_reexported(self) -> None:
        from celeste.core.llm import create_llm_client
        assert callable(create_llm_client)

    def test_base_client_reexported(self) -> None:
        from celeste.core.llm import BaseLLMClient
        assert BaseLLMClient is not None

    def test_models_reexported(self) -> None:
        from celeste.core.llm import LLMMessage, LLMResponse, ToolCallDef
        assert LLMMessage is not None
        assert LLMResponse is not None
        assert ToolCallDef is not None
