"""Tests for the incremental snapshot with mtime cache (TODO-8).

Follows strict TDD. Covers:
- First snapshot returns all files (cold cache) and incremental=False.
- Second snapshot with no changes returns an empty diff.
- Mutating a file surfaces it on the next snapshot.
- force_full=True bypasses the cache and returns everything.
- recursive=False keeps the legacy shallow behaviour.
"""

from __future__ import annotations

import os
import time

import pytest

from celeste.core.agent.agent import EnvironmentAgent
from celeste.core.agent.driver import ShellDriver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """A small workspace tree:

    tmp/
      a.txt
      sub/
        b.txt
    """
    (tmp_path / "a.txt").write_text("hello")
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world")
    return tmp_path


def _agent(workspace) -> EnvironmentAgent:
    """Build an in-process agent whose drivers point at the workspace."""
    return EnvironmentAgent(
        shell_driver=ShellDriver(cwd=str(workspace)),
        fs_driver=ShellDriver(cwd=str(workspace)),
        workdir=str(workspace),
    )


def _touch(path, content: str | None = None) -> None:
    """Write/modify a file and bump its mtime into the future.

    Sleeping on mtime granularity is flaky on some filesystems (HFS has 1s
    resolution), so we explicitly set the mtime forward instead of relying
    on time.sleep.
    """
    if content is not None:
        path.write_text(content)
    else:
        path.touch()
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5.0))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_first_snapshot_is_cold(workspace):
    """A first snapshot returns every file with incremental=False."""
    agent = _agent(workspace)
    result = await agent.call_tool("snapshot", {"paths": [str(workspace)]})

    assert result["incremental"] is False
    files = result["files"]
    assert str(workspace / "a.txt") in files
    assert str(workspace / "sub" / "b.txt") in files
    assert "modified_time" in files[str(workspace / "a.txt")]


async def test_second_snapshot_with_no_changes_is_empty(workspace):
    """A second snapshot with no mutations returns an empty diff."""
    agent = _agent(workspace)
    await agent.call_tool("snapshot", {"paths": [str(workspace)]})
    result = await agent.call_tool("snapshot", {"paths": [str(workspace)]})

    assert result["incremental"] is True
    assert result["changed_count"] == 0
    assert result["files"] == {}


async def test_mutated_file_surfaces_on_next_snapshot(workspace):
    """A file modified between snapshots must appear in the next diff."""
    agent = _agent(workspace)
    await agent.call_tool("snapshot", {"paths": [str(workspace)]})

    _touch(workspace / "a.txt", content="changed")

    result = await agent.call_tool("snapshot", {"paths": [str(workspace)]})
    assert result["incremental"] is True
    changed = result["files"]
    assert str(workspace / "a.txt") in changed
    # The untouched file must NOT be reported as changed.
    assert str(workspace / "sub" / "b.txt") not in changed


async def test_force_full_bypasses_cache(workspace):
    """force_full=True returns every file even when the cache is warm."""
    agent = _agent(workspace)
    # Warm the cache.
    await agent.call_tool("snapshot", {"paths": [str(workspace)]})

    result = await agent.call_tool(
        "snapshot", {"paths": [str(workspace)], "force_full": True}
    )
    assert result["incremental"] is False
    files = result["files"]
    assert str(workspace / "a.txt") in files
    assert str(workspace / "sub" / "b.txt") in files


async def test_recursive_false_keeps_legacy_shallow_behaviour(workspace):
    """recursive=False returns the legacy one-level listing shape."""
    agent = _agent(workspace)
    result = await agent.call_tool(
        "snapshot", {"paths": [str(workspace)], "recursive": False}
    )
    # Legacy shape: files is a {path: [names]} dict, no incremental metadata.
    assert "incremental" not in result
    files = result["files"]
    assert str(workspace) in files
    # Shallow listing includes a.txt and sub/, not nested files.
    names = set(files[str(workspace)])
    assert "a.txt" in names
    assert "sub" in names
    assert "b.txt" not in names


async def test_new_file_appears_and_disappears_correctly(workspace):
    """Creating then deleting a file is reflected across snapshots."""
    agent = _agent(workspace)
    await agent.call_tool("snapshot", {"paths": [str(workspace)]})

    new_file = workspace / "c.txt"
    new_file.write_text("new")
    # Bump mtime so the change is unambiguous.
    st = new_file.stat()
    os.utime(new_file, (st.st_atime, st.st_mtime + 5.0))

    result = await agent.call_tool("snapshot", {"paths": [str(workspace)]})
    assert str(new_file) in result["files"]
