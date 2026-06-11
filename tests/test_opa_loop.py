"""
Tests for the OPA Loop (Observe-Plan-Act) workflow orchestrator.

Follows strict TDD: these tests are written BEFORE the implementation.
Covers:
- WorkflowResult dataclass
- OPALoop initialization and run() lifecycle
- Single-cycle goal achievement
- Multi-cycle goal achievement
- Tier 1: retry transient failures
- Tier 1: retry exhausted escalates to Tier 2
- Tier 2: scoped replan
- Tier 3: full replan
- Max cycles exceeded safety limit
- Token budget exceeded safety limit
- Evaluator returns ESCALATE
- Agent unreachable during observation
- Sequential planning (no pipeline)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from celeste.config.settings import EngineSettings
from celeste.core.evaluator import EvaluatorDecision
from celeste.core.exceptions import PlannerTimeoutError
from celeste.core.planner import DAGFragment, DAGNode
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Helpers -- test doubles
# ---------------------------------------------------------------------------


def _make_fragment(nodes: list[DAGNode] | None = None, goal_achieved: bool = False) -> DAGFragment:
    """Create a DAGFragment with the given nodes."""
    return DAGFragment(
        nodes=nodes or [],
        reasoning="test fragment",
        estimated_remaining=1,
        goal_achieved=goal_achieved,
    )


def _make_tool_node(name: str, command: str = "run_command", args: dict[str, Any] | None = None) -> DAGNode:
    """Create a simple tool execution DAGNode."""
    return DAGNode(
        name=name,
        task_type="tool_execution",
        command=command,
        arguments=args or {},
        dependencies=[],
    )


class _StubAgent:
    """Stub EnvironmentAgent for testing."""

    def __init__(
        self,
        snapshot_result: dict[str, Any] | Exception | None = None,
        list_tools_result: list[dict[str, Any]] | None = None,
        tool_results: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.call_tool_calls: list[dict[str, Any]] = []
        self._snapshot_result: dict[str, Any] | Exception = snapshot_result or {"files": {}}
        self._list_tools_result = list_tools_result or []
        self._tool_results = tool_results or {}

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        self.call_tool_calls.append({"name": name, "arguments": arguments, "timeout_ms": timeout_ms})
        if name == "snapshot":
            if isinstance(self._snapshot_result, Exception):
                raise self._snapshot_result
            return self._snapshot_result
        return self._tool_results.get(name, {"success": True})

    async def list_tools(self) -> list[dict[str, Any]]:
        return self._list_tools_result


class _StubPlanner:
    """Stub Planner for testing."""

    def __init__(
        self,
        fragments: list[DAGFragment] | None = None,
        side_effect: Any = None,
    ) -> None:
        self.plan_calls: list[dict[str, Any]] = []
        self._fragments = fragments or []
        self._call_count = 0
        self._side_effect = side_effect

    async def plan(
        self,
        goal: str,
        observation: dict | None = None,
        tool_schemas: list[dict] | None = None,
        history: list[dict] | None = None,
        timeout_ms: int = 60000,
    ) -> DAGFragment:
        # Snapshot the history so later mutations in OPALoop.run() do not affect
        # the recorded plan call.
        self.plan_calls.append({
            "goal": goal,
            "observation": observation,
            "tool_schemas": tool_schemas,
            "history": list(history) if history is not None else history,
            "timeout_ms": timeout_ms,
        })
        if self._side_effect is not None:
            if callable(self._side_effect):
                result = self._side_effect()
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            raise self._side_effect
        idx = min(self._call_count, len(self._fragments) - 1)
        fragment = self._fragments[idx]
        self._call_count += 1
        return fragment


class _StubEvaluator:
    """Stub Evaluator for testing."""

    def __init__(self, decisions: list[EvaluatorDecision] | None = None) -> None:
        self.evaluate_calls: list[dict[str, Any]] = []
        self._decisions = decisions or []
        self._call_count = 0

    async def evaluate(self, fragment: Any, goal: str) -> EvaluatorDecision:
        self.evaluate_calls.append({"fragment": fragment, "goal": goal})
        idx = min(self._call_count, len(self._decisions) - 1)
        decision = self._decisions[idx]
        self._call_count += 1
        return decision


# Need asyncio import for iscoroutine check
import asyncio


# ===========================================================================
# WorkflowResult
# ===========================================================================


def test_workflow_result_creation():
    """WorkflowResult can be created with all fields."""
    from celeste.core.opa_loop import WorkflowResult

    result = WorkflowResult(
        status="completed",
        reason="Goal achieved",
        cycle_count=1,
        llm_tokens_accumulated=100,
    )
    assert result.status == "completed"
    assert result.reason == "Goal achieved"
    assert result.cycle_count == 1
    assert result.llm_tokens_accumulated == 100


def test_workflow_result_defaults():
    """WorkflowResult reason defaults to None."""
    from celeste.core.opa_loop import WorkflowResult

    result = WorkflowResult(status="failed", cycle_count=0, llm_tokens_accumulated=0)
    assert result.reason is None


# ===========================================================================
# OPALoop initialization
# ===========================================================================


def test_opa_loop_init():
    """OPALoop can be initialized with agent, planner, evaluator."""
    from celeste.core.opa_loop import OPALoop

    agent = _StubAgent()
    planner = _StubPlanner()
    evaluator = _StubEvaluator()

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    assert loop._agent is agent
    assert loop._planner is planner
    assert loop._evaluator is evaluator


def test_opa_loop_init_with_settings():
    """OPALoop can be initialized with custom settings."""
    from celeste.core.opa_loop import OPALoop

    settings = EngineSettings(MAX_OPA_CYCLES=50, MAX_LLM_TOKENS=10000)
    loop = OPALoop(
        agent=_StubAgent(),
        planner=_StubPlanner(),
        evaluator=_StubEvaluator(),
        settings=settings,
    )
    assert loop._settings.MAX_OPA_CYCLES == 50
    assert loop._settings.MAX_LLM_TOKENS == 10000


# ===========================================================================
# OPALoop run() -- basic success paths
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_goal_achieved_in_one_cycle():
    """Goal achieved in a single OPA cycle returns completed status."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {"/tmp": ["a.txt"]}})
    fragment = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=True)
    planner = _StubPlanner(fragments=[fragment])
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.DONE])

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="test goal")

    assert isinstance(result, WorkflowResult)
    assert result.status == "completed"
    assert result.cycle_count == 1
    assert result.reason == "Goal achieved"
    assert len(planner.plan_calls) == 1
    assert len(evaluator.evaluate_calls) == 1


