"""
Evaluator for the Celeste-DAG OPA (Observe-Plan-Act) Loop.

The Evaluator is the "Cognitive Left Brain" that decides whether a workflow
goal has been achieved based on recently executed tasks.  It is model-agnostic
-- any ``BaseLLMClient`` adapter can be used.

Public API:
- EvaluatorDecision -- decision enum with reason support
- Evaluator -- LLM-backed evaluator that caches results
"""

from __future__ import annotations

import hashlib
import time
from enum import Enum
from typing import Any

from celeste_dag.core.llm.base import BaseLLMClient, LLMMessage
from celeste_dag.config.settings import EngineSettings, get_settings


# =========================================================================
# EvaluatorDecision
# =========================================================================


class _EvaluatorDecisionMeta(type):
    """Metaclass that enables string comparison for EvaluatorDecision members."""

    def __getattr__(cls, name: str) -> "EvaluatorDecision":
        for member in cls._members_.values():
            if member.name == name:
                return member
        raise AttributeError(f"{cls.__name__} has no attribute '{name}'")


class EvaluatorDecision(metaclass=_EvaluatorDecisionMeta):
    """Decision returned by the Evaluator.

    Supports comparison with strings:
        decision == "DONE"  # True
    """

    _members_: dict[str, "EvaluatorDecision"] = {}

    def __init__(self, name: str, reason: str = "") -> None:
        self.name = name
        self.reason = reason
        EvaluatorDecision._members_[name] = self

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EvaluatorDecision):
            return self.name == other.name
        if isinstance(other, str):
            return self.name == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return f"EvaluatorDecision.{self.name}(reason={self.reason!r})"


# Create singleton instances
EvaluatorDecision.DONE = EvaluatorDecision("DONE")
EvaluatorDecision.REPLAN = EvaluatorDecision("REPLAN")
EvaluatorDecision.ESCALATE = EvaluatorDecision("ESCALATE")
EvaluatorDecision.CONTINUE = EvaluatorDecision("CONTINUE")


# =========================================================================
# System prompt
# =========================================================================

_SYSTEM_PROMPT = """\
You are a workflow evaluator. Given a workflow goal and the results of recently \
executed tasks, decide whether the goal is achieved, needs replanning, should \
continue, or requires human escalation.
"""

_USER_PROMPT_TEMPLATE = """\
Goal: {goal}

Recent tasks executed:
{fragment_summary}

Respond with exactly one of: DONE, REPLAN, ESCALATE, CONTINUE
Include a brief reason.
"""


# =========================================================================
# Evaluator
# =========================================================================


class _CacheEntry:
    """Internal cache entry with expiration timestamp."""

    def __init__(self, decision: EvaluatorDecision, expires_at: float) -> None:
        self.decision = decision
        self.expires_at = expires_at


class Evaluator:
    """OPA Loop evaluator: decides whether a workflow goal is achieved.

    Uses an LLM to evaluate progress and caches results to reduce redundant
    LLM calls.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        settings: EngineSettings | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._settings = settings or get_settings()
        self._cache: dict[str, _CacheEntry] = {}

    def _make_cache_key(self, fragment: Any, goal: str) -> str:
        """Create a deterministic cache key from fragment + goal."""
        fragment_repr = repr(fragment)
        combined = f"{goal}:{fragment_repr}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def _get_cached(self, cache_key: str) -> EvaluatorDecision | None:
        """Return cached decision if present and not expired."""
        if not self._settings.EVALUATOR_CACHE_ENABLED:
            return None
        entry = self._cache.get(cache_key)
        if entry is None:
            return None
        if time.time() > entry.expires_at:
            del self._cache[cache_key]
            return None
        return entry.decision

    def _set_cached(self, cache_key: str, decision: EvaluatorDecision) -> None:
        """Store decision in cache with TTL."""
        if not self._settings.EVALUATOR_CACHE_ENABLED:
            return
        expires_at = time.time() + self._settings.EVALUATOR_CACHE_TTL_SECONDS
        self._cache[cache_key] = _CacheEntry(decision=decision, expires_at=expires_at)

    @staticmethod
    def _parse_response(content: str) -> EvaluatorDecision:
        """Parse LLM response into an EvaluatorDecision.

        Expected format: first line is one of DONE, REPLAN, ESCALATE, CONTINUE
        followed by an optional reason.
        """
        lines = content.strip().splitlines()
        if not lines:
            return EvaluatorDecision.CONTINUE

        decision_line = lines[0].strip().upper()
        reason = lines[1].strip() if len(lines) > 1 else ""

        if decision_line == "DONE":
            decision = EvaluatorDecision.DONE
        elif decision_line == "REPLAN":
            decision = EvaluatorDecision.REPLAN
        elif decision_line == "ESCALATE":
            decision = EvaluatorDecision.ESCALATE
        else:
            decision = EvaluatorDecision.CONTINUE

        decision.reason = reason
        return decision

    async def evaluate(self, fragment: Any, goal: str) -> EvaluatorDecision:
        """Evaluate whether the workflow goal is achieved.

        Args:
            fragment: The recently executed workflow fragment (any object with
                a meaningful ``repr``).
            goal: The workflow goal string.

        Returns:
            An EvaluatorDecision indicating the next action.
        """
        cache_key = self._make_cache_key(fragment, goal)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        fragment_summary = repr(fragment)
        user_prompt = _USER_PROMPT_TEMPLATE.format(
            goal=goal,
            fragment_summary=fragment_summary,
        )

        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = await self._llm_client.complete(
            messages,
            temperature=0.0,
            max_tokens=256,
        )

        decision = self._parse_response(response.content)
        self._set_cached(cache_key, decision)
        return decision
