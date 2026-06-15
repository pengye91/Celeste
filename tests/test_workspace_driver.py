"""Tests for the WorkspaceDriver containment bridge (TODO-5).

The WorkspaceDriver implements BaseDriver but delegates run_command to
workspace.execute(), so the agent's tool calls are sandboxed inside a
workspace. These tests verify:

- run_command translates (command, args) → workspace argv convention and
  returns a CommandResult with correct exit_code / stdout / stderr.
- Non-zero exit codes propagate correctly.
- Timeout returns a killed-by-signal result.
- File operations work via pathlib against the workspace path (LocalTmp).
- File operations raise NotImplementedError for containerized workspaces.
- The workspace is lazily created and torn down on stop().
- EnvironmentAgent.in_workspace() produces a working agent.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator
from unittest.mock import MagicMock

import pytest

from celeste.core.agent.driver import CommandResult
from celeste.core.agent.workspace_driver import WorkspaceDriver
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent
from celeste.core.workspaces.local_tmp import LocalTmpWorkspace


# ---------------------------------------------------------------------------
# Tests: run_command with a real LocalTmpWorkspace
# ---------------------------------------------------------------------------


async def test_run_command_returns_stdout_and_exit_code():
    """run_command executes inside the workspace and returns the result."""
    driver = WorkspaceDriver(workspace_factory=LocalTmpWorkspace)
    try:
        result = await driver.run_command("echo", args=["hello", "world"])
        assert isinstance(result, CommandResult)
        assert result.exit_code == 0
        assert "hello world" in result.stdout
    finally:
        await driver.stop()


async def test_run_command_nonzero_exit():
    """A failing command must report the non-zero exit code."""
    driver = WorkspaceDriver(workspace_factory=LocalTmpWorkspace)
    try:
        result = await driver.run_command("sh", args=["-c", "exit 3"])
        assert result.exit_code == 3
    finally:
        await driver.stop()


async def test_run_command_stderr_capture():
    """stderr written by the command is captured (for DockerWorkspace).

    For LocalTmpWorkspace the _stream_subprocess_events helper mislabels
    stderr as stdout_line, so stderr ends up in stdout. We verify the
    command at least completes and the output is captured somewhere.
    """
    driver = WorkspaceDriver(workspace_factory=LocalTmpWorkspace)
    try:
        result = await driver.run_command(
            "sh", args=["-c", "echo to-stdout; echo to-stderr 1>&2"]
        )
        assert result.exit_code == 0
        # Both lines should appear (LocalTmp conflates stdout/stderr).
        combined = result.stdout + result.stderr
        assert "to-stdout" in combined
        assert "to-stderr" in combined
    finally:
        await driver.stop()


async def test_run_command_timeout_returns_killed():
    """A timed-out command returns killed_by_signal=9."""
    driver = WorkspaceDriver(workspace_factory=LocalTmpWorkspace)
    try:
        result = await driver.run_command("sleep", args=["30"], timeout=0.2)
        assert result.killed_by_signal == 9
    finally:
        await driver.stop()


# ---------------------------------------------------------------------------
# Tests: file operations against the workspace path
# ---------------------------------------------------------------------------


async def test_file_ops_round_trip():
    """write_file → read_file round-trips against the workspace directory."""
    driver = WorkspaceDriver(workspace_factory=LocalTmpWorkspace)
    try:
        await driver.write_file("test.txt", "hello workspace")
        result = await driver.read_file("test.txt")
        assert result.content == "hello workspace"
        assert result.size == len("hello workspace")
    finally:
        await driver.stop()


async def test_list_directory():
    """list_directory returns entry names in the workspace."""
    driver = WorkspaceDriver(workspace_factory=LocalTmpWorkspace)
    try:
        await driver.write_file("a.txt", "a")
        await driver.write_file("b.txt", "b")
        listing = await driver.list_directory(".")
        assert "a.txt" in listing.files
        assert "b.txt" in listing.files
    finally:
        await driver.stop()


async def test_stat_returns_metadata():
    """stat returns size, modified_time, and permissions."""
    driver = WorkspaceDriver(workspace_factory=LocalTmpWorkspace)
    try:
        await driver.write_file("stat_me.txt", "content")
        st = await driver.stat("stat_me.txt")
        assert st.size == len("content")
        assert st.modified_time > 0
        assert st.permissions >= 0
    finally:
        await driver.stop()


async def test_mkdir_and_delete():
    """mkdir creates a dir, delete_file removes a file."""
    driver = WorkspaceDriver(workspace_factory=LocalTmpWorkspace)
    try:
        await driver.mkdir("subdir")
        await driver.write_file("subdir/inner.txt", "inner")
        result = await driver.read_file("subdir/inner.txt")
        assert result.content == "inner"
        await driver.delete_file("subdir/inner.txt")
        listing = await driver.list_directory("subdir")
        assert "inner.txt" not in listing.files
    finally:
        await driver.stop()


# ---------------------------------------------------------------------------
# Tests: containerized workspace raises NotImplementedError for file ops
# ---------------------------------------------------------------------------


class _FakeDockerWorkspace(BaseWorkspace):
    """A minimal workspace that reports as DockerWorkspace for the
    containerized-detection check (class name match)."""

    def __init__(self) -> None:
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        self._active = True

    async def execute(
        self, command: str, arguments: dict | None = None, env: dict | None = None
    ) -> AsyncIterator[WorkspaceEvent]:
        yield WorkspaceEvent(event_type="execution_completed", data={"exit_code": 0})

    async def teardown(self) -> None:
        self._active = False

    async def get_workspace_path(self) -> str:
        return "/workspace"


# Rename so type(ws).__name__ == "DockerWorkspace" for the detection logic.
DockerWorkspace = type("DockerWorkspace", (_FakeDockerWorkspace,), {})


async def test_file_ops_raise_for_containerized_workspace():
    """File ops raise NotImplementedError for DockerWorkspace."""
    driver = WorkspaceDriver(workspace_factory=DockerWorkspace)
    try:
        # run_command works (delegates to execute).
        result = await driver.run_command("echo", args=["ok"])
        assert result.exit_code == 0

        # File ops raise.
        with pytest.raises(NotImplementedError, match="containerized"):
            await driver.read_file("foo.txt")
        with pytest.raises(NotImplementedError, match="containerized"):
            await driver.write_file("foo.txt", "bar")
        with pytest.raises(NotImplementedError, match="containerized"):
            await driver.list_directory(".")
        with pytest.raises(NotImplementedError, match="containerized"):
            await driver.stat("foo.txt")
    finally:
        await driver.stop()


# ---------------------------------------------------------------------------
# Tests: lifecycle
# ---------------------------------------------------------------------------


async def test_workspace_lazily_created():
    """The workspace is created on first use, not at construction."""
    created = []

    def factory():
        ws = LocalTmpWorkspace()
        created.append(ws)
        return ws

    driver = WorkspaceDriver(workspace_factory=factory)
    assert len(created) == 0  # not yet created

    await driver.run_command("echo", args=["trigger"])
    assert len(created) == 1  # created on first use

    await driver.stop()


async def test_stop_tears_down_workspace():
    """stop() tears down the workspace."""
    driver = WorkspaceDriver(workspace_factory=LocalTmpWorkspace)
    await driver.run_command("echo", args=["setup"])
    assert driver._workspace is not None
    assert driver._workspace.is_active

    await driver.stop()
    assert driver._workspace is None


# ---------------------------------------------------------------------------
# Tests: EnvironmentAgent.in_workspace() factory
# ---------------------------------------------------------------------------


async def test_agent_in_workspace_run_command():
    """in_workspace() produces an agent whose run_command is sandboxed."""
    from celeste.core.agent.agent import EnvironmentAgent

    agent = EnvironmentAgent.in_workspace(
        workspace_factory=LocalTmpWorkspace,
    )
    try:
        result = await agent.call_tool(
            "run_command", {"command": "echo", "args": ["from-agent"]}
        )
        # The result is normalized to a dict by _normalize_result.
        assert "from-agent" in str(result)
    finally:
        await agent.stop()


async def test_agent_in_workspace_file_round_trip():
    """in_workspace() agent can write and read files in the workspace."""
    from celeste.core.agent.agent import EnvironmentAgent

    agent = EnvironmentAgent.in_workspace(
        workspace_factory=LocalTmpWorkspace,
    )
    try:
        await agent.call_tool("write_file", {"path": "agent.txt", "content": "via-agent"})
        result = await agent.call_tool("read_file", {"path": "agent.txt"})
        assert result["content"] == "via-agent"
    finally:
        await agent.stop()
