"""Celeste-DAG Environment Agent Protocol — Driver Interface.

Provides abstract BaseDriver and two concrete implementations:
- ShellDriver: executes commands via asyncio subprocess
- FilesystemDriver: constrained filesystem access within a base path
"""

from __future__ import annotations

import asyncio
import os
import stat as stat_module
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class PathTraversalError(ValueError):
    """Raised when a FilesystemDriver operation attempts to escape base_path."""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandResult:
    """Result of a shell command execution."""

    exit_code: int
    stdout: str
    stderr: str
    killed_by_signal: Optional[int] = None


@dataclass(frozen=True)
class FileResult:
    """Result of a file read/write operation."""

    content: str
    size: int


@dataclass(frozen=True)
class DirectoryResult:
    """Result of a directory listing."""

    files: list[str]


@dataclass(frozen=True)
class StatResult:
    """Result of a stat operation."""

    size: int
    modified_time: float
    permissions: int


# ---------------------------------------------------------------------------
# BaseDriver
# ---------------------------------------------------------------------------
class BaseDriver(ABC):
    """Abstract base for environment agent drivers.

    All methods are async and return strongly-typed result objects.
    """

    @abstractmethod
    async def run_command(
        self,
        command: str,
        args: list[str],
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        """Execute a command and return its result."""

    @abstractmethod
    async def read_file(self, path: str) -> FileResult:
        """Read a file and return its content and size."""

    @abstractmethod
    async def write_file(self, path: str, content: str) -> FileResult:
        """Write content to a file and return the result."""

    @abstractmethod
    async def list_directory(self, path: str) -> DirectoryResult:
        """List entries in a directory."""

    @abstractmethod
    async def delete_file(self, path: str) -> None:
        """Delete a file."""

    @abstractmethod
    async def mkdir(self, path: str) -> None:
        """Create a directory (and parents if needed)."""

    @abstractmethod
    async def stat(self, path: str) -> StatResult:
        """Return metadata about a path."""


# ---------------------------------------------------------------------------
# ShellDriver
# ---------------------------------------------------------------------------
class ShellDriver(BaseDriver):
    """Driver that executes commands in a local shell via asyncio subprocess."""

    def __init__(self, cwd: Optional[str] = None) -> None:
        self._cwd = cwd

    async def run_command(
        self,
        command: str,
        args: list[str],
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        effective_cwd = cwd or self._cwd
        proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=effective_cwd,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()
            return CommandResult(
                exit_code=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                killed_by_signal=9,
            )

        returncode = proc.returncode if proc.returncode is not None else -1
        killed_by_signal: Optional[int] = None
        if returncode < 0:
            killed_by_signal = abs(returncode)

        return CommandResult(
            exit_code=returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            killed_by_signal=killed_by_signal,
        )

    async def read_file(self, path: str) -> FileResult:
        p = Path(path)
        content = p.read_text(encoding="utf-8")
        return FileResult(content=content, size=len(content.encode("utf-8")))

    async def write_file(self, path: str, content: str) -> FileResult:
        p = Path(path)
        p.write_text(content, encoding="utf-8")
        return FileResult(content=content, size=len(content.encode("utf-8")))

    async def list_directory(self, path: str) -> DirectoryResult:
        p = Path(path)
        files = [entry.name for entry in os.scandir(p)]
        return DirectoryResult(files=files)

    async def delete_file(self, path: str) -> None:
        Path(path).unlink()

    async def mkdir(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    async def stat(self, path: str) -> StatResult:
        st = Path(path).stat()
        return StatResult(
            size=st.st_size,
            modified_time=st.st_mtime,
            permissions=stat_module.S_IMODE(st.st_mode),
        )


# ---------------------------------------------------------------------------
# FilesystemDriver
# ---------------------------------------------------------------------------
class FilesystemDriver(BaseDriver):
    """Driver providing constrained filesystem access within a base path.

    All operations validate that the resolved path stays within ``base_path``.
    Raises PathTraversalError on any traversal attempt.
    """

    def __init__(self, base_path: str) -> None:
        self._base = Path(base_path).resolve()

    def _resolve(self, path: str) -> Path:
        """Resolve *path* relative to base_path and enforce containment."""
        target = (self._base / path).resolve()
        # On some systems resolve() follows symlinks; re-check containment.
        try:
            target.relative_to(self._base)
        except ValueError:
            raise PathTraversalError(
                f"Path '{path}' resolves outside base path '{self._base}'"
            )
        return target

    async def run_command(
        self,
        command: str,
        args: list[str],
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        raise NotImplementedError("FilesystemDriver does not support run_command")

    async def read_file(self, path: str) -> FileResult:
        target = self._resolve(path)
        content = target.read_text(encoding="utf-8")
        return FileResult(content=content, size=len(content.encode("utf-8")))

    async def write_file(self, path: str, content: str) -> FileResult:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return FileResult(content=content, size=len(content.encode("utf-8")))

    async def list_directory(self, path: str) -> DirectoryResult:
        target = self._resolve(path)
        files = [entry.name for entry in os.scandir(target)]
        return DirectoryResult(files=files)

    async def delete_file(self, path: str) -> None:
        target = self._resolve(path)
        target.unlink()

    async def mkdir(self, path: str) -> None:
        target = self._resolve(path)
        target.mkdir(parents=True, exist_ok=True)

    async def stat(self, path: str) -> StatResult:
        target = self._resolve(path)
        st = target.stat()
        return StatResult(
            size=st.st_size,
            modified_time=st.st_mtime,
            permissions=stat_module.S_IMODE(st.st_mode),
        )
