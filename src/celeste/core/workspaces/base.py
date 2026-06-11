"""Abstract workspace interface — the Actor Boundary.

All concrete physical sandboxes must inherit from BaseWorkspace.
Workspaces encapsulate state strictly: no access to database models or shared state.
They execute processes and stream outputs as async WorkspaceEvent messages.
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Self


@dataclass(frozen=True)
class WorkspaceEvent:
    """Async message event emitted by workspace actors.

    Immutable dataclass representing a single event from workspace execution.
    """

    event_type: str  # "stdout_line", "error_occurred", "execution_completed", "execution_failed"
    data: str | dict
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


async def _stream_subprocess_events(
    command: str,
    cwd: str,
    env: dict | None = None,
) -> AsyncIterator[WorkspaceEvent]:
    """Run *command* as an async subprocess and yield WorkspaceEvents.

    Shared implementation used by LocalTmpWorkspace and GitWorktreeWorkspace
    (and any future concrete workspace that spawns local processes).
    """
    proc_env = dict(os.environ)
    if env:
        proc_env.update(env)

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=proc_env,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    # Stream stdout lines as they arrive
    if proc.stdout is not None:
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
            stdout_lines.append(line)
            yield WorkspaceEvent(
                event_type="stdout_line",
                data=line,
                timestamp=datetime.now(timezone.utc),
            )

    # Wait for process to finish
    await proc.wait()

    # Read any remaining stderr
    if proc.stderr is not None:
        stderr_data = await proc.stderr.read()
        if stderr_data:
            for line in stderr_data.decode("utf-8", errors="replace").splitlines():
                stderr_lines.append(line)
                yield WorkspaceEvent(
                    event_type="stdout_line",
                    data=line,
                    timestamp=datetime.now(timezone.utc),
                )

    # Emit terminal event
    if proc.returncode == 0:
        yield WorkspaceEvent(
            event_type="execution_completed",
            data={"exit_code": 0},
            timestamp=datetime.now(timezone.utc),
        )
    else:
        yield WorkspaceEvent(
            event_type="execution_failed",
            data={
                "exit_code": proc.returncode,
                "stderr": "\n".join(stderr_lines) if stderr_lines else "",
            },
            timestamp=datetime.now(timezone.utc),
        )


class BaseWorkspace(ABC):
    """Abstract workspace interface — Actor Boundary.

    Each workspace must:
    - Encapsulate state strictly (no access to database models or shared state)
    - Execute processes and stream outputs as async WorkspaceEvent messages
    - Support async context manager protocol (async with workspace:)
    - Accept state inputs during initialization as immutable values
    """

    @abstractmethod
    async def setup(self) -> None:
        """Initialize the physical workspace (create dir, boot container, etc.)."""

    @abstractmethod
    async def execute(
        self,
        command: str,
        arguments: dict | None = None,
        env: dict | None = None,
    ) -> AsyncIterator[WorkspaceEvent]:
        """Execute a command inside the workspace, streaming events."""
        yield  # pragma: no cover — makes this an async generator for type checking

    @abstractmethod
    async def teardown(self) -> None:
        """Clean up workspace resources (remove dir, stop container, etc.)."""

    @abstractmethod
    async def get_workspace_path(self) -> str:
        """Return the absolute path to the workspace root."""

    @property
    @abstractmethod
    def is_active(self) -> bool:
        """Whether the workspace is currently set up and ready for commands."""

    async def __aenter__(self) -> Self:
        """Enter async context manager — setup the workspace."""
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager — teardown the workspace."""
        await self.teardown()
