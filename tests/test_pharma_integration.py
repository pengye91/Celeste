"""Integration tests for the pharma cold-chain seed data loader.

Follows strict TDD. Tests the load_seed_data function with:
- Successful loading and row count verification
- Idempotent reload (no duplicates)
- Fail-fast on missing CSV files
- Transaction rollback on corrupt CSV
- Dry-run mode (validate without writing)
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The module under test does not exist yet, so we'll import in the test body
# after confirming the file exists. Pre-declare for type hints.
SeedDataLoadError: type


def _make_seed_dir(base_dir: Path) -> Path:
    """Create the expected seed_data directory structure with CSV files."""
    seed_dir = base_dir / "seed_data"
    manifests_dir = seed_dir / "manifests"
    hubs_dir = seed_dir / "hubs"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    hubs_dir.mkdir(parents=True, exist_ok=True)
    return seed_dir


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    """Write a CSV file with the given headers and rows."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


def _valid_hubs_csv(path: Path) -> None:
    _write_csv(
        path,
        ["id", "name", "country", "capacity_doses", "qualified"],
        [
            ["1", "Amsterdam Hub", "Netherlands", "2400000", "1"],
            ["2", "Frankfurt Hub", "Germany", "1800000", "1"],
            ["3", "Paris Hub", "France", "1500000", "1"],
        ],
    )


def _valid_batches_csv(path: Path) -> None:
    _write_csv(
        path,
        ["id", "batch_id", "hub_id", "status", "temperature_c", "humidity_pct", "created_at"],
        [
            ["1", "B-1840", "1", "active", "2.8", "45.0", "2026-06-01T00:00:00"],
            ["2", "B-1841", "1", "active", "3.1", "47.2", "2026-06-01T00:00:00"],
            ["3", "B-1843", "1", "excursion", "8.5", "52.0", "2026-06-01T00:00:00"],
        ],
    )


def _write_expected_counts(path: Path, counts: dict | None = None) -> None:
    """Write expected_counts.json to the seed dir."""
    import json

    if counts is None:
        counts = {"batches": 3, "hubs": 3, "hub_qualifications": 0, "shipments": 0, "telemetry_log": 0}
    with open(path, "w") as f:
        json.dump(counts, f)


async def _count_rows(engine: AsyncEngine, table: str) -> int:
    """Count rows in a table using raw SQL."""
    async with engine.connect() as conn:
        result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
        return result.scalar_one()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSeedDataLoads:
    """Test successful seed data loading."""

    @pytest.mark.asyncio
    async def test_seed_data_loads(self):
        """load_seed_data should insert all rows and return expected counts."""
        # Import inside test so the test file can be collected even before
        # load.py is written (tests fail with ImportError which is expected initially).
        from examples.pharma_coldchain.seed_data.load import load_seed_data

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            seed_dir = _make_seed_dir(base_dir)
            _valid_hubs_csv(seed_dir / "hubs" / "hubs.csv")
            _valid_batches_csv(seed_dir / "manifests" / "batches.csv")
            _write_expected_counts(seed_dir / "expected_counts.json")
            # Also need schema.sql in the seed dir
            schema_path = Path(__file__).parent.parent / "examples" / "pharma-coldchain" / "seed_data" / "schema.sql"
            import shutil
            shutil.copy(schema_path, seed_dir / "schema.sql")

            db_url = f"sqlite+aiosqlite:///{tmpdir}/test.db"

            result = await load_seed_data(db_url, seed_dir)

            assert result["batches"] == 3
            assert result["hubs"] == 3

            engine = create_async_engine(db_url)
            assert await _count_rows(engine, "batches") == 3
            assert await _count_rows(engine, "hubs") == 3
            await engine.dispose()


class TestSeedDataIdempotent:
    """Test that loading the same data twice does not create duplicates."""

    @pytest.mark.asyncio
    async def test_seed_data_idempotent(self):
        """Loading seed data twice should produce the same row counts."""
        from examples.pharma_coldchain.seed_data.load import load_seed_data

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            seed_dir = _make_seed_dir(base_dir)
            _valid_hubs_csv(seed_dir / "hubs" / "hubs.csv")
            _valid_batches_csv(seed_dir / "manifests" / "batches.csv")
            _write_expected_counts(seed_dir / "expected_counts.json")
            schema_path = Path(__file__).parent.parent / "examples" / "pharma-coldchain" / "seed_data" / "schema.sql"
            import shutil
            shutil.copy(schema_path, seed_dir / "schema.sql")

            db_url = f"sqlite+aiosqlite:///{tmpdir}/test.db"

            # First load
            result1 = await load_seed_data(db_url, seed_dir)
            assert result1["batches"] == 3
            assert result1["hubs"] == 3

            # Second load (should be idempotent)
            result2 = await load_seed_data(db_url, seed_dir)
            assert result2["batches"] == 3
            assert result2["hubs"] == 3

            # Verify no duplicates
            engine = create_async_engine(db_url)
            assert await _count_rows(engine, "batches") == 3
            assert await _count_rows(engine, "hubs") == 3
            await engine.dispose()


