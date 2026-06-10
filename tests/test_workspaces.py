"""
Tests for workspace engines — BaseWorkspace, LocalTmpWorkspace,
GitWorktreeWorkspace, DockerWorkspace, FirecrackerWorkspace.

Follows strict TDD: these tests are written BEFORE the implementation.
"""

import asyncio
import inspect
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import pytest

from celeste_dag.core.workspaces.base import BaseWorkspace, WorkspaceEvent


# ===========================================================================
# WorkspaceEvent
# ===========================================================================


class TestWorkspaceEvent:
    """WorkspaceEvent data model validation."""

    def test_create_event_with_string_data(self):
        evt = WorkspaceEvent(
            event_type="stdout_line",
            data="hello world",
            timestamp=datetime.now(timezone.utc),
        )
        assert evt.event_type == "stdout_line"
        assert evt.data == "hello world"
        assert isinstance(evt.timestamp, datetime)

    def test_create_event_with_dict_data(self):
        now = datetime.now(timezone.utc)
        evt = WorkspaceEvent(
            event_type="error_occurred",
            data={"exit_code": 1, "message": "command not found"},
            timestamp=now,
        )
        assert evt.event_type == "error_occurred"
        assert isinstance(evt.data, dict)
        assert evt.data["exit_code"] == 1

    def test_event_type_values(self):
        """Known event types should be valid strings."""
        valid_types = [
            "stdout_line",
            "error_occurred",
            "execution_completed",
            "execution_failed",
        ]
        for et in valid_types:
            evt = WorkspaceEvent(
                event_type=et,
                data="",
                timestamp=datetime.now(timezone.utc),
            )
            assert evt.event_type == et

    def test_timestamp_is_timezone_aware(self):
        evt = WorkspaceEvent(
            event_type="stdout_line",
            data="",
            timestamp=datetime.now(timezone.utc),
        )
        assert evt.timestamp.tzinfo is not None


# ===========================================================================
# BaseWorkspace Abstract Interface
# ===========================================================================


class TestBaseWorkspaceAbstract:
    """BaseWorkspace must be abstract and not directly instantiable."""

    def test_cannot_instantiate_base_workspace(self):
        """Attempting to instantiate BaseWorkspace should raise TypeError."""
        with pytest.raises(TypeError):
            BaseWorkspace()

    def test_has_required_abstract_methods(self):
        """BaseWorkspace must define setup, execute, teardown, get_workspace_path, is_active."""
        abstract_methods = BaseWorkspace.__abstractmethods__
        assert "setup" in abstract_methods
        assert "execute" in abstract_methods
        assert "teardown" in abstract_methods
        assert "get_workspace_path" in abstract_methods
        assert "is_active" in abstract_methods

    def test_incomplete_subclass_cannot_instantiate(self):
        """A subclass that doesn't implement all abstracts still can't be instantiated."""

        class IncompleteWorkspace(BaseWorkspace):
            async def setup(self) -> None:
                pass

        with pytest.raises(TypeError):
            IncompleteWorkspace()


# ===========================================================================
# Actor Boundary: no database imports
# ===========================================================================


