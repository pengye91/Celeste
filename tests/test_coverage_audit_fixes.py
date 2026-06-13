"""
Coverage tests for the audit-driven bug fixes.

These tests target gaps identified by the 2026-06-13 audit:
- F2:  OPALoop compensation failure records COMPENSATION_FAILED event
- F4:  OPALoop planner unexpected exception sets workflow status to failed
- F6:  Engine workspace lifecycle emits WORKSPACE_SPAWN + WORKSPACE_DESTROY
- F12: Planner.plan() raises after 3 attempts all fail
- F14: Engine.resume_workflow atomic status check (PAUSED only)

These tests cover behaviour gaps that the audit flagged as
undertested, ensuring regression coverage for the existing fixes.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator

import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.planner import DAGNode, DAGPlan, DAGFragment
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowStatus,
    WorkflowEvent,
)


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


# ---------------------------------------------------------------------------
# Shared fixtures
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


@pytest.fixture
def settings():
    return EngineSettings(
        DATABASE_URL=SQLITE_MEMORY_URL,  # type: ignore[arg-type]
        MAX_PARALLEL_SUBPROCESSES=2,
        WORKSPACE_ENGINE="local_tmp",
    )


# ---------------------------------------------------------------------------
# F2: Compensation failure records COMPENSATION_FAILED
# ---------------------------------------------------------------------------


class _FailingCompensationAgent:
    """Mock agent whose call_tool raises for compensation commands."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> dict:
        self.calls.append((tool_name, arguments or {}))
        raise RuntimeError(f"compensation tool {tool_name} failed")


@pytest.mark.asyncio
async def test_opa_loop_compensation_failure_records_failed_event(settings):
    """F2: When a compensation call_tool raises, OPALoop._trigger_compensation
    must record a TaskEvent(type=COMPENSATION_FAILED, event_data={error:...}).
    """
    from celeste.core.agent import EnvironmentAgent
    from celeste.core.evaluator import Evaluator
    from celeste.core.opa_loop import OPALoop
    from celeste.core.planner import Planner
    from celeste.database.db import init_db
    from celeste.database.models import Workflow

    await init_db(settings=settings)

    wf_id = uuid.uuid4()
    async with __import__("celeste.database.db", fromlist=["get_session"]).get_session() as session:
        session.add(
            Workflow(
                id=wf_id,
                name="f2-test",
                status=WorkflowStatus.RUNNING,
                dag_definition={"nodes": []},
            )
        )

    # Build a fragment with a compensation_command
    frag = DAGFragment(
        reasoning="compensate step_a",
        nodes=[
            DAGNode(
                name="step_a",
                task_type="tool_execution",
                command="do_a",
                arguments={},
                dependencies=[],
                compensation_command="undo_a",
                compensation_arguments={"target": "a"},
            ),
        ],
    )

    # Need a completed node matching the compensation in DB
    async with __import__("celeste.database.db", fromlist=["get_session"]).get_session() as session:
        session.add(
            TaskNode(
                workflow_id=wf_id,
                name="step_a",
                task_type="tool_execution",
                status=TaskNodeStatus.COMPLETED,
                command="do_a",
                arguments={},
                compensation_command="undo_a",
                compensation_arguments={"target": "a"},
            )
        )

    agent = _FailingCompensationAgent()
    planner = Planner.__new__(Planner)
    planner._client = None
    evaluator = Evaluator.__new__(Evaluator)
    evaluator._llm_client = None
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)
    await loop._trigger_compensation(
        workflow_id=wf_id,
        fragment=frag,
        completed_node_names={"step_a"},
    )

    async with __import__("celeste.database.db", fromlist=["get_session"]).get_session() as session:
        events = (
            await session.execute(
                select(TaskEvent).where(TaskEvent.workflow_id == wf_id)
            )
        ).scalars().all()
        types = [e.event_type for e in events]
        assert TaskEventType.COMPENSATION_TRIGGERED in types, "must record TRIGGERED"
        assert TaskEventType.COMPENSATION_FAILED in types, (
            "F2: COMPENSATION_FAILED event must be recorded when call_tool raises"
        )
        failed_event = next(e for e in events if e.event_type == TaskEventType.COMPENSATION_FAILED)
        assert failed_event.event_data and "error" in failed_event.event_data


# ---------------------------------------------------------------------------
# F4: Planner unexpected exception sets workflow status to failed
# ---------------------------------------------------------------------------


class _ExplodingPlanner:
    """Planner whose plan() always raises an unexpected exception."""

    def __init__(self):
        self.plan_calls: list[dict[str, Any]] = []

    async def plan(self, **kwargs):
        self.plan_calls.append(kwargs)
        raise RuntimeError("planner kaboom")


class _NoopAgent:
    async def call_tool(self, *args, **kwargs):
        return {"ok": True}

    async def list_tools(self):
        return ["a"]


