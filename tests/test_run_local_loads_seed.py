"""Tests that run_pharma_local() loads seed data before starting the engine.

The pharma cold-chain scenario queries telemetry_log / hubs / batches etc.
via the cold_chain tool. Those tables only exist if the seed loader runs
before engine.start(). Without wiring, the OPA loop re-plans the same node
forever because each tool call raises ``no such table: telemetry_log``.

This file covers two complementary checks:

1. ``TestRunLocalCallsSeedLoader``: patches the in-process loader so
   ``run_pharma_local`` can be exercised end-to-end without touching the
   real database. Asserts the loader is called with the engine's
   DATABASE_URL before ``engine.start()``.

2. ``TestSeedLoaderIntegration``: actually invokes the real loader against
   a temp SQLite database (the one ``run_pharma_local`` would use) and
   asserts the pharma tables exist with rows.
"""

from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _add_example_to_path() -> None:
    """Ensure the example directory is on sys.path for run_local imports."""
    example_dir = str(
        Path(__file__).resolve().parent.parent / "examples" / "pharma-coldchain"
    )
    if example_dir not in sys.path:
        sys.path.insert(0, example_dir)


# ---------------------------------------------------------------------------
# 1. run_pharma_local must invoke the seed loader before engine.start()
# ---------------------------------------------------------------------------


class TestRunLocalCallsSeedLoader:
    """run_pharma_local() should load seed data into the engine's DB
    before starting the OPA loop."""

    @pytest.mark.asyncio
    async def test_run_pharma_local_invokes_seed_loader(self):
        _add_example_to_path()
        import run_local

        called: dict[str, object] = {}

        async def fake_load_seed_data(db_url, seed_dir, **_kwargs):
            called["db_url"] = db_url
            called["seed_dir"] = seed_dir
            return {"batches": 12, "hubs": 6}

        with patch.object(run_local, "Engine", autospec=True) as mock_engine_cls, \
             patch.object(run_local, "_load_goal", return_value="Test goal"), \
             patch.object(run_local, "_build_llm_client", return_value=MagicMock()), \
             patch.object(
                 run_local,
                 "load_seed_data",
                 side_effect=fake_load_seed_data,
                 create=True,
             ):
            mock_engine = MagicMock()
            mock_engine.start = AsyncMock()
            mock_engine.stop = AsyncMock()
            mock_engine.run = AsyncMock()
            mock_engine_cls.return_value = mock_engine

            result = await run_local.run_pharma_local(
                database_url="sqlite+aiosqlite:///celeste.db",
                api_key="sk-test",
            )

            assert result is not None
            # Loader must have been invoked at least once.
            assert "db_url" in called, (
                "run_pharma_local() did not call load_seed_data(); "
                "telemetry_log and related tables will be missing when "
                "cold_chain.check_temperature_excursion() runs."
            )
            # Loader must have been called with the engine's database URL.
            assert called["db_url"] == "sqlite+aiosqlite:///celeste.db"

    @pytest.mark.asyncio
    async def test_seed_loader_runs_before_engine_start(self):
        """The loader must finish before engine.start() is invoked.

        Otherwise cold_chain.check_temperature_excursion() (called during
        the OPA loop) raises ``no such table: telemetry_log`` and the
        workflow spins forever re-planning the same node.
        """
        _add_example_to_path()
        import run_local

        event_order: list[str] = []

        async def fake_load_seed_data(db_url, seed_dir, **_kwargs):
            event_order.append("load_seed_data")
            return {"batches": 12, "hubs": 6}

        def fake_engine_cls(*args, **kwargs):
            event_order.append("Engine.__init__")
            mock_engine = MagicMock()

            async def _start():
                event_order.append("engine.start")

            async def _stop():
                event_order.append("engine.stop")

            async def _run(**_kw):
                event_order.append("engine.run")
                mock_result = MagicMock()
                mock_result.status = "completed"
                mock_result.workflow_id = "wf-test"
                mock_result.cycle_count = 1
                mock_result.llm_tokens_accumulated = 0
                return mock_result

            mock_engine.start = _start
            mock_engine.stop = _stop
            mock_engine.run = _run
            return mock_engine

        with patch.object(run_local, "Engine", side_effect=fake_engine_cls), \
             patch.object(run_local, "_load_goal", return_value="Test goal"), \
             patch.object(run_local, "_build_llm_client", return_value=MagicMock()), \
             patch.object(
                 run_local,
                 "load_seed_data",
                 side_effect=fake_load_seed_data,
                 create=True,
             ):
            await run_local.run_pharma_local(
                database_url="sqlite+aiosqlite:///celeste.db",
                api_key="sk-test",
            )

        # Find indices of the relevant events.
        start_idx = event_order.index("engine.start")
        load_idx = event_order.index("load_seed_data")

        assert load_idx < start_idx, (
            f"load_seed_data() ran after engine.start(): {event_order}"
        )

    @pytest.mark.asyncio
    async def test_seed_loader_failure_does_not_block_engine(self):
        """A seed-load failure should log a warning and let the engine run.

        The seed loader is best-effort: the example must not collapse if
        seed CSVs are missing or malformed. Real engine bugs should not be
        masked by seed-load errors either.
        """
        _add_example_to_path()
        import run_local

        async def broken_load_seed_data(db_url, seed_dir, **_kwargs):
            raise RuntimeError("simulated seed load failure")

        with patch.object(run_local, "Engine", autospec=True) as mock_engine_cls, \
             patch.object(run_local, "_load_goal", return_value="Test goal"), \
             patch.object(run_local, "_build_llm_client", return_value=MagicMock()), \
             patch.object(
                 run_local,
                 "load_seed_data",
                 side_effect=broken_load_seed_data,
                 create=True,
             ):
            mock_engine = MagicMock()
            mock_engine.start = AsyncMock()
            mock_engine.stop = AsyncMock()
            mock_engine.run = AsyncMock()
            mock_engine_cls.return_value = mock_engine

            # Should NOT raise: seed-load failure is logged and swallowed.
            result = await run_local.run_pharma_local(
                database_url="sqlite+aiosqlite:///celeste.db",
                api_key="sk-test",
            )

            assert result is not None
            mock_engine.start.assert_called_once()
            mock_engine.run.assert_called_once()
            mock_engine.stop.assert_called_once()