class TestActorBoundary:
    """Workspace modules must not import database models or shared mutable state."""

    def test_base_workspace_no_db_imports(self):
        """base.py must not import from celeste_dag.database."""
        import celeste_dag.core.workspaces.base as base_mod

        source = inspect.getsource(base_mod)
        assert "from celeste_dag.database" not in source
        assert "import celeste_dag.database" not in source

    def test_local_tmp_no_db_imports(self):
        """local_tmp.py must not import from celeste_dag.database."""
        import celeste_dag.core.workspaces.local_tmp as mod

        source = inspect.getsource(mod)
        assert "from celeste_dag.database" not in source
        assert "import celeste_dag.database" not in source

    def test_git_worktree_no_db_imports(self):
        """git_worktree.py must not import from celeste_dag.database."""
        import celeste_dag.core.workspaces.git_worktree as mod

        source = inspect.getsource(mod)
        assert "from celeste_dag.database" not in source
        assert "import celeste_dag.database" not in source

    def test_docker_no_db_imports(self):
        """docker.py must not import from celeste_dag.database."""
        import celeste_dag.core.workspaces.docker as mod

        source = inspect.getsource(mod)
        assert "from celeste_dag.database" not in source
        assert "import celeste_dag.database" not in source

    def test_firecracker_no_db_imports(self):
        """firecracker.py must not import from celeste_dag.database."""
        import celeste_dag.core.workspaces.firecracker as mod

        source = inspect.getsource(mod)
        assert "from celeste_dag.database" not in source
        assert "import celeste_dag.database" not in source

    def test_workspace_state_isolation(self):
        """Two workspace instances must not share mutable state."""
        from celeste_dag.core.workspaces.local_tmp import LocalTmpWorkspace

        ws1 = LocalTmpWorkspace()
        ws2 = LocalTmpWorkspace()
        # They should have independent internal state
        assert ws1 is not ws2


# ===========================================================================
# LocalTmpWorkspace
# ===========================================================================


@pytest.fixture
def local_ws():
    """Provide a fresh LocalTmpWorkspace instance."""
    from celeste_dag.core.workspaces.local_tmp import LocalTmpWorkspace

    return LocalTmpWorkspace()


class TestLocalTmpSetup:
    """LocalTmpWorkspace.setup creates a temporary directory."""

    @pytest.mark.asyncio
    async def test_setup_creates_directory(self, local_ws):
        await local_ws.setup()
        path = await local_ws.get_workspace_path()
        assert os.path.isdir(path)
        await local_ws.teardown()

    @pytest.mark.asyncio
    async def test_setup_is_active(self, local_ws):
        """After setup, is_active must be True."""
        await local_ws.setup()
        assert local_ws.is_active is True
        await local_ws.teardown()

    @pytest.mark.asyncio
    async def test_not_active_before_setup(self, local_ws):
        """Before setup, is_active must be False."""
        assert local_ws.is_active is False

    @pytest.mark.asyncio
    async def test_not_active_after_teardown(self, local_ws):
        """After teardown, is_active must be False."""
        await local_ws.setup()
        assert local_ws.is_active is True
        await local_ws.teardown()
        assert local_ws.is_active is False

    @pytest.mark.asyncio
    async def test_workspace_path_is_absolute(self, local_ws):
        await local_ws.setup()
        path = await local_ws.get_workspace_path()
        assert os.path.isabs(path)
        await local_ws.teardown()


class TestLocalTmpTeardown:
    """LocalTmpWorkspace.teardown removes the temporary directory."""

    @pytest.mark.asyncio
    async def test_teardown_removes_directory(self, local_ws):
        await local_ws.setup()
        path = await local_ws.get_workspace_path()
        assert os.path.isdir(path)
        await local_ws.teardown()
        assert not os.path.exists(path)

    @pytest.mark.asyncio
    async def test_teardown_idempotent(self, local_ws):
        """Calling teardown multiple times should not raise."""
        await local_ws.setup()
        await local_ws.teardown()
        await local_ws.teardown()  # Should not raise


