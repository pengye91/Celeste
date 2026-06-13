"""
Regression test for the "engine plans but never executes" gap.

Symptom: in the pharma cold-chain run, every TaskNode ended in PENDING even
though the OPA loop emitted CYCLE_STARTED / OBSERVATION_CAPTURED /
PLAN_GENERATED / EVALUATION_RESULT events. No node_started / node_completed /
node_failed events were ever recorded.

Root cause: WorkflowExecutor.execute_fragment() called
self._agent.call_tool() but never persisted TaskNode status transitions or
emitted per-node TaskEvent rows. The plan was persisted via
OPALoop._persist_fragment(), but the act step didn't update those rows.

This test asserts that after a single OPA cycle the TaskNode row reaches
status=COMPLETED and at least one TaskEvent of type NODE_COMPLETED exists for
it -- the behaviour that the engine._execute_node() path already implements
for the API path, but which the in-process OPA loop must also implement.
"""

from __future__ import annotations

from typing import Any

import pytest

from celeste.config.settings import EngineSettings
from celeste.core.evaluator import EvaluatorDecision
from celeste.core.opa_loop import OPALoop
from celeste.core.planner import DAGFragment, DAGNode
from celeste.database.db import close_db, get_session, init_db
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
)
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _make_fragment(nodes: list[DAGNode] | None = None, goal_achieved: bool = False) -> DAGFragment:
    return DAGFragment(
        nodes=nodes or [],
        reasoning="act-step regression fragment",
        estimated_remaining=1,
        goal_achieved=goal_achieved,
    )


def _make_tool_node(name: str, command: str, args: dict[str, Any] | None = None) -> DAGNode:
    return DAGNode(
        name=name,
        task_type="tool_execution",
        command=command,
        arguments=args or {},
        dependencies=[],
    )


class _SnapshotAgent:
    """Minimal EnvironmentAgent stand-in with a "snapshot" tool.

    call_tool("snapshot") -> {"ok": True} (also used by OPA observe step).
    call_tool(<other>)   -> {"ok": True}.
    list_tools()         -> [].
    """

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        return {"ok": True}

    async def list_tools(self) -> list[dict[str, Any]]:
        return []


class _OneNodePlanner:
    """Planner that emits a single trivial tool_execution fragment."""

    def __init__(self, node: DAGNode) -> None:
        self._fragment = _make_fragment(nodes=[node], goal_achieved=True)
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
        return self._fragment


class _DoneEvaluator:
    """Evaluator that always returns DONE (signals goal achieved)."""

    async def evaluate(self, fragment: Any, goal: str) -> EvaluatorDecision:
        return EvaluatorDecision.DONE


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opa_loop_persists_node_status_and_events():
    """OPA loop act step must mark the TaskNode as COMPLETED and emit a NODE_COMPLETED event."""
    settings = EngineSettings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        MAX_OPA_CYCLES=10,
        MAX_LLM_TOKENS=5000,
    )
    await init_db(settings=settings)

    try:
        agent = _SnapshotAgent()
        node = _make_tool_node("act_step_node", command="snapshot", args={})
        planner = _OneNodePlanner(node)
        evaluator = _DoneEvaluator()

        loop = OPALoop(
            agent=agent,
            planner=planner,
            evaluator=evaluator,
            settings=settings,
        )
        result = await loop.run(goal="act step gap")

        assert result.status == "completed"
        assert result.workflow_id is not None

        async with get_session() as session:
            nodes = (
                await session.execute(
                    select(TaskNode).where(TaskNode.workflow_id == result.workflow_id)
                )
            ).scalars().all()

            assert len(nodes) == 1
            persisted_node = nodes[0]
            assert persisted_node.name == "act_step_node"
            assert persisted_node.status == TaskNodeStatus.COMPLETED

            events = (
                await session.execute(
                    select(TaskEvent).where(
                        TaskEvent.task_node_id == persisted_node.id,
                        TaskEvent.event_type == TaskEventType.NODE_COMPLETED,
                    )
                )
            ).scalars().all()

            assert len(events) >= 1, (
                "Expected at least one NODE_COMPLETED TaskEvent for the executed node"
            )
    finally:
        await close_db()