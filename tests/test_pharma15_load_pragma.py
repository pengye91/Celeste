"""Regression test for PHARMA-15: seed_data/load.py runs PRAGMA on PostgreSQL.

The loader applies schema.sql via raw SQL, but unconditionally executes
`PRAGMA foreign_keys = ON` first. PostgreSQL doesn't understand PRAGMA,
so a non-sqlite dialect causes an SQL error that the loader does not
catch, the run_local.py wrapper swallows as a warning, and the engine
subsequently can't find tables.

The fix: detect the dialect from the engine and skip PRAGMA for
non-sqlite backends.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
PHARMA_LOADER_PATH = (
    REPO_ROOT / "examples" / "pharma-coldchain" / "seed_data" / "load.py"
)


def _import_loader_module():
    """Load the pharma seed loader module by file path (hyphenated dir name)."""
    spec = importlib.util.spec_from_file_location(
        "_pharma_seed_loader_test", PHARMA_LOADER_PATH
    )
    assert spec and spec.loader, f"could not load spec for {PHARMA_LOADER_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_module_imports_cleanly() -> None:
    """The loader module must be importable without side effects."""
    module = _import_loader_module()
    assert hasattr(module, "load_seed_data"), (
        "load_seed_data must be importable from the pharma seed loader"
    )


def test_apply_schema_gates_pragma_on_sqlite_dialect() -> None:
    """PHARMA-15: _apply_schema must gate PRAGMA on the engine's dialect.

    We can't easily stand up a real PostgreSQL in unit tests, so we
    verify the source gates PRAGMA on the dialect name. Acceptable
    patterns include: `engine.dialect.name == "sqlite"`, branch on
    `"sqlite" in db_url`, or calling a helper that returns False for
    non-sqlite dialects.
    """
    source = PHARMA_LOADER_PATH.read_text()

    # The PRAGMA call must be gated. Either an explicit dialect check or
    # the call must be wrapped in an `if` that mentions sqlite.
    # Simple sanity: `PRAGMA` appears in source, and at least one of
    # `dialect`, `sqlite`, or a guard pattern is present in the same
    # _apply_schema function.
    fn_start = source.find("async def _apply_schema")
    assert fn_start != -1, "_apply_schema function must exist"
    fn_end = source.find("\nasync def ", fn_start + 1)
    if fn_end == -1:
        fn_end = len(source)
    fn_body = source[fn_start:fn_end]

    assert "PRAGMA" in fn_body, "_apply_schema must still emit PRAGMA for sqlite"

    # The PRAGMA call must be wrapped in a guard. We accept several styles.
    guard_patterns = (
        'dialect.name == "sqlite"',
        "dialect.name == 'sqlite'",
        'dialect.name.startswith("sqlite")',
        '"sqlite" in db_url.lower()',
        '"sqlite" in str(',
        'if "sqlite"',
        "if sqlite",
        'is_sqlite',
        "_is_sqlite",
    )
    assert any(p in fn_body for p in guard_patterns), (
        "_apply_schema executes PRAGMA without checking the engine's "
        "dialect. PHARMA-15: detect the dialect and skip PRAGMA when "
        f"not on sqlite. Looked for one of: {guard_patterns}."
    )


@pytest.mark.asyncio
async def test_apply_schema_runs_pragma_for_sqlite(tmp_path: Path) -> None:
    """When the engine IS sqlite, _apply_schema should still execute PRAGMA.

    SQLite supports PRAGMA and foreign_keys = ON is needed for the seed
    loader's ON CONFLICT clauses to behave correctly.
    """
    loader_mod = _import_loader_module()

    schema_path = tmp_path / "schema.sql"
    schema_path.write_text(
        "CREATE TABLE IF NOT EXISTS widgets (id INTEGER PRIMARY KEY);\n"
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    attempted_statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _capture(
        conn, cursor, statement, parameters, context, executemany
    ):  # type: ignore[no-untyped-def]
        attempted_statements.append(statement)

    await loader_mod._apply_schema(engine, schema_path)
    await engine.dispose()

    pragma_statements = [
        s for s in attempted_statements if "PRAGMA" in s.upper()
    ]
    assert pragma_statements, (
        "_apply_schema must still execute at least one PRAGMA when the "
        "dialect is sqlite (foreign_keys = ON is required for ON CONFLICT)."
    )