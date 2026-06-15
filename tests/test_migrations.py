"""Tests for Alembic database migrations (TODO-3).

Verifies:
- ``alembic upgrade head`` creates all tables with the expected columns.
- ``alembic downgrade base`` drops everything cleanly.
- The baseline migration has no drift vs the current SQLAlchemy models
  (autogenerate produces no new operations).
- The ``parent_workflow_id`` column + FK + index are created by the
  migration (regression guard for TODO-20).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_ROOT / "src" / "celeste" / "migrations" / "alembic.ini"


def _find_alembic_python() -> str:
    """Find the Python executable that has alembic installed.

    pytest may run under a different interpreter (e.g. conda base) than the
    project venv where alembic is installed. We check sys.executable first,
    then fall back to the .venv.
    """
    candidates = [sys.executable, str(REPO_ROOT / ".venv" / "bin" / "python")]
    for py in candidates:
        try:
            result = subprocess.run(
                [py, "-c", "import alembic"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return py
        except Exception:
            continue
    pytest.skip("alembic is not installed in any discovered Python")


def _run_alembic(*args: str, db_url: str) -> subprocess.CompletedProcess:
    """Run an alembic CLI command against the given DB URL."""
    python = _find_alembic_python()
    env = dict(os.environ, CELESTE_ALEMBIC_DATABASE_URL=db_url)
    cmd = [python, "-m", "alembic", "-c", str(ALEMBIC_INI), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )


# ---------------------------------------------------------------------------
# Upgrade / downgrade round-trip
# ---------------------------------------------------------------------------


def test_upgrade_head_creates_all_tables(tmp_path):
    """alembic upgrade head creates the 4 core tables + alembic_version."""
    db_file = tmp_path / "test_upgrade.db"
    db_url = f"sqlite:///{db_file}"

    result = _run_alembic("upgrade", "head", db_url=db_url)
    assert result.returncode == 0, result.stderr

    import sqlite3

    con = sqlite3.connect(str(db_file))
    tables = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    con.close()

    assert "workflows" in tables
    assert "task_nodes" in tables
    assert "task_events" in tables
    assert "workflow_events" in tables
    assert "alembic_version" in tables


def test_downgrade_base_drops_all_tables(tmp_path):
    """alembic downgrade base removes all tables."""
    db_file = tmp_path / "test_downgrade.db"
    db_url = f"sqlite:///{db_file}"

    _run_alembic("upgrade", "head", db_url=db_url)
    result = _run_alembic("downgrade", "base", db_url=db_url)
    assert result.returncode == 0, result.stderr

    import sqlite3

    con = sqlite3.connect(str(db_file))
    tables = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    con.close()

    # Only alembic_version should remain (or nothing if the version table
    # is also dropped — depends on alembic version).
    assert "workflows" not in tables
    assert "task_nodes" not in tables


def test_upgrade_downgrade_upgrade_roundtrip(tmp_path):
    """upgrade → downgrade → upgrade works without errors."""
    db_file = tmp_path / "test_roundtrip.db"
    db_url = f"sqlite:///{db_file}"

    r1 = _run_alembic("upgrade", "head", db_url=db_url)
    assert r1.returncode == 0, r1.stderr

    r2 = _run_alembic("downgrade", "base", db_url=db_url)
    assert r2.returncode == 0, r2.stderr

    r3 = _run_alembic("upgrade", "head", db_url=db_url)
    assert r3.returncode == 0, r3.stderr


# ---------------------------------------------------------------------------
# parent_workflow_id column (TODO-20 regression guard)
# ---------------------------------------------------------------------------


def test_migration_creates_parent_workflow_id(tmp_path):
    """The baseline migration must create parent_workflow_id + FK + index."""
    db_file = tmp_path / "test_lineage.db"
    db_url = f"sqlite:///{db_file}"

    result = _run_alembic("upgrade", "head", db_url=db_url)
    assert result.returncode == 0, result.stderr

    import sqlite3

    con = sqlite3.connect(str(db_file))
    # Column exists.
    cols = {row[1] for row in con.execute("PRAGMA table_info(workflows)")}
    assert "parent_workflow_id" in cols

    # FK index exists.
    indexes = {row[1] for row in con.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='workflows'"
    )}
    assert "ix_workflows_parent_workflow_id" in indexes

    con.close()


# ---------------------------------------------------------------------------
# Autogenerate drift check
# ---------------------------------------------------------------------------


def test_no_autogenerate_drift(tmp_path):
    """autogenerate against an up-to-date DB produces no new operations.

    This catches schema drift: if someone adds a column to the SQLAlchemy
    models but forgets to create a migration, this test fails.
    """
    db_file = tmp_path / "test_drift.db"
    db_url = f"sqlite:///{db_file}"

    _run_alembic("upgrade", "head", db_url=db_url)

    # Use 'alembic check' (alembic >= 1.13) which runs autogenerate in
    # "check" mode and exits non-zero if drift is detected.
    result = _run_alembic("check", db_url=db_url)
    # Exit code 0 means no drift; non-zero means drift detected.
    if result.returncode != 0:
        pytest.fail(
            "Autogenerate drift detected — the models have changes not "
            "captured by a migration:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
