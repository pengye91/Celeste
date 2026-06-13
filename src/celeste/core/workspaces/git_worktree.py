"""Git worktree workspace — coding vertical.

Creates a git worktree branch for code isolation.
Wraps LocalTmpWorkspace-style execution for running commands.
Manages git worktree creation and removal.
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

from celeste.core.workspaces.base import (
    BaseWorkspace,
    WorkspaceEvent,
    _stream_subprocess_events,
)


class GitWorktreeWorkspace(BaseWorkspace):
    """Workspace backed by a git worktree for code isolation.

    Creates a new branch and worktree from the given repository.
    Commands execute inside the worktree directory as subprocesses.
    The worktree is removed on teardown.
    """

    def __init__(
        self,
        repo_path: str,
        branch_name: str,
        base_ref: str = "HEAD",
    ) -> None:
        self._repo_path = repo_path
        self._branch_name = branch_name
        self._base_ref = base_ref
        self._worktree_path: str | None = None
        self._active: bool = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        """Create a git worktree from the repository."""
        # Use a temporary location under the system temp dir
        worktree_dir = os.path.join(
            os.environ.get("TMPDIR", "/tmp"),
            f"celeste_worktree_{self._branch_name}",
        )

        # Create a new branch and worktree using async subprocess
        cmd = [
            "git", "worktree", "add",
            worktree_dir,
            "-b", self._branch_name,
            self._base_ref,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._repo_path,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to create git worktree: {stderr.decode()}"
            )

        self._worktree_path = worktree_dir
        self._active = True

    async def execute(
        self,
        command: str,
        arguments: dict | None = None,
        env: dict | None = None,
    ) -> AsyncIterator[WorkspaceEvent]:
        """Execute a command inside the worktree directory.

        If ``arguments`` contains an ``argv`` list, it is used directly as the
        structured argv list (SEC-001: no shell interpretation). Otherwise the
        single ``command`` string is passed as ``argv[0]``.
        """
        if not self._active or self._worktree_path is None:
            raise RuntimeError("Workspace is not active. Call setup() first.")

        argv_list = None
        if isinstance(arguments, dict):
            maybe_argv = arguments.get("argv")
            if isinstance(maybe_argv, list) and all(isinstance(x, str) for x in maybe_argv):
                argv_list = maybe_argv

        # SEC-001: never invoke /bin/sh. The full argv list is built
        # from arguments["argv"] if provided (caller includes executable
        # as argv[0]); otherwise we use the single ``command`` string
        # as argv[0].
        if argv_list is not None:
            full_argv = argv_list
        elif command is not None:
            full_argv = [command]
        else:
            raise ValueError("execute() requires either command or arguments['argv']")

        stream_kwargs = {"argv": full_argv, "cwd": self._worktree_path, "env": env}

        async for event in _stream_subprocess_events(**stream_kwargs):
            yield event

    async def teardown(self) -> None:
        """Remove the git worktree and its branch."""
        if self._worktree_path is not None and os.path.exists(self._worktree_path):
            # Remove the worktree via git using async subprocess
            proc = await asyncio.create_subprocess_exec(
                "git", "worktree", "remove", self._worktree_path, "--force",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._repo_path,
            )
            await proc.communicate()

            # Delete the branch using async subprocess
            proc = await asyncio.create_subprocess_exec(
                "git", "branch", "-D", self._branch_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._repo_path,
            )
            await proc.communicate()

        self._worktree_path = None
        self._active = False

    async def get_workspace_path(self) -> str:
        """Return the absolute path to the worktree root."""
        if self._worktree_path is None:
            raise RuntimeError("Workspace path not available. Call setup() first.")
        return self._worktree_path
