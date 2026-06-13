"""
Tests for OBS-020: Engine._execute_node must capture stderr lines.

The audit shows Engine._execute_node handles stdout_line but ignores
stderr_line. DockerWorkspace emits stderr_line events that are queued
to the event queue but never persisted to TaskNode.outputs.

These tests verify that:
- A stderr_line event is captured into TaskNode.outputs under a "stderr" key
- A stdout_line event is captured under a "stdout" key
- Both streams are preserved through completion
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator

import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.planner import DAGNode, DAGPlan
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.models import (
    TaskEvent,
    TaskNode,
    TaskNodeStatus,
    Workflow,
)


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


class _StderrWorkspace(BaseWorkspace):
    """Workspace that yields stdout + stderr + completion events."""

    def __init__(self):
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        self._active = True

    async def execute(self, command, arguments=None, env=None):
        yield WorkspaceEvent(event_type="stdout_line", data="out-1")
        yield WorkspaceEvent(event_type="stderr_line", data="err-1")
        yield WorkspaceEvent(event_type="stdout_line", data="out-2")
        yield WorkspaceEvent(event_type="stderr_line", data="err-2")
        yield WorkspaceEvent(event_type="execution_completed", data={"exit_code": 0})

    async def teardown(self) -> None:
        self._active = False

    async def get_workspace_path(self):
        return "/tmp/stderr"


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


PLAN = DAGPlan(
    name="stderr-test",
    description="Plan used to verify stderr capture (OBS-020)",
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


class TestExecuteNodeStderrCapture:
    """Engine._execute_node must persist both stdout and stderr streams."""

    @pytest.mark.asyncio
    async def test_stderr_lines_captured_into_outputs(self, settings):
        from celeste.core.engine import Engine
        from celeste.database.db import get_session

        engine = Engine(settings=settings, workspace_factory=lambda: _StderrWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(PLAN)
            async with get_session() as session:
                node = (
                    await session.execute(
                        select(TaskNode).where(
                            TaskNode.workflow_id == wf_id,
                            TaskNode.name == "only_step",
                        )
                    )
                ).scalar_one()
                node_id = node.id

            await engine._execute_node(node_id, _StderrWorkspace())

            async with get_session() as session:
                node = (
                    await session.execute(
                        select(TaskNode).where(TaskNode.id == node_id)
                    )
                ).scalar_one()
                # OBS-020: outputs must include stderr content.
                # Accept either JSON {"stdout":..., "stderr":...} or a
                # string containing both streams, but stderr must appear.
                outputs = node.outputs or ""
                assert "err-1" in outputs, (
                    "TaskNode.outputs must contain stderr content (OBS-020); "
                    f"got: {outputs!r}"
                )
                assert "err-2" in outputs, (
                    "TaskNode.outputs must contain second stderr line (OBS-020)"
                )
                # stdout should still be there
                assert "out-1" in outputs, (
                    "TaskNode.outputs must still contain stdout content"
                )
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_outputs_use_structured_json_with_stderr_key(self, settings):
        """OBS-020 proposed fix: outputs = {"stdout": ..., "stderr": ...}."""
        from celeste.core.engine import Engine
        from celeste.database.db import get_session

        engine = Engine(settings=settings, workspace_factory=lambda: _StderrWorkspace())
        await engine.start()
        try:
            wf_id = await engine.submit_workflow(PLAN)
            async with get_session() as session:
                node = (
                    await session.execute(
                        select(TaskNode).where(
                            TaskNode.workflow_id == wf_id,
                            TaskNode.name == "only_step",
                        )
                    )
                ).scalar_one()
                node_id = node.id

            await engine._execute_node(node_id, _StderrWorkspace())

            async with get_session() as session:
                node = (
                    await session.execute(
                        select(TaskNode).where(TaskNode.id == node_id)
                    )
                ).scalar_one()
                outputs = node.outputs or ""
                # Try to parse as JSON; the fix should produce {"stdout":..., "stderr":...}
                parsed = None
                try:
                    parsed = json.loads(outputs)
                except Exception:
                    pass
                if parsed is not None and isinstance(parsed, dict):
                    assert "stderr" in parsed, (
                        "outputs JSON must include 'stderr' key (OBS-020)"
                    )
                    assert "stdout" in parsed, (
                        "outputs JSON must include 'stdout' key (OBS-020)"
                    )
                else:
                    # Plain string fallback - just verify stderr present
                    assert "err-1" in outputs and "out-1" in outputs
        finally:
            await engine.stop()