# ---------------------------------------------------------------------------
# 2. Integration: real loader populates telemetry_log + pharma tables
# ---------------------------------------------------------------------------


class TestSeedLoaderIntegration:
    """End-to-end check that the real loader creates the tables
    cold_chain.check_temperature_excursion() relies on."""

    @pytest.mark.asyncio
    async def test_real_loader_creates_telemetry_log(self):
        """The real loader, given the example seed_dir, must create
        telemetry_log (and other pharma tables) and populate them."""
        from examples.pharma_coldchain.seed_data.load import load_seed_data

        repo_root = Path(__file__).resolve().parent.parent
        seed_dir = repo_root / "examples" / "pharma-coldchain" / "seed_data"
        assert seed_dir.is_dir(), f"seed_data dir missing: {seed_dir}"
        assert (seed_dir / "schema.sql").is_file(), "schema.sql missing"
        assert (seed_dir / "hubs" / "hubs.csv").is_file(), "hubs.csv missing"
        assert (seed_dir / "manifests" / "batches.csv").is_file(), "batches.csv missing"

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "pharma.db"
            db_url = f"sqlite+aiosqlite:///{db_path}"

            counts = await load_seed_data(db_url, seed_dir)

            # All pharma tables must exist with the expected row counts.
            assert "hubs" in counts and "batches" in counts
            assert counts["hubs"] >= 1
            assert counts["batches"] >= 1

            engine = create_async_engine(db_url)
            try:
                async with engine.connect() as conn:
                    # Schema check: the table cold_chain queries must exist.
                    res = await conn.execute(
                        text(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name='telemetry_log'"
                        )
                    )
                    assert res.scalar_one() == "telemetry_log", (
                        "telemetry_log table is missing — cold_chain will fail"
                    )

                    # Row counts on the other tables cold_chain / planner reach for.
                    res = await conn.execute(text("SELECT COUNT(*) FROM hubs"))
                    assert res.scalar_one() >= 1
                    res = await conn.execute(text("SELECT COUNT(*) FROM batches"))
                    assert res.scalar_one() >= 1
            finally:
                await engine.dispose()