class TestLocalTmpExecute:
    """LocalTmpWorkspace.execute runs commands and streams events."""

    @pytest.mark.asyncio
    async def test_execute_simple_command(self, local_ws):
        """Execute a simple echo command and collect stdout events."""
        await local_ws.setup()
        events = []
        async for event in local_ws.execute("echo hello"):
            events.append(event)

        await local_ws.teardown()

        # Should have at least a stdout_line and execution_completed
        assert len(events) >= 1
        stdout_events = [e for e in events if e.event_type == "stdout_line"]
        completed_events = [e for e in events if e.event_type == "execution_completed"]
        assert len(stdout_events) >= 1
        assert len(completed_events) == 1
        assert "hello" in stdout_events[0].data

    @pytest.mark.asyncio
    async def test_execute_streams_multiple_lines(self, local_ws):
        """Multi-line output should produce multiple stdout_line events."""
        await local_ws.setup()
        events = []
        async for event in local_ws.execute("echo line1 && echo line2 && echo line3"):
            events.append(event)

        await local_ws.teardown()

        stdout_events = [e for e in events if e.event_type == "stdout_line"]
        assert len(stdout_events) == 3
        assert "line1" in stdout_events[0].data
        assert "line2" in stdout_events[1].data
        assert "line3" in stdout_events[2].data

    @pytest.mark.asyncio
    async def test_execute_failing_command(self, local_ws):
        """A command that exits non-zero should produce execution_failed."""
        await local_ws.setup()
        events = []
        async for event in local_ws.execute("exit 1"):
            events.append(event)

        await local_ws.teardown()

        failed_events = [e for e in events if e.event_type == "execution_failed"]
        assert len(failed_events) == 1

    @pytest.mark.asyncio
    async def test_execute_stderr_captured(self, local_ws):
        """Stderr output should appear as events."""
        await local_ws.setup()
        events = []
        async for event in local_ws.execute("echo error_msg >&2"):
            events.append(event)

        await local_ws.teardown()

        # stderr lines should be captured (as stdout_line or error_occurred)
        all_data = [e.data for e in events if isinstance(e.data, str)]
        combined = " ".join(all_data)
        assert "error_msg" in combined

    @pytest.mark.asyncio
    async def test_execute_with_env_vars(self, local_ws):
        """Pass environment variables to the subprocess."""
        await local_ws.setup()
        events = []
        async for event in local_ws.execute(
            "echo $MY_TEST_VAR",
            env={"MY_TEST_VAR": "test_value_123"},
        ):
            events.append(event)

        await local_ws.teardown()

        stdout_events = [e for e in events if e.event_type == "stdout_line"]
        assert len(stdout_events) >= 1
        assert "test_value_123" in stdout_events[0].data

    @pytest.mark.asyncio
    async def test_execute_in_correct_directory(self, local_ws):
        """Commands should run inside the workspace directory."""
        await local_ws.setup()
        ws_path = await local_ws.get_workspace_path()
        events = []
        async for event in local_ws.execute("pwd"):
            events.append(event)

        await local_ws.teardown()

        stdout_events = [e for e in events if e.event_type == "stdout_line"]
        assert len(stdout_events) >= 1
        # pwd output should match workspace path (possibly with newline)
        assert ws_path in stdout_events[0].data.strip()

    @pytest.mark.asyncio
    async def test_execute_writes_files_in_workspace(self, local_ws):
        """Commands can create files that persist in the workspace dir."""
        await local_ws.setup()
        async for _ in local_ws.execute("echo content > test_file.txt"):
            pass

        ws_path = await local_ws.get_workspace_path()
        file_path = os.path.join(ws_path, "test_file.txt")
        assert os.path.exists(file_path)
        with open(file_path) as f:
            assert "content" in f.read()

        await local_ws.teardown()

    @pytest.mark.asyncio
    async def test_execute_not_active_raises(self, local_ws):
        """Executing before setup should raise an error."""
        with pytest.raises(RuntimeError):
            async for _ in local_ws.execute("echo hello"):
                pass


class TestLocalTmpContextManager:
    """LocalTmpWorkspace supports async context manager protocol."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        from celeste_dag.core.workspaces.local_tmp import LocalTmpWorkspace

        ws = LocalTmpWorkspace()
        path = None
        async with ws:
            assert ws.is_active is True
            path = await ws.get_workspace_path()
            assert os.path.isdir(path)

        # After exiting context, workspace should be torn down
        assert ws.is_active is False
        assert not os.path.exists(path)

    @pytest.mark.asyncio
    async def test_context_manager_execute(self):
        from celeste_dag.core.workspaces.local_tmp import LocalTmpWorkspace

        ws = LocalTmpWorkspace()
        async with ws:
            events = []
            async for event in ws.execute("echo inside_context"):
                events.append(event)

            stdout_events = [e for e in events if e.event_type == "stdout_line"]
            assert len(stdout_events) >= 1
            assert "inside_context" in stdout_events[0].data


# ===========================================================================
# GitWorktreeWorkspace
# ===========================================================================


@pytest.fixture
def temp_git_repo(tmp_path):
    """Create a temporary git repository for worktree tests."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    # Create an initial commit
    readme = repo_dir / "README.md"
    readme.write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    return str(repo_dir)