@pytest.mark.asyncio
async def test_opa_loop_goal_achieved_in_n_cycles():
    """Goal achieved after multiple OPA cycles returns completed status."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {}})
    fragment1 = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
    fragment2 = _make_fragment(nodes=[_make_tool_node("step2")], goal_achieved=False)
    fragment3 = _make_fragment(nodes=[_make_tool_node("step3")], goal_achieved=True)
    planner = _StubPlanner(fragments=[fragment1, fragment2, fragment3])
    evaluator = _StubEvaluator(decisions=[
        EvaluatorDecision.CONTINUE,
        EvaluatorDecision.CONTINUE,
        EvaluatorDecision.DONE,
    ])

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="multi-step goal")

    assert isinstance(result, WorkflowResult)
    assert result.status == "completed"
    assert result.cycle_count == 3
    assert result.reason == "Goal achieved"
    assert len(planner.plan_calls) == 3
    assert len(evaluator.evaluate_calls) == 3


# ===========================================================================
# Tier 1: retry transient failures
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_tier1_retry_transient_failure():
    """Tier 1 retries transient tool failures up to 3 times with backoff."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    # First 2 calls fail transiently, 3rd succeeds
    agent = _StubAgent(
        snapshot_result={"files": {}},
        tool_results={"run_command": {"error": "transient", "retryable": True}},
    )
    # Override call_tool to fail twice then succeed
    fail_count = 0
    original_call_tool = agent.call_tool

    async def flaky_call_tool(name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        nonlocal fail_count
        if name == "run_command" and fail_count < 2:
            fail_count += 1
            return {"error": "transient", "retryable": True}
        return {"success": True}

    agent.call_tool = flaky_call_tool

    fragment = _make_fragment(
        nodes=[_make_tool_node("step1", command="run_command", args={"command": "ls"})],
        goal_achieved=True,
    )
    planner = _StubPlanner(fragments=[fragment])
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.DONE])

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="retry test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "completed"
    assert fail_count == 2  # Retried twice before success