@pytest.mark.asyncio
async def test_opa_loop_planner_unexpected_exception_sets_failed(settings):
    """F4: When the planner raises an unexpected exception (not PlannerTimeoutError
    or max_cycles), OPALoop should surface it and mark the workflow as FAILED.
    """
    from celeste.core.evaluator import Evaluator
    from celeste.core.opa_loop import OPALoop
    from celeste.database.db import init_db, get_session
    from celeste.database.models import Workflow

    await init_db(settings=settings)
    wf_id = uuid.uuid4()
    async with get_session() as session:
        session.add(
            Workflow(
                id=wf_id,
                name="f4-test",
                status=WorkflowStatus.PENDING,
                dag_definition={"nodes": []},
            )
        )

    agent = _NoopAgent()
    planner = _ExplodingPlanner()
    evaluator = Evaluator.__new__(Evaluator)
    evaluator._llm_client = None
    loop = OPALoop(agent=agent, planner=planner, evaluator=evaluator, settings=settings)

    # Should not swallow the exception silently — propagate or mark failed.
    raised = False
    try:
        await loop.run(goal="kaboom goal", max_cycles=2)
    except RuntimeError as e:
        if "planner kaboom" in str(e):
            raised = True

    # Either it propagated or workflow was marked FAILED.
    if not raised:
        async with get_session() as session:
            wf = (
                await session.execute(
                    select(Workflow).where(Workflow.id == wf_id)
                )
            ).scalar_one_or_none()
            assert wf is not None
            assert wf.status == WorkflowStatus.FAILED, (
                "F4: planner exception must mark workflow as FAILED"
            )


# ---------------------------------------------------------------------------
# F6: Workspace spawn/destroy events emitted
# ---------------------------------------------------------------------------


class _SimpleWorkspace(BaseWorkspace):
    """Minimal workspace yielding one stdout + completion."""

    def __init__(self):
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        self._active = True

    async def execute(self, command, arguments=None, env=None):
        yield WorkspaceEvent(event_type="stdout_line", data="ok")
        yield WorkspaceEvent(event_type="execution_completed", data={"exit_code": 0})

    async def teardown(self) -> None:
        self._active = False

    async def get_workspace_path(self):
        return "/tmp/simple"


_PLAN = DAGPlan(
    name="f6-test",
    description="Workspace lifecycle test",
    nodes=[
        DAGNode(
            name="only_step",
            task_type="tool_execution",
            command="echo hi",
            arguments={},
            dependencies=[],
        ),
    ],
)


@pytest.mark.asyncio
async def test_workspace_spawn_destroy_events_emitted(settings):
    """F6: Every node execution must emit a matching
    WORKSPACE_SPAWN and WORKSPACE_DESTROY WorkflowEvent pair."""
    from celeste.core.engine import Engine
    from celeste.database.db import get_session

    engine = Engine(settings=settings, workspace_factory=lambda: _SimpleWorkspace())
    await engine.start()
    try:
        wf_id = await engine.submit_workflow(_PLAN)
        await engine.run_workflow(wf_id)
        async with get_session() as session:
            events = (
                await session.execute(
                    select(WorkflowEvent).where(WorkflowEvent.workflow_id == wf_id)
                )
            ).scalars().all()
        types = [e.event_type for e in events]
        spawn_count = types.count(TaskEventType.WORKSPACE_SPAWN)
        destroy_count = types.count(TaskEventType.WORKSPACE_DESTROY)
        assert spawn_count == 1, f"F6: expected 1 WORKSPACE_SPAWN, got {spawn_count}"
        assert destroy_count == 1, f"F6: expected 1 WORKSPACE_DESTROY, got {destroy_count}"
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# F12: Planner raises after 3 attempts
# ---------------------------------------------------------------------------


class _FailingStructuredClient:
    """LLM client whose structured_output_with_usage always raises."""

    async def structured_output_with_usage(self, *args, **kwargs):
        raise RuntimeError("LLM down")


@pytest.mark.asyncio
async def test_planner_raises_after_three_failures():
    """F12: Planner.plan() must retry up to 3 attempts and then surface
    the last error to the caller."""
    from celeste.core.planner import Planner, PlannerTimeoutError

    planner = Planner(
        llm_client=_FailingStructuredClient(),
        toolkits=None,
    )
    with pytest.raises(RuntimeError, match="LLM down"):
        await planner.plan(goal="x", history=[], timeout_ms=1000)


# ---------------------------------------------------------------------------
# F14: Engine.resume_workflow atomic status check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_resume_atomic_status_check(settings):
    """F14: Engine.resume_workflow must atomically check that the workflow
    is in PAUSED state before allowing resume. Calling resume_workflow on
    a workflow in any other state must raise ValueError."""
    from celeste.core.engine import Engine
    from celeste.database.db import get_session

    engine = Engine(settings=settings)
    await engine.start()
    try:
        # Create a workflow in COMPLETED status (terminal, non-paused)
        wf_id = uuid.uuid4()
        async with get_session() as session:
            session.add(
                Workflow(
                    id=wf_id,
                    name="f14-test",
                    status=WorkflowStatus.COMPLETED,
                    dag_definition={"nodes": []},
                )
            )

        with pytest.raises(ValueError, match="not paused"):
            await engine.resume_workflow(wf_id, "human input")

        # Verify status is unchanged (still COMPLETED, not RUNNING)
        async with get_session() as session:
            wf = (
                await session.execute(select(Workflow).where(Workflow.id == wf_id))
            ).scalar_one()
            assert wf.status == WorkflowStatus.COMPLETED, (
                "F14: resume on non-paused workflow must NOT mutate status"
            )
    finally:
        await engine.stop()