"""SEC-006: docker workspace must not pass shell=True to subprocess.run.

Tests demonstrate that:
- DockerWorkspace.execute builds an inner_python that calls
  subprocess.run(cmd, shell=True, ...) inside the container.
- This is an injection sink: a malicious `command` can run extra commands.
- The fix is to use a structured argv list (shell=False).
"""

from __future__ import annotations

import inspect
import json

import pytest


# ===========================================================================
# SEC-006: DockerWorkspace must not pass shell=True inside the container
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

    def test_docker_exec_passes_argv_list(self):
        """Audit the docker.py execute path passes a structured argv list."""
        from celeste.core.workspaces import docker as docker_mod

        source = inspect.getsource(docker_mod)
        # The container-side python should accept a list (argv), not a string
        # and run with shell=False.
        assert "shell=False" in source or "shell = False" in source

    def test_docker_payload_uses_argv_field(self):
        """The JSON payload sent to the container should carry a structured argv list."""
        from celeste.core.workspaces import docker as docker_mod

        source = inspect.getsource(docker_mod)
        # Either "argv" key in payload, OR "command + arguments" with a clear
        # structured split (not a single string)
        assert "argv" in source or ("command" in source and "arguments" in source)


class TestDockerWorkspaceShellMetacharsSafe:
    """Behavioural test: shell metachars in `command` must not execute extras."""

    @pytest.mark.asyncio
    async def test_shell_metachars_in_command_not_interpreted(self, monkeypatch):
        """A `command` containing `;` or `&&` must not trigger additional commands.

        We can't actually start a Docker container in unit tests, but we can
        intercept the docker CLI call and inspect what payload would be sent
        to the container, and what the inner_python looks like.
        """
        from celeste.core.workspaces.docker import DockerWorkspace

        captured: dict = {}

        class FakeProcess:
            returncode = 0
            _stdout = b'{"exit_code": 0, "stdout": "", "stderr": ""}'
            _stderr = b""

            async def communicate(self):
                return self._stdout, self._stderr

        async def fake_run(*cmd, **kwargs):
            captured["cmd"] = cmd
            return FakeProcess()

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_run)

        ws = DockerWorkspace(image="python:3.11")
        # bypass setup
        ws._active = True
        events = []
        async for ev in ws.execute("echo hi; touch /tmp/pwned"):
            events.append(ev)

        # The docker exec command's inner_python arg should NOT contain "shell=True"
        cmd = captured["cmd"]
        # find the python -c argument (string with the inner script)
        inner_python = None
        for arg in cmd:
            if isinstance(arg, str) and "subprocess" in arg and "run" in arg:
                inner_python = arg
                break
        assert inner_python is not None, "could not locate inner_python arg in docker exec"
        assert "shell=True" not in inner_python, (
            "SEC-006: inner_python still contains shell=True; metacharacter "
            "injection is possible"
        )
        assert "shell=False" in inner_python or "shell = False" in inner_python, (
            "SEC-006: inner_python must call subprocess.run with shell=False"
        )