@pytest.mark.asyncio
async def test_opa_loop_tier1_retry_exhausted_escalates_to_tier2():
    """When Tier 1 retries are exhausted, the loop escalates to Tier 2 (replan)."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {}})
    # Always fail
    async def always_fail(name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        if name == "run_command":
            return {"error": "transient", "retryable": True}
        return {"success": True}

    agent.call_tool = always_fail

    fragment1 = _make_fragment(
        nodes=[_make_tool_node("step1", command="run_command")],
        goal_achieved=False,
    )
    fragment2 = _make_fragment(
        nodes=[_make_tool_node("step1_alt", command="run_command")],
        goal_achieved=True,
    )
    planner = _StubPlanner(fragments=[fragment1, fragment2])
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE, EvaluatorDecision.DONE])

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="retry exhausted test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "completed"
    # After 3 retries fail, planner is called again for replan
    assert len(planner.plan_calls) >= 2


# ===========================================================================
# Tier 2: scoped replan
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_tier2_scoped_replan():
    """Evaluator returning REPLAN triggers Tier 2 scoped replan."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {}})
    fragment1 = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
    fragment2 = _make_fragment(nodes=[_make_tool_node("step2")], goal_achieved=True)
    planner = _StubPlanner(fragments=[fragment1, fragment2])
    evaluator = _StubEvaluator(decisions=[
        EvaluatorDecision.REPLAN,
        EvaluatorDecision.DONE,
    ])

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="scoped replan test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "completed"
    assert len(planner.plan_calls) == 2
    # Second plan call should include history from first cycle
    assert planner.plan_calls[1]["history"] is not None
    assert len(planner.plan_calls[1]["history"]) > 0


