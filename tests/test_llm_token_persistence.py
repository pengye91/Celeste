"""
Tests for LLM token usage persistence on Workflow.

Covers the bug where ``Planner.plan()`` discards ``LLMResponse.usage``
returned by the underlying ``structured_output`` call. After the fix:

- ``Planner.plan()`` exposes usage (either by storing it on the
  ``DAGFragment`` via a private attribute, or via a side-channel).
- ``OPALoop.run()`` accumulates usage from every planning call into the
  ``llm_tokens_accumulated`` counter and writes that counter onto the
  ``Workflow`` row.
- ``GET /api/workflows/{id}/metrics`` returns the persisted total.

TDD mandate: these tests fail before the implementation and pass after.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.evaluator import EvaluatorDecision
from celeste.core.opa_loop import OPALoop
from celeste.core.planner import DAGFragment, DAGNode
from celeste.database.db import close_db, get_session, init_db
from celeste.database.models import Workflow, WorkflowStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_node(name: str, command: str = "run_command") -> DAGNode:
    return DAGNode(
        name=name,
        task_type="tool_execution",
        command=command,
        arguments={},
        dependencies=[],
    )


def _make_fragment(nodes=None, goal_achieved=False) -> DAGFragment:
    return DAGFragment(
        nodes=nodes or [],
        reasoning="fragment",
        estimated_remaining=1,
        goal_achieved=goal_achieved,
    )


class _StubAgent:
    """Stub EnvironmentAgent for testing."""

    def __init__(self, snapshot_result: dict[str, Any] | None = None) -> None:
        self._snapshot = snapshot_result or {"files": {}}

    async def call_tool(self, name: str, arguments: dict | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        return {"success": True}

    async def list_tools(self) -> list[dict[str, Any]]:
        return []


class _UsageAwareStubPlanner:
    """Stub planner that returns a fragment annotated with usage info.

    The planner mirrors the contract we want from the real Planner after
    the fix: it stamps ``_usage`` onto the returned ``DAGFragment`` so the
    OPA loop can accumulate tokens without changing the public return
    type.
    """

    def __init__(self, usage: dict[str, int], goal_achieved: bool = True) -> None:
        self._usage = usage
        self._goal_achieved = goal_achieved
        self.plan_calls = 0

    async def plan(
        self,
        goal: str,
        observation: dict | None = None,
        tool_schemas: list[dict] | None = None,
        history: list[dict] | None = None,
        timeout_ms: int = 60000,
    ) -> DAGFragment:
        self.plan_calls += 1
        fragment = _make_fragment(
            nodes=[_make_tool_node("step1")],
            goal_achieved=self._goal_achieved,
        )
        # Stash usage for the OPA loop to harvest. Using setattr keeps the
        # Pydantic DAGFragment schema unchanged.
        setattr(fragment, "_usage", dict(self._usage))
        return fragment


class _StubEvaluator:
    def __init__(self, decision: EvaluatorDecision | None = None) -> None:
        self._decision = decision or EvaluatorDecision.DONE

    async def evaluate(self, fragment: Any, goal: str) -> EvaluatorDecision:
        return self._decision


class _UsageAwareStubEvaluator:
    """Stub evaluator that returns a decision carrying per-call LLM usage.

    Mirrors what the real ``Evaluator.evaluate()`` does after TODO-18: it
    stamps ``usage`` onto the returned decision so the OPA loop can
    accumulate evaluator tokens. Critically, it clones the singleton
    before attaching metadata -- the same discipline the real evaluator
    now follows to avoid leaking usage across workflows.
    """

    def __init__(
        self,
        decision: EvaluatorDecision | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        self._decision = decision or EvaluatorDecision.DONE
        self._usage = usage or {}

    async def evaluate(self, fragment: Any, goal: str) -> EvaluatorDecision:
        decision = self._decision._clone()
        decision.usage = dict(self._usage)
        return decision


@pytest.fixture(autouse=True)
async def _reset_db():
    """Ensure a fresh in-memory DB for each test."""
    import celeste.database.db as db_mod

    db_mod._engine = None
    db_mod._async_session_factory = None
    yield
    try:
        await close_db()
    except Exception:
        pass
    db_mod._engine = None
    db_mod._async_session_factory = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opa_loop_persists_planner_usage_onto_workflow_row():
    """OPA loop writes planner usage into Workflow.llm_tokens_accumulated."""
    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=5,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    agent = _StubAgent()
    # usage total = 150/cycle. With the heuristic gone (TODO-18), the
    # accumulated total equals exactly the harvested planner usage.
    planner = _UsageAwareStubPlanner(
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    )
    evaluator = _StubEvaluator()

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    result = await loop.run(goal="token persistence test")

    assert result.workflow_id is not None

    async with get_session() as session:
        wf = (
            await session.execute(select(Workflow).where(Workflow.id == result.workflow_id))
        ).scalar_one()

        assert hasattr(wf, "llm_tokens_accumulated"), (
            "Workflow model is missing llm_tokens_accumulated column"
        )
        assert wf.llm_tokens_accumulated == 150, (
            f"Expected Workflow.llm_tokens_accumulated == 150, got {wf.llm_tokens_accumulated}"
        )


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_persisted_token_total():
    """GET /api/workflows/{id}/metrics returns the persisted total."""
    from celeste.api.app import create_app

    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=5,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    agent = _StubAgent()
    planner = _UsageAwareStubPlanner(
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    )
    evaluator = _StubEvaluator()

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    result = await loop.run(goal="metrics endpoint token test")

    assert result.workflow_id is not None

    async with get_session() as session:
        wf = (
            await session.execute(select(Workflow).where(Workflow.id == result.workflow_id))
        ).scalar_one()
        expected = wf.llm_tokens_accumulated
        wf_id = str(wf.id)

    # Build the FastAPI app on the same in-memory database. The
    # create_app factory uses the global session factory that init_db
    # already configured.
    app = create_app(settings=settings)

    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/workflows/{wf_id}/metrics")
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["llm_tokens_accumulated"] is not None, (
                f"metrics returned llm_tokens_accumulated=None, expected {expected}"
            )
            assert data["llm_tokens_accumulated"] == expected
            assert data["llm_tokens_accumulated"] == 150
    finally:
        await lifespan_cm.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_opa_loop_accumulates_evaluator_usage():
    """TODO-18: evaluator LLM calls contribute to llm_tokens_accumulated.

    With planner usage of 150 and evaluator usage of 75 in a single
    completed cycle, the workflow row must hold 225 tokens -- not just the
    planner's 150. This locks in the evaluator-usage harvest added in
    TODO-18.
    """
    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=5,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    agent = _StubAgent()
    planner = _UsageAwareStubPlanner(
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    )
    # Evaluator returns DONE (loop runs exactly one cycle) with 75 tokens.
    evaluator = _UsageAwareStubEvaluator(
        decision=EvaluatorDecision.DONE,
        usage={"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75},
    )

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    result = await loop.run(goal="evaluator usage test")

    assert result.status == "completed"
    assert result.llm_tokens_accumulated == 225, (
        f"Expected 150 (planner) + 75 (evaluator) = 225, "
        f"got {result.llm_tokens_accumulated}"
    )

    async with get_session() as session:
        wf = (
            await session.execute(select(Workflow).where(Workflow.id == result.workflow_id))
        ).scalar_one()
        assert wf.llm_tokens_accumulated == 225


@pytest.mark.asyncio
async def test_evaluator_usage_does_not_leak_across_workflows():
    """TODO-18 regression guard: singleton usage must not leak between runs.

    The canonical EvaluatorDecision singletons are process-global. Before
    the _clone() fix, attaching ``usage`` to a returned decision mutated
    the singleton, so a second workflow that returned the same decision
    inherited the first workflow's usage. This test runs two workflows
    back-to-back with different evaluator usage and asserts the second
    workflow's token total reflects only its own usage.
    """
    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=5,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    # First workflow: planner 150 + evaluator 75 = 225.
    loop1 = OPALoop(
        agent=_StubAgent(),
        planner=_UsageAwareStubPlanner(
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        ),
        evaluator=_UsageAwareStubEvaluator(
            decision=EvaluatorDecision.DONE,
            usage={"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75},
        ),
        settings=settings,
    )
    result1 = await loop1.run(goal="first workflow")
    assert result1.llm_tokens_accumulated == 225

    # Second workflow: planner 200 + evaluator 0 (no usage attached).
    # If the singleton leaked, the evaluator's stale 75 would inflate this.
    loop2 = OPALoop(
        agent=_StubAgent(),
        planner=_UsageAwareStubPlanner(
            usage={"prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200}
        ),
        evaluator=_StubEvaluator(decision=EvaluatorDecision.DONE),
        settings=settings,
    )
    result2 = await loop2.run(goal="second workflow")
    assert result2.llm_tokens_accumulated == 200, (
        f"Expected 200 (no leaked evaluator usage), got {result2.llm_tokens_accumulated}"
    )