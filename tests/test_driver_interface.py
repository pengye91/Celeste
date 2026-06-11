"""Tests for Celeste-DAG Environment Agent Protocol driver interface."""

import asyncio
import os
import signal
import tempfile
from pathlib import Path

import pytest

from celeste.core.agent.driver import (
    BaseDriver,
    CommandResult,
    DirectoryResult,
    FileResult,
    FilesystemDriver,
    PathTraversalError,
    ShellDriver,
    StatResult,
)


# ---------------------------------------------------------------------------
# Result dataclass sanity checks
# ---------------------------------------------------------------------------
def test_command_result_dataclass() -> None:
    cr = CommandResult(exit_code=0, stdout="out", stderr="err", killed_by_signal=None)
    assert cr.exit_code == 0
    assert cr.stdout == "out"
    assert cr.stderr == "err"
    assert cr.killed_by_signal is None


def test_file_result_dataclass() -> None:
    fr = FileResult(content="hello", size=5)
    assert fr.content == "hello"
    assert fr.size == 5


def test_directory_result_dataclass() -> None:
    dr = DirectoryResult(files=["a.txt", "b.py"])
    assert dr.files == ["a.txt", "b.py"]


def test_stat_result_dataclass() -> None:
    sr = StatResult(size=100, modified_time=1234567890.0, permissions=0o644)
    assert sr.size == 100
    assert sr.modified_time == 1234567890.0
    assert sr.permissions == 0o644


# ---------------------------------------------------------------------------
# ShellDriver
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_shell_driver_run_command() -> None:
    """ShellDriver.run_command should execute a command and return stdout/stderr/exit_code."""
    driver = ShellDriver()
    result = await driver.run_command("echo", ["hello"], cwd=None, timeout=5)
    assert isinstance(result, CommandResult)
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.stderr == ""
    assert result.killed_by_signal is None


@pytest.mark.asyncio
async def test_shell_driver_detects_sigkill() -> None:
    """If a subprocess is killed by SIGKILL, killed_by_signal should be 9."""
    driver = ShellDriver()

    async def _kill_after(proc: asyncio.subprocess.Process, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            proc.kill()  # sends SIGKILL
        except ProcessLookupError:
            pass

    proc = await asyncio.create_subprocess_exec(
        "sleep", "30",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    killer = asyncio.create_task(_kill_after(proc, 0.2))
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    await killer

    # Now test via the driver interface using a long sleep and a short timeout
    # so the driver kills it.
    result = await driver.run_command("sleep", ["10"], cwd=None, timeout=0.1)
    assert result.killed_by_signal == signal.SIGKILL


@pytest.mark.asyncio
async def test_shell_driver_run_command_with_cwd() -> None:
    """ShellDriver should respect the cwd parameter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        driver = ShellDriver(cwd=tmpdir)
        result = await driver.run_command("pwd", [], cwd=None, timeout=5)
        assert result.exit_code == 0
        assert Path(result.stdout.strip()) == Path(tmpdir).resolve()


# ---------------------------------------------------------------------------
# FilesystemDriver
# ---------------------------------------------------------------------------
@pytest.fixture
def fs_driver(tmp_path: Path) -> FilesystemDriver:
    return FilesystemDriver(base_path=str(tmp_path))


@pytest.mark.asyncio
async def test_filesystem_driver_read_file(fs_driver: FilesystemDriver, tmp_path: Path) -> None:
    """FilesystemDriver.read_file should return file content and size."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")
    result = await fs_driver.read_file("test.txt")
    assert isinstance(result, FileResult)
    assert result.content == "hello world"
    assert result.size == 11


@pytest.mark.asyncio
async def test_filesystem_driver_write_file(fs_driver: FilesystemDriver, tmp_path: Path) -> None:
    """FilesystemDriver.write_file should create or overwrite a file."""
    await fs_driver.write_file("new.txt", "content")
    assert (tmp_path / "new.txt").read_text() == "content"


@pytest.mark.asyncio
async def test_filesystem_driver_list_directory(fs_driver: FilesystemDriver, tmp_path: Path) -> None:
    """FilesystemDriver.list_directory should return filenames in the directory."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.py").write_text("b")
    (tmp_path / "subdir").mkdir()
    result = await fs_driver.list_directory(".")
    assert isinstance(result, DirectoryResult)
    assert sorted(result.files) == ["a.txt", "b.py", "subdir"]


@pytest.mark.asyncio
async def test_filesystem_driver_delete_file(fs_driver: FilesystemDriver, tmp_path: Path) -> None:
    """FilesystemDriver.delete_file should remove a file."""
    (tmp_path / "to_delete.txt").write_text("x")
    await fs_driver.delete_file("to_delete.txt")
    assert not (tmp_path / "to_delete.txt").exists()


@pytest.mark.asyncio
async def test_filesystem_driver_mkdir(fs_driver: FilesystemDriver, tmp_path: Path) -> None:
    """FilesystemDriver.mkdir should create a directory."""
    await fs_driver.mkdir("nested/dir")
    assert (tmp_path / "nested" / "dir").is_dir()


@pytest.mark.asyncio
async def test_filesystem_driver_stat(fs_driver: FilesystemDriver, tmp_path: Path) -> None:
    """FilesystemDriver.stat should return size, modified_time, and permissions."""
    test_file = tmp_path / "stat_me.txt"
    test_file.write_text("stats")
    result = await fs_driver.stat("stat_me.txt")
    assert isinstance(result, StatResult)
    assert result.size == 5
    assert result.modified_time > 0
    assert result.permissions is not None


@pytest.mark.asyncio
async def test_filesystem_driver_enforces_base_path(fs_driver: FilesystemDriver, tmp_path: Path) -> None:
    """FilesystemDriver should raise PathTraversalError for paths outside base_path."""
    with pytest.raises(PathTraversalError):
        await fs_driver.read_file("../outside.txt")
    with pytest.raises(PathTraversalError):
        await fs_driver.write_file("../outside.txt", "bad")
    with pytest.raises(PathTraversalError):
        await fs_driver.list_directory("..")
    with pytest.raises(PathTraversalError):
        await fs_driver.delete_file("../outside.txt")
    with pytest.raises(PathTraversalError):
        await fs_driver.mkdir("../outside_dir")
    with pytest.raises(PathTraversalError):
        await fs_driver.stat("../outside.txt")


@pytest.mark.asyncio
async def test_filesystem_driver_enforces_base_path_with_symlinks(fs_driver: FilesystemDriver, tmp_path: Path) -> None:
    """FilesystemDriver should raise PathTraversalError for symlink-based traversal."""
    outside = tmp_path.parent / "outside_symlink_target"
    outside.write_text("secret")
    (tmp_path / "link").symlink_to(outside)
    with pytest.raises(PathTraversalError):
        await fs_driver.read_file("link")


# ---------------------------------------------------------------------------
# BaseDriver is abstract
# ---------------------------------------------------------------------------
def test_base_driver_is_abstract() -> None:
    """BaseDriver cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseDriver()