# ===========================================================================
# Tier 3: full replan
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_tier3_full_replan():
    """Drastic environment changes trigger Tier 3 full replan."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    # Snapshot changes drastically between cycles
    snapshots = [
        {"files": {"/tmp": ["a.txt"]}},
        {"files": {"/tmp": ["b.txt", "c.txt"], "drastic_change": True}},
    ]
    snapshot_idx = 0

    async def changing_snapshot(name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        nonlocal snapshot_idx
        if name == "snapshot":
            result = snapshots[snapshot_idx]
            snapshot_idx = min(snapshot_idx + 1, len(snapshots) - 1)
            return result
        return {"success": True}

    agent = _StubAgent()
    agent.call_tool = changing_snapshot

    fragment1 = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
    fragment2 = _make_fragment(nodes=[_make_tool_node("step2")], goal_achieved=True)
    planner = _StubPlanner(fragments=[fragment1, fragment2])
    evaluator = _StubEvaluator(decisions=[
        EvaluatorDecision.CONTINUE,
        EvaluatorDecision.DONE,
    ])

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="full replan test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "completed"
    # Full replan should clear or significantly alter history
    assert len(planner.plan_calls) == 2


# ===========================================================================
# Safety limits
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_max_cycles_exceeded():
    """Exceeding MAX_OPA_CYCLES returns escalated WorkflowResult."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {}})
    fragment = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
    # Always return CONTINUE to keep cycling
    planner = _StubPlanner(fragments=[fragment])
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE])

    settings = EngineSettings(MAX_OPA_CYCLES=5)
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    result = await loop.run(goal="max cycles test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "escalated"
    assert result.reason == "max_cycles_exceeded"
    assert result.cycle_count == 5


@pytest.mark.asyncio
async def test_opa_loop_token_budget_exceeded():
    """Exceeding MAX_LLM_TOKENS returns escalated WorkflowResult."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {}})
    fragment = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
    planner = _StubPlanner(fragments=[fragment])
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE])

    settings = EngineSettings(MAX_OPA_CYCLES=100, MAX_LLM_TOKENS=2000)
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    result = await loop.run(goal="token budget test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "escalated"
    assert result.reason == "token_budget_exceeded"


# ===========================================================================
# History truncation
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_history_truncated():
    """History is truncated and summarized once it exceeds OPA_HISTORY_MAX_CYCLES."""
    from celeste.core.opa_loop import OPALoop

    agent = _StubAgent(snapshot_result={"files": {}})
    fragments = [
        _make_fragment(nodes=[_make_tool_node(f"step{i}")], goal_achieved=False)
        for i in range(5)
    ]
    planner = _StubPlanner(fragments=fragments)
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE] * 4 + [EvaluatorDecision.DONE])

    settings = EngineSettings(OPA_HISTORY_MAX_CYCLES=3, MAX_OPA_CYCLES=10)
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    await loop.run(goal="history truncation test")

    # Planner should receive at most max_cycles full entries plus one summary block.
    # With 5 cycles and max=3, we expect 1 summary block + 3 full entries = 4.
    final_history = planner.plan_calls[-1]["history"]
    assert len(final_history) <= 4


@pytest.mark.asyncio
async def test_opa_loop_history_summary_present():
    """Old cycles are summarized into a summary block, not dropped."""
    from celeste.core.opa_loop import OPALoop

    agent = _StubAgent(snapshot_result={"files": {}})
    fragments = [
        _make_fragment(nodes=[_make_tool_node(f"step{i}")], goal_achieved=False)
        for i in range(5)
    ]
    planner = _StubPlanner(fragments=fragments)
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE] * 4 + [EvaluatorDecision.DONE])

    settings = EngineSettings(OPA_HISTORY_MAX_CYCLES=3, MAX_OPA_CYCLES=10)
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    await loop.run(goal="history summary test")

    final_history = planner.plan_calls[-1]["history"]
    summary_blocks = [entry for entry in final_history if entry.get("_summary")]
    assert len(summary_blocks) >= 1
    summary_entries = summary_blocks[0].get("entries", [])
    assert len(summary_entries) >= 1
    for entry in summary_entries:
        assert "cycle" in entry
        assert "decision" in entry
        assert "completed_nodes" in entry


@pytest.mark.asyncio
async def test_opa_loop_history_zero_max():
    """With OPA_HISTORY_MAX_CYCLES=0, all old cycles are summarized."""
    from celeste.core.opa_loop import OPALoop

    agent = _StubAgent(snapshot_result={"files": {}})
    fragments = [
        _make_fragment(nodes=[_make_tool_node(f"step{i}")], goal_achieved=False)
        for i in range(3)
    ]
    planner = _StubPlanner(fragments=fragments)
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE] * 2 + [EvaluatorDecision.DONE])

    settings = EngineSettings(OPA_HISTORY_MAX_CYCLES=0, MAX_OPA_CYCLES=10)
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    await loop.run(goal="history zero max test")

    # Examine the history passed to the planner on the final planning call.
    final_history = planner.plan_calls[-1]["history"]
    # With max=0, every entry older than the current cycle is summarized. The
    # current cycle has not yet been appended when the planner is called, so the
    # planner history should contain only summary blocks (no full entries).
    assert all(entry.get("_summary") for entry in final_history)


@pytest.mark.asyncio
async def test_opa_loop_evaluator_returns_escalate():
    """Evaluator returning ESCALATE pauses workflow and returns paused WorkflowResult with reason."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult
    from celeste.database.db import close_db, get_session, init_db
    from celeste.database.models import Workflow, WorkflowStatus

    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=10,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    try:
        agent = _StubAgent(snapshot_result={"files": {}})
        fragment = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
        planner = _StubPlanner(fragments=[fragment])

        escalate_decision = EvaluatorDecision.ESCALATE
        escalate_decision.reason = "ambiguous goal"
        evaluator = _StubEvaluator(decisions=[escalate_decision])

        loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
        result = await loop.run(goal="escalate test")

        assert isinstance(result, WorkflowResult)
        assert result.status == "paused"
        assert result.reason == "ambiguous goal"
        assert result.cycle_count == 1
        assert result.workflow_id is not None

        async with get_session() as session:
            wf_result = await session.execute(
                select(Workflow).where(Workflow.id == result.workflow_id)
            )
            workflow = wf_result.scalar_one()
            assert workflow.status == WorkflowStatus.PAUSED
            assert workflow.paused_at is not None
            assert workflow.dag_definition.get("_opa_state") is not None
    finally:
        await close_db()


# ===========================================================================
# Error handling
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_agent_unreachable_during_observation():
    """Agent unreachable during observation returns failed WorkflowResult."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result=ConnectionError("agent unreachable"))
    planner = _StubPlanner()
    evaluator = _StubEvaluator()

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="unreachable test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "failed"
    assert result.reason == "agent_unreachable"
    assert result.cycle_count == 0


# ===========================================================================
# Planner timeout handling
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_planner_timeout_first_cycle_escalates():
    """Planner timeout on first cycle escalates since no progress was made."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {}})
    planner = _StubPlanner(side_effect=PlannerTimeoutError("LLM timeout"))
    evaluator = _StubEvaluator()

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="timeout test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "escalated"
    assert result.reason == "planner_timeout_no_progress"
    assert result.cycle_count == 1


@pytest.mark.asyncio
async def test_opa_loop_planner_timeout_later_cycle_retries():
    """Planner timeout after first cycle continues to retry next cycle."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {}})
    fragment1 = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
    fragment2 = _make_fragment(nodes=[_make_tool_node("step2")], goal_achieved=True)

    call_count = 0
    def planner_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fragment1
        if call_count == 2:
            raise PlannerTimeoutError("LLM timeout")
        return fragment2

    planner = _StubPlanner(side_effect=planner_side_effect)
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE, EvaluatorDecision.DONE])

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="timeout retry test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "completed"
    assert result.cycle_count == 3


# ===========================================================================
# Sequential planning (no pipeline)
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_sequential_planning_no_pipeline():
    """Nodes with dependencies are executed sequentially, respecting order."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    execution_order: list[str] = []

    async def tracking_call_tool(name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        if name != "snapshot":
            execution_order.append(name)
        return {"success": True}

    agent = _StubAgent()
    agent.call_tool = tracking_call_tool

    node1 = _make_tool_node("step1", command="cmd_a")
    node2 = _make_tool_node("step2", command="cmd_b")
    node2.dependencies = ["step1"]
    node3 = _make_tool_node("step3", command="cmd_c")
    node3.dependencies = ["step2"]

    fragment = _make_fragment(nodes=[node1, node2, node3], goal_achieved=True)
    planner = _StubPlanner(fragments=[fragment])
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.DONE])

    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator)
    result = await loop.run(goal="sequential test")

    assert isinstance(result, WorkflowResult)
    assert result.status == "completed"
    assert execution_order == ["cmd_a", "cmd_b", "cmd_c"]


