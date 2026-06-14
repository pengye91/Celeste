"""Tests for the OPA-loop USD cost budget (TODO-6).

Follows strict TDD. Covers:
- MAX_LLM_COST_USD / MAX_LLM_COST_USD_PER_1K_TOKENS defaults + validation.
- run() escalates with reason="cost_budget_exceeded" when the running token
  estimate crosses the budget.
- run(max_llm_cost_usd=...) overrides the setting.
- run(max_llm_cost_usd=0) disables the check.
- _estimate_cost_usd math matches MAX_LLM_COST_USD_PER_1K_TOKENS.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from celeste.config.settings import EngineSettings
from celeste.core.opa_loop import OPALoop
from celeste.core.planner import DAGFragment, DAGNode
from celeste.core.evaluator import EvaluatorDecision

SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


# ---------------------------------------------------------------------------
# Stubs (minimal, mirroring tests/test_opa_loop.py)
# ---------------------------------------------------------------------------


class _StubAgent:
    async def call_tool(self, name, arguments=None, timeout_ms=None):
        return {"files": {}} if name == "snapshot" else {"success": True}

    async def list_tools(self):
        return []


class _StubPlanner:
    """Minimal planner stub that stashes realistic per-cycle LLM usage.

    Mirrors the real Planner.plan() convention (fragment._usage), so the
    OPA loop's real-usage token/cost accounting has something to harvest
    now that the per-cycle ``+= 100`` heuristic is gone (TODO-18).
    """

    def __init__(self, fragment: DAGFragment, total_tokens: int = 100):
        self._fragment = fragment
        self._total_tokens = total_tokens

    async def plan(self, goal, observation=None, tool_schemas=None, history=None, timeout_ms=60000):
        setattr(
            self._fragment,
            "_usage",
            {
                "prompt_tokens": self._total_tokens // 2,
                "completion_tokens": self._total_tokens - self._total_tokens // 2,
                "total_tokens": self._total_tokens,
            },
        )
        return self._fragment


class _StubEvaluator:
    def __init__(self, decision: EvaluatorDecision = EvaluatorDecision.CONTINUE):
        self._decision = decision

    async def evaluate(self, fragment, goal):
        return self._decision


def _fragment() -> DAGFragment:
    return DAGFragment(
        nodes=[DAGNode(name="step", task_type="tool_execution", command="echo", arguments={})],
        reasoning="r",
        goal_achieved=False,
    )


# ---------------------------------------------------------------------------
# Settings contract
# ---------------------------------------------------------------------------


def test_cost_budget_defaults():
    s = EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL)
    assert s.MAX_LLM_COST_USD == 5.0
    assert s.MAX_LLM_COST_USD_PER_1K_TOKENS == 0.03


def test_cost_budget_negative_rejected():
    with pytest.raises(ValidationError):
        EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL, MAX_LLM_COST_USD=-1.0)


def test_cost_per_1k_nonpositive_rejected():
    with pytest.raises(ValidationError):
        EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL, MAX_LLM_COST_USD_PER_1K_TOKENS=0.0)


# ---------------------------------------------------------------------------
# _estimate_cost_usd math
# ---------------------------------------------------------------------------


def test_estimate_cost_usd_uses_per_1k_setting():
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_LLM_COST_USD_PER_1K_TOKENS=0.03,
    )
    loop = OPALoop(
        agent=_StubAgent(),
        planner=_StubPlanner(_fragment()),
        evaluator=_StubEvaluator(),
        settings=settings,
    )
    # 1000 tokens * $0.03/1k = $0.03
    assert loop._estimate_cost_usd(1000) == pytest.approx(0.03)
    assert loop._estimate_cost_usd(0) == 0.0


# ---------------------------------------------------------------------------
# OPA-loop budget enforcement
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _reset_db_module():
    import celeste.database.db as db_mod

    db_mod._engine = None
    db_mod._async_session_factory = None
    yield
    if db_mod._engine is not None:
        try:
            await db_mod._engine.dispose()
        except Exception:
            pass
    db_mod._engine = None
    db_mod._async_session_factory = None


async def test_run_escalates_when_cost_budget_exceeded():
    """run() must escalate with reason=cost_budget_exceeded when the estimate crosses the budget."""
    # With per_1k=0.03 and budget=$0.012, crossing happens at ~400 tokens
    # (4 cycles * 100 tokens/cycle harvested from the stub planner usage).
    # max_cycles=200 keeps the cycle limit out of the way; max_llm_tokens
    # =100000 keeps token limit out too.
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_OPA_CYCLES=200,
        MAX_LLM_TOKENS=100000,
        MAX_LLM_COST_USD=0.012,
        MAX_LLM_COST_USD_PER_1K_TOKENS=0.03,
    )
    loop = OPALoop(
        agent=_StubAgent(),
        planner=_StubPlanner(_fragment()),
        evaluator=_StubEvaluator(),
        settings=settings,
    )
    result = await loop.run(goal="cost budget test")

    assert result.status == "escalated"
    assert result.reason == "cost_budget_exceeded"
    # The budget is crossed during the 4th cycle (300 -> 400 tokens = $0.012),
    # where tokens come from stub planner usage (100/cycle), not a heuristic.
    assert result.cycle_count == 4


async def test_run_cost_budget_override_disables_it():
    """max_llm_cost_usd=0 disables the cost check entirely."""
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_OPA_CYCLES=2,  # cycle limit stops the loop, not the budget
        MAX_LLM_TOKENS=100000,
        MAX_LLM_COST_USD=0.012,  # would trip very early if applied
    )
    loop = OPALoop(
        agent=_StubAgent(),
        planner=_StubPlanner(_fragment()),
        evaluator=_StubEvaluator(),
        settings=settings,
    )
    result = await loop.run(goal="disabled budget", max_llm_cost_usd=0)

    # Budget disabled -> the cycle limit is what escalates instead.
    assert result.reason == "max_cycles_exceeded"


async def test_run_cost_budget_override_tighter_than_setting():
    """max_llm_cost_usd override must win over the setting."""
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_OPA_CYCLES=200,
        MAX_LLM_TOKENS=100000,
        MAX_LLM_COST_USD=100.0,  # very loose setting
    )
    loop = OPALoop(
        agent=_StubAgent(),
        planner=_StubPlanner(_fragment()),
        evaluator=_StubEvaluator(),
        settings=settings,
    )
    # Tighter override: $0.003 * (100 tokens/cycle from stub usage) trips on cycle 1.
    result = await loop.run(goal="override", max_llm_cost_usd=0.003)

    assert result.status == "escalated"
    assert result.reason == "cost_budget_exceeded"
    assert result.cycle_count == 1


async def test_default_budget_does_not_trip_short_workflow():
    """A short workflow must not be escalated by the default $5 budget."""
    settings = EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,
        MAX_OPA_CYCLES=2,
        MAX_LLM_TOKENS=100000,
        MAX_LLM_COST_USD=5.0,  # default
    )
    loop = OPALoop(
        agent=_StubAgent(),
        planner=_StubPlanner(_fragment()),
        evaluator=_StubEvaluator(),
        settings=settings,
    )
    result = await loop.run(goal="short workflow")

    # 2 cycles * 100 tokens = $0.006, well under $5. Cycle limit trips.
    assert result.reason == "max_cycles_exceeded"
