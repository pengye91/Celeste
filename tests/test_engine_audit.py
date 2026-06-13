"""SEC-002 / SEC-007: SecurityAuditor wired into Engine execution and compensation.

Tests demonstrate that:
- Engine._execute_node calls a SecurityAuditor before invoking workspace.execute
  (SEC-002)
- Engine._handle_failure audits the compensation command before executing it
  (SEC-007)
- When audit verdict is unsafe, execution is blocked
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator

import pytest
from sqlalchemy import select

from celeste.config.settings import EngineSettings
from celeste.core.planner import DAGNode, DAGPlan
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
)


SQLITE_MEMORY_URL = "sqlite+aiosqlite://"


# Two-node plan: node A completes successfully, node B fails.
# A has a compensation_command that is the audit test target.
PLAN_WITH_COMPENSATION = DAGPlan(
    name="audit-test-plan",
    description="",
    nodes=[
        DAGNode(
            name="success_a",
            task_type="tool_execution",
            command="echo a",
            arguments={},
            dependencies=[],
            compensation_command="echo undo_a",
            compensation_arguments={},
        ),
        DAGNode(
            name="fail_b",
            task_type="tool_execution",
            command="false",  # fails immediately
            arguments={},
            dependencies=["success_a"],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Mock workspace that just echoes a fixed sequence of events
# ---------------------------------------------------------------------------


class MockWorkspace(BaseWorkspace):
    """Workspace that yields a pre-defined sequence of events."""

    def __init__(self, events: list[WorkspaceEvent] | None = None) -> None:
        self._events = events or []
        self.executed_commands: list[tuple[str, dict | None]] = []

    async def setup(self) -> None:
        pass

    async def execute(self, command: str, arguments: dict | None = None, env=None):
        self.executed_commands.append((command, arguments))
        for ev in self._events:
            yield ev

    async def teardown(self) -> None:
        pass

    async def get_workspace_path(self) -> str:
        return "/tmp"

    @property
    def is_active(self) -> bool:
        return True


def make_completing_workspace() -> MockWorkspace:
    return MockWorkspace(
        events=[
            WorkspaceEvent(event_type="stdout_line", data="hi"),
            WorkspaceEvent(event_type="execution_completed", data={"exit_code": 0}),
        ]
    )


def make_failing_workspace() -> MockWorkspace:
    return MockWorkspace(
        events=[
            WorkspaceEvent(
                event_type="execution_failed",
                data={"exit_code": 1, "stderr": "fail"},
            )
        ]
    )


# ---------------------------------------------------------------------------
# Stub auditor
# ---------------------------------------------------------------------------


class StubAuditor:
    """Test double for SecurityAuditor with programmable verdicts."""

    def __init__(self, unsafe_for: set[str] | None = None) -> None:
        # unsafe_for: set of command strings that should be blocked
        self.unsafe_for = set(unsafe_for or [])
        self.calls: list[str] = []

    def _verdict_for(self, command: str) -> Any:
        from celeste.tools.security_auditor import SecurityVerdict

        if command in self.unsafe_for:
            return SecurityVerdict(
                is_safe=False,
                risk_level="high",
                reason=f"test blocked: {command}",
                detected_threats=["test_blocked"],
            )
        return SecurityVerdict(
            is_safe=True, risk_level="safe", reason="ok", detected_threats=[]
        )

    def audit_command(self, command: str, context: str = "") -> Any:
        self.calls.append(command)
        return self._verdict_for(command)

    def check_deterministic(self, command: str) -> Any:
        self.calls.append(command)
        return self._verdict_for(command)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def settings():
    """Provide isolated SQLite-memory settings for each test."""
    s = EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL)
    return s


@pytest.fixture
async def engine_with_auditor(settings):
    """Yield (engine, auditor). Engine is started/stopped around the test."""
    from celeste.core.engine import Engine

    e = Engine(settings=settings)
    await e.start()
    auditor = StubAuditor(unsafe_for={"rm -rf /"})
    e.set_security_auditor(auditor)
    try:
        yield e, auditor
    finally:
        await e.stop()


class TestEngineExecutesSecurityAudit:
    """SEC-002: Engine._execute_node audits the command before execution."""

    @pytest.mark.asyncio
    async def test_safe_command_audited_and_run(self, engine_with_auditor):
        engine, auditor = engine_with_auditor
        wf_id = await engine.submit_workflow(PLAN_WITH_COMPENSATION)
        ws = make_completing_workspace()

        from celeste.database.db import get_session

        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(
                    TaskNode.workflow_id == wf_id,
                    TaskNode.name == "success_a",
                )
            )
            node = result.scalar_one()
            node_id = node.id

        await engine._execute_node(node_id, ws)

        # The auditor must have been called with the node's command.
        assert "echo a" in auditor.calls, (
            "SEC-002: Engine._execute_node did not call the auditor before "
            "running the node command"
        )

    @pytest.mark.asyncio
    async def test_unsafe_command_blocks_execution(self, settings):
        from celeste.core.engine import Engine

        e = Engine(settings=settings)
        await e.start()
        try:
            auditor = StubAuditor(unsafe_for={"echo a"})
            e.set_security_auditor(auditor)
            wf_id = await e.submit_workflow(PLAN_WITH_COMPENSATION)

            ws = make_completing_workspace()
            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "success_a",
                    )
                )
                node = result.scalar_one()
                node_id = node.id

            with pytest.raises(RuntimeError, match="[Ss]ecurity"):
                await e._execute_node(node_id, ws)

            # The workspace must NOT have been asked to execute the unsafe command.
            assert ws.executed_commands == [], (
                f"SEC-002: unsafe command was executed despite audit block: "
                f"{ws.executed_commands!r}"
            )
        finally:
            await e.stop()


class TestEngineCompensationAudits:
    """SEC-007: Engine._handle_failure audits compensation commands."""

    @pytest.mark.asyncio
    async def test_compensation_audited_before_run(self, settings):
        from celeste.core.engine import Engine

        e = Engine(settings=settings)
        await e.start()
        try:
            auditor = StubAuditor(unsafe_for=set())  # all safe
            e.set_security_auditor(auditor)
            wf_id = await e.submit_workflow(PLAN_WITH_COMPENSATION)

            from celeste.database.db import get_session

            async with get_session() as session:
                # Mark success_a as completed so its compensation will trigger
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "success_a",
                    )
                )
                node = result.scalar_one()
                node.status = TaskNodeStatus.COMPLETED

            # Run the compensation handler — it should audit each comp_cmd.
            await e._handle_failure(wf_id)

            # The auditor was called with the compensation command string.
            assert "echo undo_a" in auditor.calls, (
                "SEC-007: compensation command was not audited"
            )
        finally:
            await e.stop()

    @pytest.mark.asyncio
    async def test_unsafe_compensation_blocked(self, settings):
        from celeste.core.engine import Engine

        e = Engine(settings=settings)
        await e.start()
        try:
            auditor = StubAuditor(unsafe_for={"echo undo_a"})
            e.set_security_auditor(auditor)
            wf_id = await e.submit_workflow(PLAN_WITH_COMPENSATION)

            from celeste.database.db import get_session

            async with get_session() as session:
                result = await session.execute(
                    select(TaskNode).where(
                        TaskNode.workflow_id == wf_id,
                        TaskNode.name == "success_a",
                    )
                )
                node = result.scalar_one()
                node.status = TaskNodeStatus.COMPLETED

            # Use a workspace that records every execute() call.
            ws = make_completing_workspace()
            # Inject workspace_factory so the compensation uses our tracker
            e._workspace_factory = lambda: ws  # type: ignore[assignment]

            await e._handle_failure(wf_id)

            # The unsafe compensation command must NOT have been executed.
            assert ws.executed_commands == [], (
                f"SEC-007: unsafe compensation command was executed: "
                f"{ws.executed_commands!r}"
            )
        finally:
            await e.stop()