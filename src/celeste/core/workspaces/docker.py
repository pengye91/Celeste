"""Docker container workspace — container isolation engine.

Stub implementation: setup/teardown define the container config structure,
but execute raises NotImplementedError since Docker is not available in test env.
Defines the interface for Docker/gVisor integration.
"""

from __future__ import annotations

from typing import AsyncIterator

from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent


class DockerWorkspace(BaseWorkspace):
    """Workspace backed by a Docker container for full isolation.

    This is a stub implementation. Setup defines the container configuration
    structure. Execute raises NotImplementedError pending Docker/gVisor
    integration in the deployment environment.
    """

    def __init__(
        self,
        image: str = "python:3.11",
        container_name: str | None = None,
        volumes: dict[str, str] | None = None,
        network: str | None = None,
    ) -> None:
        self._image = image
        self._container_name = container_name
        self._volumes = volumes or {}
        self._network = network
        self._active: bool = False
        self.container_config: dict | None = None

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        """Define container configuration structure."""
        self.container_config = {
            "image": self._image,
            "container_name": self._container_name,
            "volumes": self._volumes,
            "network": self._network,
            "runtime": "runc",  # or "runsc" for gVisor
        }
        self._active = True

    async def execute(
        self,
        command: str,
        arguments: dict | None = None,
        env: dict | None = None,
    ) -> AsyncIterator[WorkspaceEvent]:
        """Execute a command inside the Docker container.

        Raises:
            NotImplementedError: Docker execution is not yet implemented.
        """
        raise NotImplementedError(
            "Docker workspace execution is not yet implemented. "
            "Requires Docker daemon or gVisor runtime."
        )
        yield  # pragma: no cover — makes this an async generator

    async def teardown(self) -> None:
        """Clean up container configuration."""
        self._active = False
        self.container_config = None

    async def get_workspace_path(self) -> str:
        """Return the workspace path inside the container."""
        return "/workspace"
