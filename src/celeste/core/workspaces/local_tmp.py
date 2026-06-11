"""Local temporary directory workspace — default lightweight engine.

Creates a temporary directory using tempfile.mkdtemp.
Executes commands as asyncio subprocesses inside that directory.
Streams stdout/stderr as WorkspaceEvents.
Cleans up directory on teardown.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import AsyncIterator

from celeste.core.workspaces.base import (
    BaseWorkspace,
    WorkspaceEvent,
    _stream_subprocess_events,
)


class LocalTmpWorkspace(BaseWorkspace):
    """Workspace backed by a local temporary directory.

    Commands execute as asyncio subprocesses inside the temp dir.
    Stdout and stderr are streamed as WorkspaceEvents.
    The directory is removed on teardown.
    """

    def __init__(self, prefix: str = "celeste_ws_") -> None:
        self._prefix = prefix
        self._workspace_path: str | None = None
        self._active: bool = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        """Create a temporary directory for the workspace."""
        self._workspace_path = tempfile.mkdtemp(prefix=self._prefix)
        self._active = True

    async def execute(
        self,
        command: str,
        arguments: dict | None = None,
        env: dict | None = None,
    ) -> AsyncIterator[WorkspaceEvent]:
        """Execute a command as an asyncio subprocess, streaming events.

        Raises:
            RuntimeError: If the workspace is not active (setup not called).
        """
        if not self._active or self._workspace_path is None:
            raise RuntimeError("Workspace is not active. Call setup() first.")

        async for event in _stream_subprocess_events(
            command=command,
            cwd=self._workspace_path,
            env=env,
        ):
            yield event

    async def teardown(self) -> None:
        """Remove the temporary directory."""
        if self._workspace_path is not None and os.path.exists(self._workspace_path):
            shutil.rmtree(self._workspace_path, ignore_errors=True)
        self._workspace_path = None
        self._active = False

    async def get_workspace_path(self) -> str:
        """Return the absolute path to the workspace root."""
        if self._workspace_path is None:
            raise RuntimeError("Workspace path not available. Call setup() first.")
        return self._workspace_path