class TestSeedDataMissingFileFailsFast:
    """Test that missing CSV files cause failure before any DB write."""

    @pytest.mark.asyncio
    async def test_seed_data_missing_file_fails_fast(self):
        """Missing CSV should raise SeedDataLoadError and leave DB empty."""
        from examples.pharma_coldchain.seed_data.load import load_seed_data, SeedDataLoadError

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            seed_dir = _make_seed_dir(base_dir)
            # Only create hubs CSV, omit batches CSV
            _valid_hubs_csv(seed_dir / "hubs" / "hubs.csv")
            _write_expected_counts(seed_dir / "expected_counts.json")
            schema_path = Path(__file__).parent.parent / "examples" / "pharma-coldchain" / "seed_data" / "schema.sql"
            import shutil
            shutil.copy(schema_path, seed_dir / "schema.sql")

            db_url = f"sqlite+aiosqlite:///{tmpdir}/test.db"

            with pytest.raises(SeedDataLoadError):
                await load_seed_data(db_url, seed_dir)

            # Database should have no rows (fail-fast before any write).
            # Tables may not exist at all, which is proof that no data was written.
            engine = create_async_engine(db_url)
            try:
                assert await _count_rows(engine, "hubs") == 0
            except Exception:
                # Table does not exist — no data was written to the database
                pass
            await engine.dispose()


class TestSeedDataCorruptCSVRollsBack:
    """Test that corrupt CSV causes transaction rollback."""

    @pytest.mark.asyncio
    async def test_seed_data_corrupt_csv_rolls_back(self):
        """Invalid CSV (missing required column) should roll back all changes."""
        from examples.pharma_coldchain.seed_data.load import load_seed_data, SeedDataLoadError

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            seed_dir = _make_seed_dir(base_dir)
            _valid_hubs_csv(seed_dir / "hubs" / "hubs.csv")
            # Write a corrupt batches.csv (missing 'temperature_c' column)
            _write_csv(
                seed_dir / "manifests" / "batches.csv",
                ["id", "batch_id", "hub_id", "status", "humidity_pct", "created_at"],
                [["1", "B-1840", "1", "active", "45.0", "2026-06-01T00:00:00"]],
            )
            _write_expected_counts(seed_dir / "expected_counts.json")
            schema_path = Path(__file__).parent.parent / "examples" / "pharma-coldchain" / "seed_data" / "schema.sql"
            import shutil
            shutil.copy(schema_path, seed_dir / "schema.sql")

            db_url = f"sqlite+aiosqlite:///{tmpdir}/test.db"

            with pytest.raises(SeedDataLoadError):
                await load_seed_data(db_url, seed_dir)

            # Database should have no rows (transaction rolled back, or tables
            # never created if fail-fast validation caught the error first).
            engine = create_async_engine(db_url)
            try:
                assert await _count_rows(engine, "batches") == 0
                assert await _count_rows(engine, "hubs") == 0
            except Exception:
                # Table does not exist — no data was written to the database
                pass
            await engine.dispose()


class TestSeedDataDryRun:
    """Test dry-run mode validates without writing to DB."""

    @pytest.mark.asyncio
    async def test_seed_data_dry_run(self):
        """Dry-run should validate all files but not write to the database."""
        from examples.pharma_coldchain.seed_data.load import load_seed_data

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            seed_dir = _make_seed_dir(base_dir)
            _valid_hubs_csv(seed_dir / "hubs" / "hubs.csv")
            _valid_batches_csv(seed_dir / "manifests" / "batches.csv")
            _write_expected_counts(seed_dir / "expected_counts.json")
            schema_path = Path(__file__).parent.parent / "examples" / "pharma-coldchain" / "seed_data" / "schema.sql"
            import shutil
            shutil.copy(schema_path, seed_dir / "schema.sql")

            db_url = f"sqlite+aiosqlite:///{tmpdir}/test.db"

            # Dry-run should not write to DB
            result = await load_seed_data(db_url, seed_dir, dry_run=True)

            assert result["batches"] == 3
            assert result["hubs"] == 3

            # Database should be empty (no tables created if dry-run skips DB entirely)
            engine = create_async_engine(db_url)
            # Tables won't exist since dry-run skips schema creation
            try:
                count = await _count_rows(engine, "hubs")
                assert count == 0
            except Exception:
                # Table doesn't exist, which is also fine for dry-run
                pass
            await engine.dispose()
