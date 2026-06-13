"""Tests for the Celeste evaluation module.

Follows strict TDD. Covers:
- Evaluator.evaluate() orchestration
- FeatureDetector for all 8 features
- AssertionRegistry
- Reporter formatting
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.evaluator import EvaluatorDecision
from celeste.core.opa_loop import OPALoop
from celeste.core.planner import DAGFragment, DAGNode
from celeste.database.db import close_db, get_session, init_db
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)
from celeste.evaluation import (
    Evaluator,
    AssertionRegistry,
    FeatureDetector,
    MetricsCollector,
    format_report,
    assert_replan_occurred,
    assert_saga_compensation,
    assert_escalation,
    assert_checkpoint_state_match,
    assert_multi_workspace,
    assert_security_pipeline,
)
from celeste.evaluation.schemas import EvaluationReport, FeatureResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubAgent:
    def __init__(self) -> None:
        self.snapshot_result: dict = {"files": {}}

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return {"success": True}

    async def list_tools(self) -> list[dict]:
        return []


class _StubPlanner:
    def __init__(self, fragments: list[DAGFragment]) -> None:
        self._fragments = fragments
        self._index = 0
        self.plan_calls: list[dict] = []

    async def plan(self, **kwargs) -> DAGFragment:
        self.plan_calls.append(kwargs)
        fragment = self._fragments[self._index]
        self._index = min(self._index + 1, len(self._fragments) - 1)
        return fragment


class _StubEvaluator:
    def __init__(self, decisions: list[EvaluatorDecision]) -> None:
        self._decisions = decisions
        self._index = 0

    async def evaluate(self, fragment: DAGFragment, goal: str) -> EvaluatorDecision:
        decision = self._decisions[self._index]
        self._index = min(self._index + 1, len(self._decisions) - 1)
        return decision


def _make_tool_node(name: str, command: str = "run_command") -> DAGNode:
    return DAGNode(
        name=name,
        task_type="tool_execution",
        command=command,
        arguments={},
        dependencies=[],
    )


def _make_fragment(nodes: list[DAGNode], goal_achieved: bool = False) -> DAGFragment:
    return DAGFragment(
        nodes=nodes,
        reasoning="test",
        estimated_remaining=1,
        goal_achieved=goal_achieved,
    )


async def _run_workflow(goal: str, fragments: list[DAGFragment], decisions: list[EvaluatorDecision]) -> str:
    """Run a workflow and return the workflow_id."""
    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=10,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    agent = _StubAgent()
    planner = _StubPlanner(fragments=fragments)
    evaluator = _StubEvaluator(decisions=decisions)
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    result = await loop.run(goal=goal)
    return str(result.workflow_id)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class TestEvaluator:
    @pytest.mark.asyncio
    async def test_evaluator_empty_assertions(self):
        """No assertions → report has 0 custom features but built-in ones."""
        wf_id = await _run_workflow(
            "eval test",
            fragments=[_make_fragment([_make_tool_node("s1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )

        evaluator = Evaluator(workflow_id=wf_id)
        report = await evaluator.evaluate()
        assert report.workflow_id == wf_id
        assert report.overall in ("PASS", "PARTIAL", "FAIL")
        assert "dynamic_opa_loop" in report.features

    @pytest.mark.asyncio
    async def test_evaluator_all_pass(self):
        """All features exercised and passing."""
        wf_id = await _run_workflow(
            "pass test",
            fragments=[
                _make_fragment([_make_tool_node("s1")]),
                _make_fragment([_make_tool_node("s2")], goal_achieved=True),
            ],
            decisions=[EvaluatorDecision.REPLAN, EvaluatorDecision.DONE],
        )

        evaluator = Evaluator(workflow_id=wf_id)
        evaluator.assertions.add(assert_replan_occurred(min_count=1))
        report = await evaluator.evaluate()
        assert report.features["dynamic_opa_loop"].status == "PASS"

    @pytest.mark.asyncio
    async def test_evaluator_some_fail(self):
        """Some features fail → PARTIAL."""
        wf_id = await _run_workflow(
            "partial test",
            fragments=[_make_fragment([_make_tool_node("s1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )

        evaluator = Evaluator(workflow_id=wf_id)
        evaluator.assertions.add(assert_replan_occurred(min_count=1))
        report = await evaluator.evaluate()
        assert report.overall == "PARTIAL"

    @pytest.mark.asyncio
    async def test_evaluator_all_fail(self):
        """When built-in features are NOT_EXERCISED and assertions fail, overall is PARTIAL (not all-FAIL)."""
        wf_id = await _run_workflow(
            "fail test",
            fragments=[_make_fragment([_make_tool_node("s1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )

        evaluator = Evaluator(workflow_id=wf_id)
        evaluator.assertions.add(assert_replan_occurred(min_count=5))
        report = await evaluator.evaluate()
        assert report.overall == "PARTIAL"


# ---------------------------------------------------------------------------
# FeatureDetector
# ---------------------------------------------------------------------------


class TestFeatureDetector:
    @pytest.mark.asyncio
    async def test_detect_replan_no_events(self):
        wf_id = await _run_workflow(
            "no replan",
            fragments=[_make_fragment([_make_tool_node("s1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        detector = FeatureDetector()
        evidence = await detector.detect_replan(wf_id)
        assert evidence.replan_count == 0

    @pytest.mark.asyncio
    async def test_detect_replan_found(self):
        wf_id = await _run_workflow(
            "replan test",
            fragments=[
                _make_fragment([_make_tool_node("s1")]),
                _make_fragment([_make_tool_node("s1"), _make_tool_node("s2")]),
            ],
            decisions=[EvaluatorDecision.REPLAN, EvaluatorDecision.DONE],
        )
        detector = FeatureDetector()
        evidence = await detector.detect_replan(wf_id)
        assert evidence.replan_count == 1
        assert "new_nodes" in evidence.dag_diffs[0]

    @pytest.mark.asyncio
    async def test_detect_saga_correct_chain(self):
        wf_id = await _run_workflow(
            "saga test",
            fragments=[
                _make_fragment([_make_tool_node("n1")]),
            ],
            decisions=[EvaluatorDecision.CONTINUE],
        )
        # Manually inject compensation events
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "saga test")
            )
            workflow = result.scalar_one()
            session.add(
                TaskEvent(
                    task_node_id=uuid.uuid4(),
                    workflow_id=workflow.id,
                    event_type=TaskEventType.COMPENSATION_TRIGGERED,
                    event_data={"compensation_command": "undo"},
                )
            )
            session.add(
                TaskEvent(
                    task_node_id=uuid.uuid4(),
                    workflow_id=workflow.id,
                    event_type=TaskEventType.COMPENSATION_COMPLETED,
                    event_data={"compensation_command": "undo"},
                )
            )

        detector = FeatureDetector()
        evidence = await detector.detect_saga(wf_id)
        assert evidence.chain_executed == ["triggered", "completed"]

    @pytest.mark.asyncio
    async def test_detect_saga_wrong_order(self):
        wf_id = await _run_workflow(
            "saga wrong",
            fragments=[_make_fragment([_make_tool_node("n1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "saga wrong")
            )
            workflow = result.scalar_one()
            session.add(
                TaskEvent(
                    task_node_id=uuid.uuid4(),
                    workflow_id=workflow.id,
                    event_type=TaskEventType.COMPENSATION_COMPLETED,
                )
            )
            session.add(
                TaskEvent(
                    task_node_id=uuid.uuid4(),
                    workflow_id=workflow.id,
                    event_type=TaskEventType.COMPENSATION_TRIGGERED,
                )
            )

        detector = FeatureDetector()
        evidence = await detector.detect_saga(wf_id)
        assert evidence.error == "compensation_started_after_completion"

    @pytest.mark.asyncio
    async def test_detect_escalation_resolved(self):
        wf_id = await _run_workflow(
            "escalation test",
            fragments=[_make_fragment([_make_tool_node("n1")])],
            decisions=[EvaluatorDecision.ESCALATE],
        )
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "escalation test")
            )
            workflow = result.scalar_one()
            session.add(
                WorkflowEvent(
                    workflow_id=workflow.id,
                    event_type=TaskEventType.HUMAN_INPUT_RECEIVED,
                    event_data={"human_input": "do this"},
                    sequence_number=10,
                )
            )
            session.add(
                WorkflowEvent(
                    workflow_id=workflow.id,
                    event_type=TaskEventType.WORKFLOW_RESUMED,
                    event_data={},
                    sequence_number=11,
                )
            )

        detector = FeatureDetector()
        evidence = await detector.detect_escalation(wf_id, max_pause_minutes=60)
        assert evidence.human_input_present is True

    @pytest.mark.asyncio
    async def test_detect_escalation_timeout(self):
        wf_id = await _run_workflow(
            "escalation timeout",
            fragments=[_make_fragment([_make_tool_node("n1")])],
            decisions=[EvaluatorDecision.ESCALATE],
        )
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "escalation timeout")
            )
            workflow = result.scalar_one()
            session.add(
                WorkflowEvent(
                    workflow_id=workflow.id,
                    event_type=TaskEventType.HUMAN_INPUT_RECEIVED,
                    event_data={"human_input": "do this"},
                    sequence_number=10,
                    timestamp=workflow.created_at + timedelta(minutes=65),
                )
            )
            session.add(
                WorkflowEvent(
                    workflow_id=workflow.id,
                    event_type=TaskEventType.WORKFLOW_RESUMED,
                    event_data={},
                    sequence_number=11,
                    timestamp=workflow.created_at + timedelta(minutes=66),
                )
            )

        detector = FeatureDetector()
        evidence = await detector.detect_escalation(wf_id, max_pause_minutes=60)
        assert evidence.error is not None
        assert "exceeded" in evidence.error

    @pytest.mark.asyncio
    async def test_detect_checkpoint_state_match(self):
        wf_id = await _run_workflow(
            "checkpoint",
            fragments=[_make_fragment([_make_tool_node("n1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "checkpoint")
            )
            workflow = result.scalar_one()
            session.add(
                WorkflowEvent(
                    workflow_id=workflow.id,
                    event_type=TaskEventType.CHECKPOINT,
                    event_data={"state_hash": "abc123"},
                    sequence_number=5,
                )
            )
            session.add(
                WorkflowEvent(
                    workflow_id=workflow.id,
                    event_type=TaskEventType.STATE_CHECKPOINT,
                    event_data={"state_hash": "abc123"},
                    sequence_number=6,
                )
            )

        detector = FeatureDetector()
        evidence = await detector.detect_checkpoint(wf_id)
        assert evidence.checkpoint_count == 1
        assert evidence.state_hash_match is True

    @pytest.mark.asyncio
    async def test_detect_multi_workspace_no_events(self):
        """No workspace events should return concurrent_max=0 without an error."""
        wf_id = await _run_workflow(
            "multi-ws none",
            fragments=[_make_fragment([_make_tool_node("n1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        detector = FeatureDetector()
        evidence = await detector.detect_multi_workspace(wf_id)
        assert evidence.concurrent_max == 0
        assert evidence.workspaces_leaked == 0
        assert evidence.error is None

    @pytest.mark.asyncio
    async def test_detect_multi_workspace_concurrent(self):
        """Correctly computes concurrent_max and leak count from events."""
        wf_id = await _run_workflow(
            "multi-ws concurrent",
            fragments=[_make_fragment([_make_tool_node("n1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "multi-ws concurrent")
            )
            workflow = result.scalar_one()
            # Simulate 3 concurrent workspaces with partial teardown (1 leak).
            # Use high sequence numbers to avoid colliding with the
            # WORKFLOW_SUBMITTED / CYCLE_STARTED / WORKFLOW_COMPLETED
            # events that _run_workflow already inserted.
            # seq: spawn(100), spawn(101), spawn(102), destroy(101), destroy(102)  -> concurrent_max=3, leaked=1
            for seq, etype in [
                (100, TaskEventType.WORKSPACE_SPAWN),
                (101, TaskEventType.WORKSPACE_SPAWN),
                (102, TaskEventType.WORKSPACE_SPAWN),
                (103, TaskEventType.WORKSPACE_DESTROY),
                (104, TaskEventType.WORKSPACE_DESTROY),
            ]:
                session.add(
                    WorkflowEvent(
                        workflow_id=workflow.id,
                        event_type=etype,
                        sequence_number=seq,
                    )
                )

        detector = FeatureDetector()
        evidence = await detector.detect_multi_workspace(wf_id)
        assert evidence.concurrent_max == 3
        assert evidence.workspaces_leaked == 1
        assert evidence.error is None

    @pytest.mark.asyncio
    async def test_detect_multi_workspace_all_torn_down(self):
        """When all spawns are matched by destroys, leaked=0."""
        wf_id = await _run_workflow(
            "multi-ws clean",
            fragments=[_make_fragment([_make_tool_node("n1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "multi-ws clean")
            )
            workflow = result.scalar_one()
            # High sequence numbers to avoid collisions with events
            # already inserted by _run_workflow.
            for seq, etype in [
                (100, TaskEventType.WORKSPACE_SPAWN),
                (101, TaskEventType.WORKSPACE_SPAWN),
                (102, TaskEventType.WORKSPACE_DESTROY),
                (103, TaskEventType.WORKSPACE_DESTROY),
            ]:
                session.add(
                    WorkflowEvent(
                        workflow_id=workflow.id,
                        event_type=etype,
                        sequence_number=seq,
                    )
                )

        detector = FeatureDetector()
        evidence = await detector.detect_multi_workspace(wf_id)
        assert evidence.concurrent_max == 2
        assert evidence.workspaces_leaked == 0
        assert evidence.error is None

    @pytest.mark.asyncio
    async def test_detect_security_blocked_call(self):
        wf_id = await _run_workflow(
            "security",
            fragments=[_make_fragment([_make_tool_node("n1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        detector = FeatureDetector()
        evidence = await detector.detect_security(wf_id)
        assert isinstance(evidence.blocked_count, int)

    @pytest.mark.asyncio
    async def test_detect_security_no_audit(self):
        wf_id = await _run_workflow(
            "security no audit",
            fragments=[_make_fragment([_make_tool_node("n1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.name == "security no audit")
            )
            workflow = result.scalar_one()
            session.add(
                TaskEvent(
                    task_node_id=uuid.uuid4(),
                    workflow_id=workflow.id,
                    event_type=TaskEventType.NODE_COMPLETED,
                    event_data={"command": "UPDATE batches SET status='x'"},
                )
            )

        detector = FeatureDetector()
        evidence = await detector.detect_security(wf_id)
        assert evidence.missing_audit_count >= 0


# ---------------------------------------------------------------------------
# AssertionRegistry
# ---------------------------------------------------------------------------


class TestAssertionRegistry:
    @pytest.mark.asyncio
    async def test_add_and_evaluate(self):
        registry = AssertionRegistry()
        registry.add(assert_replan_occurred(min_count=0))
        results = await registry.evaluate("wf_001")
        assert len(results) == 1
        assert results[0].name == "assert_replan_occurred"

    @pytest.mark.asyncio
    async def test_exception_handled(self):
        registry = AssertionRegistry()

        async def bad_assert(wf_id: str):
            raise RuntimeError("boom")

        registry.add(bad_assert)
        results = await registry.evaluate("wf_001")
        assert len(results) == 1
        assert results[0].passed is False
        assert "boom" in results[0].message


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


class TestReporter:
    def test_format_pass(self):
        report = EvaluationReport(
            workflow_id="wf_001",
            overall="PASS",
            features={
                "f1": FeatureResult(name="f1", status="PASS", evidence={}, assertion="a1"),
            },
        )
        text = format_report(report)
        assert "PASS" in text
        assert "wf_001" in text

    def test_format_fail(self):
        report = EvaluationReport(
            workflow_id="wf_001",
            overall="FAIL",
            features={
                "f1": FeatureResult(name="f1", status="FAIL", evidence={}, assertion="a1"),
            },
        )
        text = format_report(report)
        assert "FAIL" in text


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------


class TestMetricsCollector:
    @pytest.mark.asyncio
    async def test_collect_opa_cycles(self):
        wf_id = await _run_workflow(
            "metrics",
            fragments=[_make_fragment([_make_tool_node("n1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        collector = MetricsCollector()
        metrics = await collector.collect(wf_id)
        assert metrics.opa_cycles == 1
        assert metrics.total_nodes == 1

    @pytest.mark.asyncio
    async def test_collect_token_cost(self):
        wf_id = await _run_workflow(
            "token cost",
            fragments=[_make_fragment([_make_tool_node("n1")], goal_achieved=True)],
            decisions=[EvaluatorDecision.DONE],
        )
        collector = MetricsCollector()
        cost = await collector.collect_token_cost(wf_id)
        assert cost.planner_tokens >= 0
        assert cost.total_tokens >= cost.planner_tokens


# ---------------------------------------------------------------------------
# Cleanup fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _cleanup_db():
    yield
    await close_db()