class TestGitWorktreeSetup:
    """GitWorktreeWorkspace creates a git worktree for isolation."""

    @pytest.mark.asyncio
    async def test_creates_worktree(self, temp_git_repo):
        from celeste_dag.core.workspaces.git_worktree import GitWorktreeWorkspace

        ws = GitWorktreeWorkspace(repo_path=temp_git_repo, branch_name="test-branch")
        await ws.setup()
        assert ws.is_active is True
        ws_path = await ws.get_workspace_path()
        assert os.path.isdir(ws_path)

        # The worktree should be a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=ws_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        await ws.teardown()

    @pytest.mark.asyncio
    async def test_worktree_is_separate_branch(self, temp_git_repo):
        from celeste_dag.core.workspaces.git_worktree import GitWorktreeWorkspace

        ws = GitWorktreeWorkspace(repo_path=temp_git_repo, branch_name="feature-x")
        await ws.setup()
        ws_path = await ws.get_workspace_path()

        # The current branch in the worktree should be feature-x
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=ws_path,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "feature-x"

        await ws.teardown()


class TestGitWorktreeTeardown:
    """GitWorktreeWorkspace cleans up the worktree."""

    @pytest.mark.asyncio
    async def test_teardown_removes_worktree(self, temp_git_repo):
        from celeste_dag.core.workspaces.git_worktree import GitWorktreeWorkspace

        ws = GitWorktreeWorkspace(repo_path=temp_git_repo, branch_name="cleanup-test")
        await ws.setup()
        ws_path = await ws.get_workspace_path()
        assert os.path.isdir(ws_path)

        await ws.teardown()
        assert not os.path.exists(ws_path)
        assert ws.is_active is False


class TestGitWorktreeExecute:
    """GitWorktreeWorkspace can execute commands in the worktree."""

    @pytest.mark.asyncio
    async def test_execute_in_worktree(self, temp_git_repo):
        from celeste_dag.core.workspaces.git_worktree import GitWorktreeWorkspace

        ws = GitWorktreeWorkspace(repo_path=temp_git_repo, branch_name="exec-test")
        await ws.setup()

        events = []
        async for event in ws.execute("echo worktree_hello"):
            events.append(event)

        stdout_events = [e for e in events if e.event_type == "stdout_line"]
        assert len(stdout_events) >= 1
        assert "worktree_hello" in stdout_events[0].data

        await ws.teardown()


