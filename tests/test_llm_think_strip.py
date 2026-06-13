"""Regression tests for stripping reasoning-model <think> blocks before JSON validation."""

from __future__ import annotations

from pydantic import BaseModel

from celeste.core.llm.base import BaseLLMClient, _extract_json_payload


class _Shape(BaseModel):
    goal: str
    achieved: bool


class _StubClient(BaseLLMClient):
    async def complete(self, messages, *, model=None, temperature=0.0, max_tokens=4096):
        from celeste.core.llm.base import LLMResponse

        return LLMResponse(
            content=(
                "<think>Let me reason about this carefully...</think>\n"
                "```json\n"
                '{"goal": "ship vaccine", "achieved": false}\n'
                "```"
            ),
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            model="stub",
        )

    async def close(self) -> None:  # pragma: no cover - nothing to close
        return None


def test_extract_strips_think_and_fence():
    content = (
        "<think>let me think</think>\n"
        "```json\n"
        '{"goal": "x", "achieved": true}\n'
        "```"
    )
    payload = _extract_json_payload(content)
    assert _Shape.model_validate_json(payload).goal == "x"


def test_extract_passes_through_clean_json():
    payload = _extract_json_payload('{"goal": "y", "achieved": false}')
    assert _Shape.model_validate_json(payload).goal == "y"


def test_structured_output_handles_think_block():
    import asyncio

    async def run() -> _Shape:
        client = _StubClient()
        return await client.structured_output(
            messages=[],  # ignored by stub
            response_model=_Shape,
        )

    parsed = asyncio.run(run())
    assert parsed.goal == "ship vaccine"
    assert parsed.achieved is False