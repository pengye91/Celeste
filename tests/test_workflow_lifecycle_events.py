"""
Tests for OBS-005: WORKFLOW_SUBMITTED and WORKFLOW_COMPLETED events.

The audit shows WORKFLOW_SUBMITTED (models.py:77) and WORKFLOW_COMPLETED
(models.py:78) are defined in TaskEventType but never emitted anywhere.
Engine.submit_workflow creates a Workflow row but emits no event;
Engine._complete_workflow and _fail_workflow only update workflow.status.

These tests assert:
- Engine.submit_workflow emits a TaskEvent(WORKFLOW_SUBMITTED) row
- Engine.run_workflow on a successful workflow emits WORKFLOW_COMPLETED
- Engine.run_workflow on a failing workflow emits WORKFLOW_FAILED
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.planner import DAGNode, DAGPlan
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    Workflow,
)


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


SUBMITTED_PLAN = DAGPlan(
    name="lifecycle-test",
    description="Used to verify lifecycle events are emitted",
    nodes=[
        DAGNode(
            name="only_step",
            task_type="tool_execution",
            command="echo lifecycle",
            arguments={},
            dependencies=[],
        ),
    ],
)


class _PassingWorkspace(BaseWorkspace):
    """Workspace that yields one stdout_line and then succeeds."""

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
        return "/tmp/passing"


class _FailingWorkspace(BaseWorkspace):
    """Workspace that yields an execution_failed event."""

    def __init__(self):
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        self._active = True

    async def execute(self, command, arguments=None, env=None):
        yield WorkspaceEvent(event_type="execution_failed", data={"exit_code": 1, "stderr": "boom"})

    async def teardown(self) -> None:
        self._active = False

    async def get_workspace_path(self):
        return "/tmp/failing"


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
        MAX_PARALLEL_SUBPROCESSES=1,
        WORKSPACE_ENGINE="local_tmp",
    )


class TestWorkflowLifecycleEvents:
    """Engine.submit_workflow / _complete_workflow / _fail_workflow
    must emit TaskEvent rows for lifecycle transitions."""

    @pytest.mark.asyncio
    async def test_submit_workflow_emits_workflow_submitted(self, settings):
        from celeste.core.engine import Engine
        from celeste.database.db import get_session

        engine = Engine(settings=settings, workspace_factory=lambda: _PassingWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SUBMITTED_PLAN)
            async with get_session() as session:
                events = (
                    await session.execute(
                        select(TaskEvent).where(TaskEvent.workflow_id == wf_id)
                    )
                ).scalars().all()
                types = [e.event_type for e in events]
            assert TaskEventType.WORKFLOW_SUBMITTED in types, (
                "Engine.submit_workflow must emit WORKFLOW_SUBMITTED (OBS-005)"
            )
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_run_workflow_emits_workflow_completed(self, settings):
        from celeste.core.engine import Engine
        from celeste.database.db import get_session

        engine = Engine(settings=settings, workspace_factory=lambda: _PassingWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SUBMITTED_PLAN)
            await engine.run_workflow(wf_id)
            async with get_session() as session:
                events = (
                    await session.execute(
                        select(TaskEvent).where(TaskEvent.workflow_id == wf_id)
                    )
                ).scalars().all()
                types = [e.event_type for e in events]
            assert TaskEventType.WORKFLOW_COMPLETED in types, (
                "Successful workflow must emit WORKFLOW_COMPLETED (OBS-005)"
            )
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_run_workflow_emits_workflow_failed_on_failure(self, settings):
        from celeste.core.engine import Engine
        from celeste.database.db import get_session

        engine = Engine(settings=settings, workspace_factory=lambda: _FailingWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(SUBMITTED_PLAN)
            await engine.run_workflow(wf_id)
            async with get_session() as session:
                events = (
                    await session.execute(
                        select(TaskEvent).where(TaskEvent.workflow_id == wf_id)
                    )
                ).scalars().all()
                types = [e.event_type for e in events]
            assert TaskEventType.WORKFLOW_FAILED in types, (
                "Failing workflow must emit WORKFLOW_FAILED (OBS-005)"
            )
        finally:
            await engine.stop()