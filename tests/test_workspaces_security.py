"""SEC-001 / SEC-006: command-injection prevention tests for workspaces.

Tests demonstrate that:
- _stream_subprocess_events must NOT use asyncio.create_subprocess_shell (SEC-001)
- Shell metacharacters in command strings must not be interpreted
- DockerWorkspace.execute must NOT pass shell=True to subprocess.run inside the container
"""

from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from typing import Any

import pytest


# ===========================================================================
# SEC-001: workspace base uses shell=False, structured argv list
# ===========================================================================


class TestStreamSubprocessUsesExec:
    """_stream_subprocess_events must NOT use asyncio.create_subprocess_shell."""

    def test_source_does_not_call_create_subprocess_shell(self):
        """Audit the source of base.py: create_subprocess_shell must not be used."""
        from celeste.core.workspaces import base as base_mod

        source = inspect.getsource(base_mod)
        assert "create_subprocess_shell" not in source, (
            "SEC-001: _stream_subprocess_events must use create_subprocess_exec "
            "with argv list, not create_subprocess_shell (which interprets shell "
            "metacharacters)"
        )

    def test_source_calls_create_subprocess_exec(self):
        """Audit the source of base.py: create_subprocess_exec must be used."""
        from celeste.core.workspaces import base as base_mod

        source = inspect.getsource(base_mod)
        assert "create_subprocess_exec" in source


class TestShellMetacharsNotInterpreted:
    """Shell metacharacters in a command string must not be interpreted."""

    @pytest.mark.asyncio
    async def test_shell_metachar_semicolon_not_executed(self, tmp_path):
        """`echo hi; touch /tmp/celeste_pwned` must NOT create the file.

        With shell=True the second command after `;` runs. With shell=False,
        the entire string is treated as a single argv[0] which fails to exec.
        The injection marker must not be created even if the exec fails.
        """
        from celeste.core.workspaces.base import _stream_subprocess_events

        marker = os.path.join(str(tmp_path), "pwned_via_semicolon")
        cmd = f"echo hi; touch {marker}"

        events = []
        try:
            async for ev in _stream_subprocess_events(cmd, cwd=str(tmp_path)):
                events.append(ev)
        except (FileNotFoundError, OSError):
            # The string is treated as a literal exec name; no shell, so exec fails.
            # Either outcome is acceptable; the marker must NOT exist.
            pass

        # The injection file must NOT exist
        assert not os.path.exists(marker), (
            f"SEC-001: shell injection succeeded — {marker} was created. "
            f"_stream_subprocess_events still interprets shell metacharacters."
        )

    @pytest.mark.asyncio
    async def test_shell_metachar_pipe_not_executed(self, tmp_path):
        """`echo hi | tee /tmp/pwned` must NOT create /tmp/pwned."""
        from celeste.core.workspaces.base import _stream_subprocess_events

        marker = os.path.join(str(tmp_path), "pwned_via_pipe")
        cmd = f"echo hi | tee {marker}"

        try:
            async for _ in _stream_subprocess_events(cmd, cwd=str(tmp_path)):
                pass
        except (FileNotFoundError, OSError):
            pass

        assert not os.path.exists(marker), (
            "SEC-001: pipe metacharacter was interpreted; injection succeeded"
        )

    @pytest.mark.asyncio
    async def test_shell_metachar_backtick_not_executed(self, tmp_path):
        """Command substitution via backticks must not run."""
        from celeste.core.workspaces.base import _stream_subprocess_events

        marker = os.path.join(str(tmp_path), "pwned_via_backtick")
        cmd = f"echo `touch {marker}`"

        try:
            async for _ in _stream_subprocess_events(cmd, cwd=str(tmp_path)):
                pass
        except (FileNotFoundError, OSError):
            pass

        assert not os.path.exists(marker), (
            "SEC-001: backtick command substitution was interpreted; injection succeeded"
        )


class TestArgvListSupport:
    """_stream_subprocess_events should accept a structured argv list."""

    @pytest.mark.asyncio
    async def test_runs_argv_list(self, tmp_path):
        """A structured argv list (e.g. ['echo', 'hello']) should run cleanly."""
        from celeste.core.workspaces.base import _stream_subprocess_events

        events: list[Any] = []
        async for ev in _stream_subprocess_events(
            argv=["echo", "from_argv_list"],
            cwd=str(tmp_path),
        ):
            events.append(ev)

        stdout = [e for e in events if e.event_type == "stdout_line"]
        assert any("from_argv_list" in str(e.data) for e in stdout)


# ===========================================================================
# SEC-006: DockerWorkspace.execute uses shell=False
# ===========================================================================


class TestDockerWorkspaceShellFalse:
    """DockerWorkspace must not pass shell=True inside the container."""

    def test_docker_source_does_not_use_shell_true(self):
        """The container-side python must not enable shell=True."""
        from celeste.core.workspaces import docker as docker_mod

        source = inspect.getsource(docker_mod)
        assert "shell=True" not in source, (
            "SEC-006: DockerWorkspace.execute passes shell=True to subprocess.run "
            "inside the container, allowing shell metacharacter injection"
        )

    def test_docker_exec_uses_argv_list(self):
        """Audit the docker.py execute path uses argv-style list."""
        from celeste.core.workspaces import docker as docker_mod

        source = inspect.getsource(docker_mod)
        # The container-side python should accept a list, not a string.
        assert "subprocess.run(cmd" in source or "subprocess.run([" in source or "shell=False" in source