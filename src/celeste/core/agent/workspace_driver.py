"""Workspace-backed driver — bridges BaseDriver to BaseWorkspace.

TODO-5 (containment model): the OPA loop executes commands through the
agent's driver. Previously the only concrete drivers were ``ShellDriver``
and ``FilesystemDriver``, both of which execute directly on the engine
host's filesystem — bypassing the workspace sandbox entirely.

``WorkspaceDriver`` implements ``BaseDriver`` but delegates ``run_command``
to ``workspace.execute()``, so the agent's tool calls run inside whichever
sandbox the workspace provides (LocalTmp temp dir, Docker container, or
Firecracker microVM). This unifies the OPA-loop and legacy-DAG execution
paths under one containment boundary.

See ``docs/containment-model.md`` for the full design rationale.
"""

from __future__ import annotations

import asyncio
import logging
import os
import stat as stat_module
from pathlib import Path
from typing import Callable, Optional

from celeste.core.agent.driver import (
    BaseDriver,
    CommandResult,
    DirectoryResult,
    FileResult,
    StatResult,
)
from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent

logger = logging.getLogger(__name__)


class WorkspaceDriver(BaseDriver):
    """Driver that proxies tool calls through a ``BaseWorkspace`` sandbox.

    The driver lazily creates a workspace on first use (via the injected
    factory) and tears it down on :meth:`stop`. Once active,
    :meth:`run_command` translates the ``BaseDriver`` calling convention
    (``command + args``) into the ``BaseWorkspace`` convention
    (``command + {"argv": [...]}``), consumes the ``WorkspaceEvent`` stream,
    and returns a ``CommandResult``.

    File operations (``read_file``, ``write_file``, ``list_directory``,
    ``stat``) are implemented via ``pathlib`` against the workspace's local
    path. This works for ``LocalTmpWorkspace`` and ``GitWorktreeWorkspace``
    (shared filesystem). For ``DockerWorkspace`` / ``FirecrackerWorkspace``
    (containerized/VM filesystems not mounted on the host), these raise
    ``NotImplementedError`` — callers should use ``run_command("cat", ...)``
    instead.
    """

    def __init__(
        self,
        workspace_factory: Callable[[], BaseWorkspace],
    ) -> None:
        self._workspace_factory = workspace_factory
        self._workspace: BaseWorkspace | None = None
        self._workspace_path: str | None = None
        # Whether the workspace is a containerized/VM type whose filesystem
        # is not directly accessible from the host process. If True, file
        # operations raise NotImplementedError. Detected from the workspace
        # class name after creation.
        self._is_containerized: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _ensure_workspace(self) -> BaseWorkspace:
        """Lazily create + enter the workspace on first use."""
        if self._workspace is not None:
            return self._workspace

        ws = self._workspace_factory()
        await ws.setup()
        self._workspace = ws
        self._workspace_path = await ws.get_workspace_path()

        # Detect containerized workspaces whose filesystem isn't on the host.
        # We check by class name rather than isinstance to avoid importing
        # Docker/Firecracker (which may not be available on all platforms).
        cls_name = type(ws).__name__
        self._is_containerized = cls_name in ("DockerWorkspace", "FirecrackerWorkspace")

        logger.info(
            "WorkspaceDriver: workspace created (%s, path=%s, containerized=%s)",
            cls_name,
            self._workspace_path,
            self._is_containerized,
        )
        return ws

    async def stop(self) -> None:
        """Tear down the workspace if it was created."""
        if self._workspace is not None:
            try:
                await self._workspace.teardown()
            except Exception:
                logger.debug("WorkspaceDriver: teardown error", exc_info=True)
            self._workspace = None
            self._workspace_path = None

    # ------------------------------------------------------------------
    # run_command — the core bridge
    # ------------------------------------------------------------------

    async def run_command(
        self,
        command: str,
        args: list[str],
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        """Execute a command inside the workspace sandbox.

        Translates ``(command, args)`` into the workspace's
        ``execute(command, arguments={"argv": [...]})`` convention, consumes
        the event stream, and returns a ``CommandResult``.
        """
        ws = await self._ensure_workspace()

        # The workspace layer runs commands in its own get_workspace_path();
        # cwd from the caller is not applicable (the workspace owns the
        # working directory). Log it for traceability.
        if cwd is not None:
            logger.debug(
                "WorkspaceDriver: ignoring cwd=%r (workspace path=%s)",
                cwd,
                self._workspace_path,
            )

        argv = [command] + list(args)

        async def _consume() -> CommandResult:
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            exit_code = 0

            async for event in ws.execute(command, arguments={"argv": argv}):
                if event.event_type == "stdout_line":
                    # NOTE: LocalTmpWorkspace's _stream_subprocess_events
                    # mislabels stderr as "stdout_line" (base.py:95). We
                    # accumulate everything into stdout for that workspace;
                    # DockerWorkspace correctly emits "stderr_line".
                    stdout_lines.append(str(event.data))
                elif event.event_type == "stderr_line":
                    stderr_lines.append(str(event.data))
                elif event.event_type == "execution_completed":
                    data = event.data if isinstance(event.data, dict) else {}
                    exit_code = int(data.get("exit_code", 0))
                elif event.event_type == "execution_failed":
                    data = event.data if isinstance(event.data, dict) else {}
                    exit_code = int(data.get("exit_code", 1))
                    # If the failure event carries stderr, prefer it.
                    if "stderr" in data and data["stderr"]:
                        stderr_lines = [str(data["stderr"])]

            return CommandResult(
                exit_code=exit_code,
                stdout="\n".join(stdout_lines),
                stderr="\n".join(stderr_lines),
            )

        if timeout is not None:
            try:
                return await asyncio.wait_for(_consume(), timeout=timeout)
            except asyncio.TimeoutError:
                return CommandResult(
                    exit_code=-1,
                    stdout="",
                    stderr="",
                    killed_by_signal=9,
                )
        return await _consume()

    # ------------------------------------------------------------------
    # File operations — via pathlib against the workspace path.
    #
    # These work for LocalTmpWorkspace and GitWorktreeWorkspace (the
    # workspace directory is on the host filesystem). For DockerWorkspace /
    # FirecrackerWorkspace the container filesystem is NOT mounted on the
    # host, so these raise NotImplementedError.
    # ------------------------------------------------------------------

    async def _resolve_host_path(self, path: str) -> Path:
        """Resolve a path relative to the workspace's host-side directory.

        Ensures the workspace is created first (lazy init). Raises
        NotImplementedError if the workspace is containerized.
        """
        await self._ensure_workspace()
        if self._is_containerized:
            raise NotImplementedError(
                "File operations are not supported for containerized "
                "workspaces (Docker/Firecracker). The container filesystem "
                "is not mounted on the host. Use run_command('cat', ...) "
                "or run_command('ls', ...) instead."
            )
        if self._workspace_path is None:
            raise RuntimeError("Workspace not initialized")
        p = Path(path)
        if not p.is_absolute():
            p = Path(self._workspace_path) / p
        return p

    async def read_file(self, path: str) -> FileResult:
        p = await self._resolve_host_path(path)
        content = p.read_text(encoding="utf-8")
        return FileResult(content=content, size=len(content.encode("utf-8")))

    async def write_file(self, path: str, content: str) -> FileResult:
        p = await self._resolve_host_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return FileResult(content=content, size=len(content.encode("utf-8")))

    async def list_directory(self, path: str) -> DirectoryResult:
        p = await self._resolve_host_path(path)
        files = [entry.name for entry in os.scandir(p)]
        return DirectoryResult(files=files)

    async def delete_file(self, path: str) -> None:
        p = await self._resolve_host_path(path)
        Path(p).unlink()

    async def mkdir(self, path: str) -> None:
        p = await self._resolve_host_path(path)
        Path(p).mkdir(parents=True, exist_ok=True)

    async def stat(self, path: str) -> StatResult:
        p = await self._resolve_host_path(path)
        st = Path(p).stat()
        return StatResult(
            size=st.st_size,
            modified_time=st.st_mtime,
            permissions=stat_module.S_IMODE(st.st_mode),
        )