# ===========================================================================
# WorkflowExecutor
# ===========================================================================


@pytest.mark.asyncio
async def test_workflow_executor_executes_nodes():
    """WorkflowExecutor executes each node via agent.call_tool()."""
    from celeste.core.opa_loop import WorkflowExecutor

    calls: list[dict[str, Any]] = []

    async def mock_call_tool(name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        calls.append({"name": name, "arguments": arguments})
        return {"success": True}

    agent = _StubAgent()
    agent.call_tool = mock_call_tool

    fragment = _make_fragment(nodes=[
        _make_tool_node("n1", command="cmd1", args={"x": 1}),
        _make_tool_node("n2", command="cmd2", args={"y": 2}),
    ])

    executor = WorkflowExecutor(agent)
    result = await executor.execute_fragment(fragment)

    assert len(calls) == 2
    assert calls[0]["name"] == "cmd1"
    assert calls[0]["arguments"] == {"x": 1}
    assert calls[1]["name"] == "cmd2"
    assert calls[1]["arguments"] == {"y": 2}
    assert result["completed"] == ["n1", "n2"]
    assert result["failed"] == []


@pytest.mark.asyncio
async def test_workflow_executor_tracks_failed_nodes():
    """WorkflowExecutor tracks which nodes failed."""
    from celeste.core.opa_loop import WorkflowExecutor

    async def mock_call_tool(name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        if name == "cmd2":
            return {"error": "failed"}
        return {"success": True}

    agent = _StubAgent()
    agent.call_tool = mock_call_tool

    fragment = _make_fragment(nodes=[
        _make_tool_node("n1", command="cmd1"),
        _make_tool_node("n2", command="cmd2"),
    ])

    executor = WorkflowExecutor(agent)
    result = await executor.execute_fragment(fragment)

    assert result["completed"] == ["n1"]
    assert result["failed"] == ["n2"]


@pytest.mark.asyncio
async def test_workflow_executor_respects_dependencies():
    """WorkflowExecutor executes nodes in dependency order."""
    from celeste.core.opa_loop import WorkflowExecutor

    execution_order: list[str] = []

    async def mock_call_tool(name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        execution_order.append(name)
        return {"success": True}

    agent = _StubAgent()
    agent.call_tool = mock_call_tool

    node1 = _make_tool_node("n1", command="cmd1")
    node2 = _make_tool_node("n2", command="cmd2")
    node2.dependencies = ["n1"]
    node3 = _make_tool_node("n3", command="cmd3")
    node3.dependencies = ["n2"]

    fragment = _make_fragment(nodes=[node3, node1, node2])  # Out of order

    executor = WorkflowExecutor(agent)
    await executor.execute_fragment(fragment)

    assert execution_order == ["cmd1", "cmd2", "cmd3"]


@pytest.mark.asyncio
async def test_workflow_executor_skips_dependents_of_failed_nodes():
    """WorkflowExecutor skips nodes that depend on failed nodes."""
    from celeste.core.opa_loop import WorkflowExecutor

    execution_order: list[str] = []

    async def mock_call_tool(name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        execution_order.append(name)
        if name == "cmd2":
            return {"error": "failed"}
        return {"success": True}

    agent = _StubAgent()
    agent.call_tool = mock_call_tool

    node1 = _make_tool_node("n1", command="cmd1")
    node2 = _make_tool_node("n2", command="cmd2")
    node2.dependencies = ["n1"]
    node3 = _make_tool_node("n3", command="cmd3")
    node3.dependencies = ["n2"]

    fragment = _make_fragment(nodes=[node1, node2, node3])

    executor = WorkflowExecutor(agent)
    result = await executor.execute_fragment(fragment)

    assert execution_order == ["cmd1", "cmd2"]
    assert "cmd3" not in execution_order
    assert result["completed"] == ["n1"]
    assert result["failed"] == ["n2"]
    assert result["skipped"] == ["n3"]


# ===========================================================================
# run() parameter overrides
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_run_overrides_max_cycles():
    """run() max_cycles parameter overrides settings.MAX_OPA_CYCLES."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {}})
    fragment = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
    planner = _StubPlanner(fragments=[fragment])
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE])

    settings = EngineSettings(MAX_OPA_CYCLES=100)
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    result = await loop.run(goal="override test", max_cycles=3)

    assert isinstance(result, WorkflowResult)
    assert result.status == "escalated"
    assert result.reason == "max_cycles_exceeded"
    assert result.cycle_count == 3


@pytest.mark.asyncio
async def test_opa_loop_run_overrides_max_llm_tokens():
    """run() max_llm_tokens parameter overrides settings.MAX_LLM_TOKENS."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult

    agent = _StubAgent(snapshot_result={"files": {}})
    fragment = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
    planner = _StubPlanner(fragments=[fragment])
    evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE])

    settings = EngineSettings(MAX_OPA_CYCLES=100, MAX_LLM_TOKENS=50000)
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    result = await loop.run(goal="override test", max_llm_tokens=1000, max_cycles=200)

    assert isinstance(result, WorkflowResult)
    assert result.status == "escalated"
    assert result.reason == "token_budget_exceeded"


# ===========================================================================
# Workflow persistence and event emission
# ===========================================================================


@pytest.mark.asyncio
async def test_opa_loop_creates_workflow_record():
    """OPALoop.run() persists a Workflow record with status RUNNING and TaskNode rows."""
    from celeste.core.opa_loop import OPALoop
    from celeste.database.db import get_session, init_db
    from celeste.database.models import TaskNode, Workflow, WorkflowStatus

    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=10,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    try:
        agent = _StubAgent(snapshot_result={"files": {}})
        fragment = _make_fragment(
            nodes=[_make_tool_node("step1", command="cmd_a")],
            goal_achieved=True,
        )
        planner = _StubPlanner(fragments=[fragment])
        evaluator = _StubEvaluator(decisions=[EvaluatorDecision.DONE])

        loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
        await loop.run(goal="persisted goal")

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "persisted goal")
            )
            workflow = result.scalar_one()
            assert workflow.status == WorkflowStatus.COMPLETED

            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == workflow.id)
            )
            nodes = result.scalars().all()
            assert len(nodes) == 1
            assert nodes[0].name == "step1"
    finally:
        from celeste.database.db import close_db

        await close_db()


