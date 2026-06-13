"""
Tests for the Evaluator (OPA Loop decision engine).

Follows strict TDD: these tests are written BEFORE the implementation.
Covers:
- EvaluatorDecision enum/class with DONE, REPLAN, ESCALATE, CONTINUE
- EvaluatorDecision equality with strings
- EvaluatorDecision reason attribute
- Evaluator.evaluate() calls LLM and parses each decision type
- Evaluator caching: cache hit returns cached decision
- Evaluator caching: different goal produces cache miss
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from celeste.core.llm.base import BaseLLMClient, LLMMessage, LLMResponse
from celeste.config.settings import EngineSettings


# ---------------------------------------------------------------------------
# Helpers -- concrete test doubles for abstract base classes
# ---------------------------------------------------------------------------


class _StubLLMClient(BaseLLMClient):
    """Concrete LLM client that records calls and returns canned responses."""

    def __init__(self, response_content: str = "DONE\nGoal achieved.") -> None:
        self.complete_calls: list[dict[str, Any]] = []
        self._response_content = response_content

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        self.complete_calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": tools,
            }
        )
        return LLMResponse(
            content=self._response_content,
            model="stub",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    async def close(self) -> None:
        pass


class _MockFragment:
    """Simple stand-in for a workflow fragment."""

    def __init__(self, tasks: list[dict[str, Any]]) -> None:
        self.tasks = tasks

    def __repr__(self) -> str:
        return f"_MockFragment(tasks={self.tasks!r})"


# ===========================================================================
# EvaluatorDecision
# ===========================================================================


class TestEvaluatorDecision:
    """Tests for the EvaluatorDecision class."""

    def test_decision_values_exist(self):
        from celeste.core.evaluator import EvaluatorDecision

        assert EvaluatorDecision.DONE is not None
        assert EvaluatorDecision.REPLAN is not None
        assert EvaluatorDecision.ESCALATE is not None
        assert EvaluatorDecision.CONTINUE is not None

    def test_decision_string_equality(self):
        from celeste.core.evaluator import EvaluatorDecision

        assert EvaluatorDecision.DONE == "DONE"
        assert EvaluatorDecision.REPLAN == "REPLAN"
        assert EvaluatorDecision.ESCALATE == "ESCALATE"
        assert EvaluatorDecision.CONTINUE == "CONTINUE"

    def test_decision_reason_attribute(self):
        from celeste.core.evaluator import EvaluatorDecision

        decision = EvaluatorDecision.DONE
        assert hasattr(decision, "reason")

    def test_decision_reason_settable(self):
        from celeste.core.evaluator import EvaluatorDecision

        decision = EvaluatorDecision.DONE
        decision.reason = "All tasks completed successfully."
        assert decision.reason == "All tasks completed successfully."


# ===========================================================================
# Evaluator.evaluate() -- decision types
# ===========================================================================


class TestEvaluatorDecisions:
    """Tests for Evaluator.evaluate() returning each decision type."""

    @pytest.mark.asyncio()
    async def test_evaluator_returns_done(self):
        """Evaluator should return DONE when LLM responds with DONE."""
        from celeste.core.evaluator import Evaluator, EvaluatorDecision

        client = _StubLLMClient(response_content="DONE\nGoal fully achieved.")
        evaluator = Evaluator(client)

        fragment = _MockFragment([{"name": "task1", "status": "completed"}])
        decision = await evaluator.evaluate(fragment, goal="Complete the workflow")

        assert decision == EvaluatorDecision.DONE
        assert decision == "DONE"
        assert "achieved" in decision.reason.lower() or decision.reason == "Goal fully achieved."

    @pytest.mark.asyncio()
    async def test_evaluator_returns_replan(self):
        """Evaluator should return REPLAN when LLM responds with REPLAN."""
        from celeste.core.evaluator import Evaluator, EvaluatorDecision

        client = _StubLLMClient(response_content="REPLAN\nNeed a different approach.")
        evaluator = Evaluator(client)

        fragment = _MockFragment([{"name": "task1", "status": "failed"}])
        decision = await evaluator.evaluate(fragment, goal="Complete the workflow")

        assert decision == EvaluatorDecision.REPLAN
        assert decision == "REPLAN"
        assert "different approach" in decision.reason.lower() or decision.reason == "Need a different approach."

    @pytest.mark.asyncio()
    async def test_evaluator_returns_escalate(self):
        """Evaluator should return ESCALATE when LLM responds with ESCALATE."""
        from celeste.core.evaluator import Evaluator, EvaluatorDecision

        client = _StubLLMClient(response_content="ESCALATE\nHuman intervention required.")
        evaluator = Evaluator(client)

        fragment = _MockFragment([{"name": "task1", "status": "blocked"}])
        decision = await evaluator.evaluate(fragment, goal="Complete the workflow")

        assert decision == EvaluatorDecision.ESCALATE
        assert decision == "ESCALATE"
        assert "intervention" in decision.reason.lower() or decision.reason == "Human intervention required."

    @pytest.mark.asyncio()
    async def test_evaluator_returns_continue(self):
        """Evaluator should return CONTINUE when LLM responds with CONTINUE."""
        from celeste.core.evaluator import Evaluator, EvaluatorDecision

        client = _StubLLMClient(response_content="CONTINUE\nMore tasks needed.")
        evaluator = Evaluator(client)

        fragment = _MockFragment([{"name": "task1", "status": "in_progress"}])
        decision = await evaluator.evaluate(fragment, goal="Complete the workflow")

        assert decision == EvaluatorDecision.CONTINUE
        assert decision == "CONTINUE"
        assert "needed" in decision.reason.lower() or decision.reason == "More tasks needed."


# ===========================================================================
# Evaluator caching
# ===========================================================================


class TestEvaluatorCache:
    """Tests for Evaluator caching behavior."""

    @pytest.mark.asyncio()
    async def test_evaluator_cache_hit(self):
        """Second call with same fragment and goal should return cached decision."""
        from celeste.core.evaluator import Evaluator, EvaluatorDecision

        client = _StubLLMClient(response_content="DONE\nGoal achieved.")
        settings = EngineSettings(EVALUATOR_CACHE_ENABLED=True, EVALUATOR_CACHE_TTL_SECONDS=3600)
        evaluator = Evaluator(client, settings=settings)

        fragment = _MockFragment([{"name": "task1", "status": "completed"}])
        goal = "Complete the workflow"

        decision1 = await evaluator.evaluate(fragment, goal=goal)
        decision2 = await evaluator.evaluate(fragment, goal=goal)

        assert decision1 == decision2
        assert decision1 == EvaluatorDecision.DONE
        # LLM should only be called once
        assert len(client.complete_calls) == 1

    @pytest.mark.asyncio()
    async def test_evaluator_cache_miss_different_goal(self):
        """Same fragment with different goal should be a cache miss."""
        from celeste.core.evaluator import Evaluator, EvaluatorDecision

        client = _StubLLMClient(response_content="DONE\nGoal achieved.")
        settings = EngineSettings(EVALUATOR_CACHE_ENABLED=True, EVALUATOR_CACHE_TTL_SECONDS=3600)
        evaluator = Evaluator(client, settings=settings)

        fragment = _MockFragment([{"name": "task1", "status": "completed"}])

        decision1 = await evaluator.evaluate(fragment, goal="Complete the workflow")
        decision2 = await evaluator.evaluate(fragment, goal="Verify the results")

        assert decision1 == EvaluatorDecision.DONE
        assert decision2 == EvaluatorDecision.DONE
        # LLM should be called twice because goals differ
        assert len(client.complete_calls) == 2

    @pytest.mark.asyncio()
    async def test_evaluator_cache_disabled(self):
        """When cache is disabled, every call hits the LLM."""
        from celeste.core.evaluator import Evaluator

        client = _StubLLMClient(response_content="DONE\nGoal achieved.")
        settings = EngineSettings(EVALUATOR_CACHE_ENABLED=False, EVALUATOR_CACHE_TTL_SECONDS=3600)
        evaluator = Evaluator(client, settings=settings)

        fragment = _MockFragment([{"name": "task1", "status": "completed"}])
        goal = "Complete the workflow"

        await evaluator.evaluate(fragment, goal=goal)
        await evaluator.evaluate(fragment, goal=goal)

        assert len(client.complete_calls) == 2

    @pytest.mark.asyncio()
    async def test_evaluator_cache_expires(self):
        """Cached decision should expire after TTL."""
        from celeste.core.evaluator import Evaluator

        client = _StubLLMClient(response_content="DONE\nGoal achieved.")
        settings = EngineSettings(EVALUATOR_CACHE_ENABLED=True, EVALUATOR_CACHE_TTL_SECONDS=0)
        evaluator = Evaluator(client, settings=settings)

        fragment = _MockFragment([{"name": "task1", "status": "completed"}])
        goal = "Complete the workflow"

        await evaluator.evaluate(fragment, goal=goal)
        time.sleep(0.01)  # wait for TTL to expire
        await evaluator.evaluate(fragment, goal=goal)

        assert len(client.complete_calls) == 2

    def test_evaluator_cache_uses_monotonic_clock(self, monkeypatch):
        """F007: Cache TTL must use time.monotonic() (not time.time()) so that
        NTP step adjustments do not cause stale entries to persist forever.

        With time.time() (wall-clock), if the clock jumps BACKWARD, expires_at
        (set to wall_clock + TTL) ends up "in the future" of the new clock, so
        time.time() > expires_at is False and the entry is never evicted.

        We directly assert that the cache implementation reads
        ``time.monotonic()`` (not ``time.time()``) when computing TTL.
        """
        from celeste.core import evaluator as evaluator_module
        from celeste.core.evaluator import Evaluator, EvaluatorDecision

        client = _StubLLMClient(response_content="DONE\nGoal achieved.")
        settings = EngineSettings(EVALUATOR_CACHE_ENABLED=True, EVALUATOR_CACHE_TTL_SECONDS=60)
        evaluator = Evaluator(client, settings=settings)

        fragment = _MockFragment([{"name": "task1", "status": "completed"}])
        goal = "Complete the workflow"
        cache_key = evaluator._make_cache_key(fragment, goal)

        calls = {"time": 0, "monotonic": 0}

        def fake_time() -> float:
            calls["time"] += 1
            # Wall clock DOES NOT advance. NTP step simulates no time passing.
            return 1000.0

        def fake_monotonic() -> float:
            calls["monotonic"] += 1
            # Monotonic clock advances past TTL.
            n = calls["monotonic"]
            # First call (set): 100.0. Second call (get): 200.0 > 160.0 (TTL).
            return 100.0 if n == 1 else 200.0

        monkeypatch.setattr(evaluator_module.time, "time", fake_time)
        monkeypatch.setattr(evaluator_module.time, "monotonic", fake_monotonic)

        evaluator._set_cached(cache_key, EvaluatorDecision.DONE)
        result = evaluator._get_cached(cache_key)

        # Under correct (monotonic-based) impl: monotonic advances past
        # expires_at -> entry evicted -> result is None.
        # Under buggy (time.time()) impl: time is frozen at 1000.0, so
        # expires_at = 1060.0 and 1000.0 > 1060.0 is False -> entry returned.
        assert result is None, (
            "F007: cache TTL must use time.monotonic(), not time.time(); "
            "monotonic advances past TTL but time.time() does not."
        )
        # And the implementation must actually call monotonic() at least once
        # for each of _set_cached and _get_cached.
        assert calls["monotonic"] >= 2, (
            f"F007: expected at least 2 calls to time.monotonic() "
            f"(one in _set_cached, one in _get_cached), got {calls['monotonic']}"
        )


# ===========================================================================
# Evaluator prompt structure
# ===========================================================================


class TestEvaluatorPrompt:
    """Tests for the prompt sent to the LLM."""

    @pytest.mark.asyncio()
    async def test_evaluator_prompt_includes_goal(self):
        """The prompt sent to the LLM must include the goal."""
        from celeste.core.evaluator import Evaluator

        client = _StubLLMClient(response_content="DONE\nGoal achieved.")
        evaluator = Evaluator(client)

        fragment = _MockFragment([{"name": "task1", "status": "completed"}])
        goal = "Analyze sales data and generate report"
        await evaluator.evaluate(fragment, goal=goal)

        call = client.complete_calls[0]
        messages = call["messages"]
        all_content = " ".join(m.content for m in messages)
        assert goal in all_content

    @pytest.mark.asyncio()
    async def test_evaluator_prompt_includes_fragment(self):
        """The prompt sent to the LLM must include the fragment summary."""
        from celeste.core.evaluator import Evaluator

        client = _StubLLMClient(response_content="DONE\nGoal achieved.")
        evaluator = Evaluator(client)

        fragment = _MockFragment([{"name": "task1", "status": "completed"}])
        await evaluator.evaluate(fragment, goal="Complete the workflow")

        call = client.complete_calls[0]
        messages = call["messages"]
        all_content = " ".join(m.content for m in messages)
        assert "task1" in all_content or "Recent tasks" in all_content

    @pytest.mark.asyncio()
    async def test_evaluator_uses_low_temperature(self):
        """Evaluation should use temperature=0 for deterministic output."""
        from celeste.core.evaluator import Evaluator

        client = _StubLLMClient(response_content="DONE\nGoal achieved.")
        evaluator = Evaluator(client)

        fragment = _MockFragment([{"name": "task1", "status": "completed"}])
        await evaluator.evaluate(fragment, goal="Complete the workflow")

        call = client.complete_calls[0]
        assert call["temperature"] == 0.0
