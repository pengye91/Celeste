"""Docker container workspace — container isolation engine.

Uses asyncio subprocess to call the Docker CLI. Requires Docker to be
installed and the daemon to be running. Falls back to clear errors when
Docker is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent

logger = logging.getLogger(__name__)


class DockerWorkspace(BaseWorkspace):
    """Workspace backed by a Docker container for full isolation.

    Lifecycle:
        1. setup()   → docker run -d (detached container)
        2. execute() → docker exec (run commands inside container)
        3. teardown() → docker stop + rm

    Requires the ``docker`` CLI to be on PATH.
    """

    def __init__(
        self,
        image: str = "python:3.11",
        container_name: str | None = None,
        volumes: dict[str, str] | None = None,
        network: str | None = None,
    ) -> None:
        self._image = image
        self._container_name = container_name or f"celeste-ws-{uuid.uuid4().hex[:12]}"
        self._volumes = volumes or {}
        self._network = network
        self._active: bool = False
        self.container_config: dict | None = None

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        """Create and start a detached Docker container."""
        cmd = [
            "docker", "run", "-d",
            "--name", self._container_name,
            "--entrypoint", "sh",
            self._image,
            "-c", "while true; do sleep 3600; done",
        ]

        if self._network:
            cmd.extend(["--network", self._network])

        for host, container in self._volumes.items():
            cmd.extend(["-v", f"{host}:{container}"])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Docker run failed: {stderr.decode().strip()}"
                )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Docker CLI not found. Ensure Docker is installed and on PATH."
            ) from exc

        self.container_config = {
            "image": self._image,
            "container_name": self._container_name,
            "volumes": self._volumes,
            "network": self._network,
            "runtime": "runc",
        }
        self._active = True
        logger.info("Docker container %s started", self._container_name)

    async def execute(
        self,
        command: str,
        arguments: dict | None = None,
        env: dict | None = None,
    ) -> AsyncIterator[WorkspaceEvent]:
        """Execute a command inside the running Docker container.

        Yields WorkspaceEvent for stdout/stderr lines and completion status.
        """
        if not self._active:
            raise RuntimeError("DockerWorkspace is not active. Call setup() first.")

        args = arguments or {}
        env = env or {}

        # Build a JSON-serialisable payload so the container can parse it.
        payload = json.dumps({"command": command, "arguments": args, "env": env})

        # Use python -c inside the container to run the command safely.
        inner_python = (
            "import json, subprocess, sys; "
            "data = json.loads(sys.argv[1]); "
            "cmd = data['command']; "
            "proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, env={**dict(__import__('os').environ), **data.get('env', {})}); "
            "print(json.dumps({'exit_code': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr}))"
        )

        docker_cmd = [
            "docker", "exec",
            self._container_name,
            "python", "-c", inner_python,
            payload,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError as exc:
            yield WorkspaceEvent(
                event_type="execution_failed",
                data={"error": "Docker CLI not found"},
            )
            return

        if stderr:
            for line in stderr.decode().splitlines():
                yield WorkspaceEvent(event_type="stderr_line", data=line)

        if proc.returncode != 0:
            yield WorkspaceEvent(
                event_type="execution_failed",
                data={"error": stdout.decode().strip() or "docker exec failed"},
            )
            return

        try:
            result = json.loads(stdout.decode())
        except json.JSONDecodeError:
            # Fallback: treat raw stdout as output lines
            for line in stdout.decode().splitlines():
                yield WorkspaceEvent(event_type="stdout_line", data=line)
            yield WorkspaceEvent(event_type="execution_completed", data={"exit_code": 0})
            return

        for line in result.get("stdout", "").splitlines():
            yield WorkspaceEvent(event_type="stdout_line", data=line)
        for line in result.get("stderr", "").splitlines():
            yield WorkspaceEvent(event_type="stderr_line", data=line)

        exit_code = result.get("exit_code", 0)
        if exit_code != 0:
            yield WorkspaceEvent(
                event_type="execution_failed",
                data={"exit_code": exit_code, "error": result.get("stderr", "")},
            )
        else:
            yield WorkspaceEvent(
                event_type="execution_completed",
                data={"exit_code": exit_code},
            )

    async def teardown(self) -> None:
        """Stop and remove the Docker container."""
        if not self._active:
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", "-t", "5", self._container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()

            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", self._container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        except FileNotFoundError:
            logger.warning("Docker CLI not found during teardown")

        self._active = False
        self.container_config = None
        logger.info("Docker container %s removed", self._container_name)

    async def get_workspace_path(self) -> str:
        """Return the workspace path inside the container."""
        return "/workspace"