@pytest.mark.asyncio
async def test_opa_loop_emits_workflow_events():
    """Each OPA cycle writes CYCLE_STARTED, OBSERVATION_CAPTURED, PLAN_GENERATED, and EVALUATION_RESULT WorkflowEvent rows."""
    from celeste.core.opa_loop import OPALoop
    from celeste.database.db import close_db, get_session, init_db
    from celeste.database.models import TaskEventType, Workflow, WorkflowEvent

    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=10,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    try:
        agent = _StubAgent(snapshot_result={"files": {}})
        fragment1 = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
        fragment2 = _make_fragment(nodes=[_make_tool_node("step2")], goal_achieved=True)
        planner = _StubPlanner(fragments=[fragment1, fragment2])
        evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE, EvaluatorDecision.DONE])

        loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
        await loop.run(goal="evented goal")

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "evented goal")
            )
            workflow = result.scalar_one()

            result = await session.execute(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == workflow.id)
                .order_by(WorkflowEvent.sequence_number)
            )
            events = result.scalars().all()
            types = [e.event_type for e in events]

            assert types.count(TaskEventType.CYCLE_STARTED) >= 2
            assert types.count(TaskEventType.OBSERVATION_CAPTURED) >= 2
            assert types.count(TaskEventType.PLAN_GENERATED) >= 2
            assert types.count(TaskEventType.EVALUATION_RESULT) >= 2

            # Sequence numbers should be monotonically assigned per workflow.
            seqs = [e.sequence_number for e in events]
            assert all(isinstance(s, int) for s in seqs)
            assert seqs == sorted(seqs)
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_opa_loop_compensates_on_failure():
    """When a node fails and compensation commands exist, OPALoop triggers compensation and records COMPENSATION_* events."""
    from celeste.core.opa_loop import OPALoop
    from celeste.database.db import close_db, get_session, init_db
    from celeste.database.models import TaskEvent, TaskEventType, Workflow

    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=10,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    try:
        agent = _StubAgent(snapshot_result={"files": {}})

        async def failing_call_tool(name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
            if name == "fail_cmd":
                return {"error": "boom"}
            return {"success": True}

        agent.call_tool = failing_call_tool

        node1 = _make_tool_node("n1", command="ok_cmd")
        node1.compensation_command = "undo_n1"
        node1.compensation_arguments = {"action": "undo"}
        node2 = _make_tool_node("n2", command="fail_cmd")
        node2.dependencies = ["n1"]

        fragment = _make_fragment(nodes=[node1, node2], goal_achieved=False)
        planner = _StubPlanner(fragments=[fragment])
        evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE])

        loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
        result = await loop.run(goal="saga goal", max_cycles=3)

        assert result.status == "failed"

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "saga goal")
            )
            workflow = result.scalar_one()
            assert workflow.status.value == "failed"

            result = await session.execute(
                select(TaskEvent).where(
                    TaskEvent.workflow_id == workflow.id,
                    TaskEvent.event_type == TaskEventType.COMPENSATION_TRIGGERED,
                )
            )
            assert len(result.scalars().all()) == 1

            result = await session.execute(
                select(TaskEvent).where(
                    TaskEvent.workflow_id == workflow.id,
                    TaskEvent.event_type == TaskEventType.COMPENSATION_COMPLETED,
                )
            )
            assert len(result.scalars().all()) == 1
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_opa_loop_max_cycles_exceeded():
    """Exceeding MAX_OPA_CYCLES returns escalated WorkflowResult and persists a workflow record."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult
    from celeste.database.db import close_db, get_session, init_db
    from celeste.database.models import Workflow, WorkflowStatus

    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=5,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    try:
        agent = _StubAgent(snapshot_result={"files": {}})
        fragment = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
        planner = _StubPlanner(fragments=[fragment])
        evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE])

        loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
        result = await loop.run(goal="max cycles persisted")

        assert isinstance(result, WorkflowResult)
        assert result.status == "escalated"
        assert result.reason == "max_cycles_exceeded"

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "max cycles persisted")
            )
            workflow = result.scalar_one()
            assert workflow.status == WorkflowStatus.RUNNING
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_opa_loop_token_budget_exceeded():
    """Exceeding MAX_LLM_TOKENS returns escalated WorkflowResult and persists a workflow record."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult
    from celeste.database.db import close_db, get_session, init_db
    from celeste.database.models import Workflow, WorkflowStatus

    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=100,
        MAX_LLM_TOKENS=1000,
    )
    await init_db(settings=settings)

    try:
        agent = _StubAgent(snapshot_result={"files": {}})
        fragment = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
        planner = _StubPlanner(fragments=[fragment])
        evaluator = _StubEvaluator(decisions=[EvaluatorDecision.CONTINUE])

        loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
        result = await loop.run(goal="token budget persisted")

        assert isinstance(result, WorkflowResult)
        assert result.status == "escalated"
        assert result.reason == "token_budget_exceeded"

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "token budget persisted")
            )
            workflow = result.scalar_one()
            assert workflow.status == WorkflowStatus.RUNNING
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_opa_loop_resume_from_paused():
    """Resume a paused workflow with human input and continue to completion."""
    from celeste.core.opa_loop import OPALoop, WorkflowResult
    from celeste.database.db import close_db, get_session, init_db
    from celeste.database.models import Workflow, WorkflowStatus, WorkflowEvent, TaskEventType

    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=10,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    try:
        agent = _StubAgent(snapshot_result={"files": {}})
        fragment1 = _make_fragment(nodes=[_make_tool_node("step1")], goal_achieved=False)
        fragment2 = _make_fragment(nodes=[_make_tool_node("step2")], goal_achieved=True)
        planner = _StubPlanner(fragments=[fragment1, fragment2])
        evaluator = _StubEvaluator(decisions=[EvaluatorDecision.ESCALATE, EvaluatorDecision.DONE])

        loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
        result = await loop.run(goal="resume test")

        assert result.status == "paused"
        workflow_id = result.workflow_id
        assert workflow_id is not None

        async with get_session() as session:
            wf_result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = wf_result.scalar_one()
            assert workflow.status == WorkflowStatus.PAUSED

        # Resume with human input
        resume_result = await loop.resume(workflow_id, "human guidance")

        assert resume_result.status == "completed"
        assert resume_result.workflow_id == workflow_id

        async with get_session() as session:
            wf_result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = wf_result.scalar_one()
            assert workflow.status == WorkflowStatus.COMPLETED
            assert workflow.human_input == "human guidance"
            assert workflow.paused_at is None

            # Verify HUMAN_INPUT_RECEIVED and WORKFLOW_RESUMED events
            evt_result = await session.execute(
                select(WorkflowEvent).where(
                    WorkflowEvent.workflow_id == workflow_id,
                    WorkflowEvent.event_type == TaskEventType.HUMAN_INPUT_RECEIVED,
                )
            )
            assert len(evt_result.scalars().all()) == 1

            evt_result = await session.execute(
                select(WorkflowEvent).where(
                    WorkflowEvent.workflow_id == workflow_id,
                    WorkflowEvent.event_type == TaskEventType.WORKFLOW_RESUMED,
                )
            )
            assert len(evt_result.scalars().all()) == 1
    finally:
        await close_db()
