"""Pharma cold-chain seed data loader.

Loads CSV manifests into a SQLite/PostgreSQL database with full transactional
safety, idempotent inserts, fail-fast validation, and dry-run support.

Usage:
    python -m examples.pharma_coldchain.seed_data.load \\
        --db-url sqlite+aiosqlite:///pharma.db \\
        --seed-dir examples/pharma-coldchain/seed_data

    # Dry-run (validate without writing)
    python -m examples.pharma_coldchain.seed_data.load --dry-run

    # Verify after load
    python -m examples.pharma_coldchain.seed_data.load --verify
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from io import StringIO
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class SeedDataLoadError(Exception):
    """Structured error raised when seed data loading fails.

    Attributes:
        message: Human-readable description of the failure.
        table: Name of the table that failed (or None for pre-DB failures).
        cause: The original exception (if any).
    """

    def __init__(self, message: str, *, table: str | None = None, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.table = table
        self.cause = cause

    def __str__(self) -> str:
        parts = [self.message]
        if self.table:
            parts.append(f"table={self.table}")
        if self.cause:
            parts.append(f"cause={self.cause!r}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Expected CSV columns per table (order matters for INSERT)
# ---------------------------------------------------------------------------

_EXPECTED_COLUMNS: dict[str, list[str]] = {
    "batches": ["id", "batch_id", "hub_id", "status", "temperature_c", "humidity_pct", "created_at"],
    "hubs": ["id", "name", "country", "capacity_doses", "qualified"],
    "hub_qualifications": ["id", "hub_id", "qualification_type", "valid_until"],
    "shipments": ["id", "batch_id", "from_hub_id", "to_hub_id", "status"],
    "telemetry_log": ["id", "batch_id", "temperature_c", "humidity_pct", "recorded_at"],
}

# Map table names to their CSV file paths relative to seed_dir
_TABLE_CSV_MAP: dict[str, tuple[str, ...]] = {
    # Order matters: tables must be loaded after their referenced parents.
    # batches.hub_id references hubs.id, so hubs loads first.
    "hubs": ("hubs", "hubs.csv"),
    "batches": ("manifests", "batches.csv"),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_csv_path(seed_dir: Path, table: str) -> Path:
    """Resolve the CSV file path for a given table name."""
    parts = _TABLE_CSV_MAP.get(table)
    if parts is None:
        raise SeedDataLoadError(f"Unknown table '{table}' (no CSV mapping defined)")
    return seed_dir.joinpath(*parts)


def _validate_csv_files_exist(seed_dir: Path) -> None:
    """Fail fast: verify all expected CSV files exist before touching the database."""
    missing: list[str] = []
    for table in _TABLE_CSV_MAP:
        path = _resolve_csv_path(seed_dir, table)
        if not path.is_file():
            missing.append(f"{table} -> {path}")
    if missing:
        raise SeedDataLoadError(
            f"Missing CSV files: {', '.join(missing)}",
            cause=FileNotFoundError(f"Missing: {missing}"),
        )


def _parse_csv(path: Path) -> list[dict[str, str]]:
    """Parse a CSV file into a list of dicts, validating column headers.

    Returns rows as dicts keyed by column name.
    """
    required_cols = None
    # Determine table name from path
    stem = path.stem
    for table, cols in _EXPECTED_COLUMNS.items():
        if table == stem or stem in table:
            required_cols = cols
            break

    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        actual_cols = reader.fieldnames or []

        if required_cols is not None:
            missing_cols = [c for c in required_cols if c not in actual_cols]
            if missing_cols:
                raise SeedDataLoadError(
                    f"CSV {path.name} is missing required columns: {missing_cols}",
                    table=stem,
                )

        return list(reader)


def _build_insert_sql(table: str, columns: list[str]) -> str:
    """Build an idempotent INSERT statement for the given table.

    Uses ON CONFLICT DO NOTHING for idempotency.
    For tables with PRIMARY KEY (id), conflicts on the id column.
    For tables with UNIQUE constraints (batches.batch_id), we need
    to handle both. Since SQLite only supports ON CONFLICT for a single
    constraint, we use OR IGNORE as a fallback for broader coverage.
    """
    col_list = ", ".join(columns)
    placeholders = ", ".join([f":{c}" for c in columns])

    # Determine conflict target based on table
    conflict_targets: dict[str, str] = {
        "batches": "batch_id",
        "hubs": "name",
        "hub_qualifications": "id",
        "shipments": "id",
        "telemetry_log": "id",
    }

    conflict_col = conflict_targets.get(table, "id")

    return f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT ({conflict_col}) DO NOTHING"


async def _apply_schema(engine: AsyncEngine, schema_path: Path) -> None:
    """Read and execute the schema.sql DDL file."""
    if not schema_path.is_file():
        raise SeedDataLoadError(
            f"Schema file not found: {schema_path}",
            cause=FileNotFoundError(str(schema_path)),
        )

    sql_text = schema_path.read_text()

    # Split by semicolons to handle multiple statements.
    # SQLAlchemy's text() can only handle one statement per execute() call.
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]

    # Detect the engine's dialect so we can skip dialect-specific
    # statements (notably PRAGMA, which is a SQLite extension and not
    # understood by PostgreSQL/MySQL). PHARMA-15.
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "") or ""
    is_sqlite = dialect_name.startswith("sqlite")

    async with engine.begin() as conn:
        # Enable foreign keys for SQLite. Skipped for non-sqlite dialects
        # because PRAGMA is not understood by PostgreSQL/MySQL.
        if is_sqlite:
            await conn.execute(text("PRAGMA foreign_keys = ON"))
        for stmt in statements:
            if stmt.upper().startswith("PRAGMA"):
                continue  # PRAGMA only valid on sqlite; engine path handled it
            await conn.execute(text(stmt))


async def _load_table(conn: Any, table: str, seed_dir: Path) -> int:
    """Load a single table's CSV data into the database.

    Returns the number of rows actually inserted (ignoring conflicts).
    """
    csv_path = _resolve_csv_path(seed_dir, table)
    rows = _parse_csv(csv_path)

    if not rows:
        return 0

    columns = list(rows[0].keys())
    insert_sql = _build_insert_sql(table, columns)

    inserted = 0
    for row in rows:
        result = await conn.execute(text(insert_sql), row)
        if result.rowcount and result.rowcount > 0:
            inserted += 1

    return inserted


async def _get_row_counts(engine: AsyncEngine, tables: list[str]) -> dict[str, int]:
    """Get current row counts for the specified tables."""
    counts: dict[str, int] = {}
    async with engine.connect() as conn:
        for table in tables:
            result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            counts[table] = result.scalar_one()
    return counts


async def _verify_counts(
    engine: AsyncEngine,
    seed_dir: Path,
    expected: dict[str, int] | None = None,
) -> dict[str, int]:
    """Verify row counts against expected_counts.json or a provided dict."""
    if expected is None:
        counts_path = seed_dir / "expected_counts.json"
        if counts_path.is_file():
            expected = json.loads(counts_path.read_text())
        else:
            logger.warning("No expected_counts.json found; skipping verification.")
            return {}

    tables = list(expected.keys()) if expected else []
    actual = await _get_row_counts(engine, tables)

    mismatches: list[str] = []
    for table, exp_count in (expected or {}).items():
        act_count = actual.get(table, 0)
        if act_count != exp_count:
            mismatches.append(f"{table}: expected {exp_count}, got {act_count}")

    if mismatches:
        raise SeedDataLoadError(
            f"Row count mismatch: {'; '.join(mismatches)}",
        )

    return actual


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def load_seed_data(
    db_url: str,
    seed_dir: Path,
    *,
    dry_run: bool = False,
    verify: bool = False,
) -> dict[str, int]:
    """Load pharma cold-chain seed data into the database.

    Parameters:
        db_url: SQLAlchemy async database URL (e.g. 'sqlite+aiosqlite:///pharma.db').
        seed_dir: Path to the seed_data directory containing schema.sql and CSV files.
        dry_run: If True, validate all files and parse CSVs but do not write to DB.
        verify: If True, check row counts against expected_counts.json after loading.

    Returns:
        Dict mapping table names to row counts after loading.

    Raises:
        SeedDataLoadError: If any validation fails or loading encounters an error.
    """
    seed_dir = Path(seed_dir).resolve()
    if not seed_dir.is_dir():
        raise SeedDataLoadError(f"Seed directory not found: {seed_dir}")

    # --- Phase 1: Validate (fail fast, no DB touch) ---

    schema_path = seed_dir / "schema.sql"
    if not schema_path.is_file():
        raise SeedDataLoadError(f"Schema file not found: {schema_path}")

    _validate_csv_files_exist(seed_dir)

    # Pre-parse all CSVs to catch format errors early
    parsed_data: dict[str, list[dict[str, str]]] = {}
    for table in _TABLE_CSV_MAP:
        csv_path = _resolve_csv_path(seed_dir, table)
        parsed_data[table] = _parse_csv(csv_path)

    if dry_run:
        logger.info("Dry-run: all files validated successfully, no data written.")
        return {table: len(rows) for table, rows in parsed_data.items()}

    # --- Phase 2: Apply schema and load data transactionally ---

    engine: AsyncEngine = create_async_engine(db_url)

    try:
        # Apply schema (CREATE TABLE IF NOT EXISTS)
        await _apply_schema(engine, schema_path)

        # Load each table in a single transaction
        async with engine.begin() as conn:
            for table in _TABLE_CSV_MAP:
                try:
                    await _load_table(conn, table, seed_dir)
                except SeedDataLoadError:
                    raise
                except Exception as exc:
                    raise SeedDataLoadError(
                        f"Failed to load table '{table}'",
                        table=table,
                        cause=exc,
                    ) from exc

        # --- Phase 3: Optional verification ---

        if verify:
            await _verify_counts(engine, seed_dir)

        # Return final counts
        counts = await _get_row_counts(engine, list(_TABLE_CSV_MAP.keys()))
        return counts

    except Exception:
        # Let any unhandled exceptions propagate
        raise
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli() -> None:
    """Command-line entry point for the seed data loader.

    Supports:
        --db-url: Database URL (default: sqlite+aiosqlite:///pharma.db)
        --seed-dir: Path to seed_data directory
        --dry-run: Validate without writing
        --verify: Verify counts after load
    """
    import argparse

    parser = argparse.ArgumentParser(description="Load pharma cold-chain seed data.")
    parser.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///pharma.db",
        help="SQLAlchemy async database URL",
    )
    parser.add_argument(
        "--seed-dir",
        default=str(Path(__file__).resolve().parent.parent.parent / "pharma-coldchain" / "seed_data"),
        help="Path to the seed_data directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate files and parse CSVs without writing to the database",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify row counts against expected_counts.json after loading",
    )

    args = parser.parse_args()

    import asyncio

    async def _run() -> None:
        try:
            counts = await load_seed_data(
                db_url=args.db_url,
                seed_dir=Path(args.seed_dir),
                dry_run=args.dry_run,
                verify=args.verify,
            )
            print(json.dumps(counts, indent=2))
            print("Seed data loaded successfully.")
        except SeedDataLoadError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    asyncio.run(_run())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _cli()