class TestGitWorktreeContextManager:
    """GitWorktreeWorkspace supports async context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self, temp_git_repo):
        from celeste_dag.core.workspaces.git_worktree import GitWorktreeWorkspace

        ws = GitWorktreeWorkspace(repo_path=temp_git_repo, branch_name="ctx-test")
        path = None
        async with ws:
            assert ws.is_active is True
            path = await ws.get_workspace_path()
            assert os.path.isdir(path)

        assert ws.is_active is False
        assert not os.path.exists(path)


# ===========================================================================
# DockerWorkspace (Stub)
# ===========================================================================


class TestDockerWorkspaceStub:
    """DockerWorkspace is a stub that raises NotImplementedError."""

    @pytest.mark.asyncio
    async def test_setup_defines_config(self):
        from celeste_dag.core.workspaces.docker import DockerWorkspace

        ws = DockerWorkspace(image="python:3.11")
        # Setup should work (just defines config)
        await ws.setup()
        assert ws.container_config is not None
        assert ws.container_config["image"] == "python:3.11"
        await ws.teardown()

    @pytest.mark.asyncio
    async def test_execute_raises_not_implemented(self):
        from celeste_dag.core.workspaces.docker import DockerWorkspace

        ws = DockerWorkspace(image="python:3.11")
        await ws.setup()
        with pytest.raises(NotImplementedError, match="[Dd]ocker"):
            async for _ in ws.execute("echo hello"):
                pass
        await ws.teardown()

    @pytest.mark.asyncio
    async def test_teardown_is_safe(self):
        from celeste_dag.core.workspaces.docker import DockerWorkspace

        ws = DockerWorkspace(image="python:3.11")
        await ws.setup()
        await ws.teardown()  # Should not raise
        assert ws.is_active is False


# ===========================================================================
# FirecrackerWorkspace (Stub)
# ===========================================================================


class TestFirecrackerWorkspaceStub:
    """FirecrackerWorkspace is a stub that raises NotImplementedError."""

    @pytest.mark.asyncio
    async def test_setup_defines_config(self):
        from celeste_dag.core.workspaces.firecracker import FirecrackerWorkspace

        ws = FirecrackerWorkspace(kernel_path="/path/to/kernel")
        await ws.setup()
        assert ws.vm_config is not None
        assert ws.vm_config["kernel_path"] == "/path/to/kernel"
        await ws.teardown()

    @pytest.mark.asyncio
    async def test_execute_raises_not_implemented(self):
        from celeste_dag.core.workspaces.firecracker import FirecrackerWorkspace

        ws = FirecrackerWorkspace(kernel_path="/path/to/kernel")
        await ws.setup()
        with pytest.raises(NotImplementedError, match="[Ff]irecracker|[Kk]vm|[Mm]icro[Vv][Mm]"):
            async for _ in ws.execute("echo hello"):
                pass
        await ws.teardown()

    @pytest.mark.asyncio
    async def test_teardown_is_safe(self):
        from celeste_dag.core.workspaces.firecracker import FirecrackerWorkspace

        ws = FirecrackerWorkspace(kernel_path="/path/to/kernel")
        await ws.setup()
        await ws.teardown()
        assert ws.is_active is False


# ===========================================================================
# Integration: full workflow with LocalTmpWorkspace
# ===========================================================================


class TestLocalTmpIntegration:
    """Integration tests for full command lifecycle."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Setup -> execute multiple commands -> teardown."""
        from celeste_dag.core.workspaces.local_tmp import LocalTmpWorkspace

        ws = LocalTmpWorkspace()
        await ws.setup()
        ws_path = await ws.get_workspace_path()

        # Create a file
        async for _ in ws.execute("echo 'hello' > file1.txt"):
            pass
        assert os.path.exists(os.path.join(ws_path, "file1.txt"))

        # Read it back
        events = []
        async for event in ws.execute("cat file1.txt"):
            events.append(event)
        stdout = " ".join(e.data for e in events if e.event_type == "stdout_line")
        assert "hello" in stdout

        # Modify and verify
        async for _ in ws.execute("echo 'world' >> file1.txt"):
            pass
        events = []
        async for event in ws.execute("cat file1.txt"):
            events.append(event)
        stdout = " ".join(e.data for e in events if e.event_type == "stdout_line")
        assert "hello" in stdout
        assert "world" in stdout

        await ws.teardown()
        assert not os.path.exists(ws_path)

    @pytest.mark.asyncio
    async def test_event_timestamps_ordered(self):
        """Events should have non-decreasing timestamps."""
        from celeste_dag.core.workspaces.local_tmp import LocalTmpWorkspace

        ws = LocalTmpWorkspace()
        async with ws:
            events = []
            async for event in ws.execute("echo a && echo b && echo c"):
                events.append(event)

            timestamps = [e.timestamp for e in events]
            for i in range(1, len(timestamps)):
                assert timestamps[i] >= timestamps[i - 1]
