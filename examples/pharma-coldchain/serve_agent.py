#!/usr/bin/env python3
"""Pharma Cold-Chain Example — Remote Agent Server.

A pharma-specific wrapper around the generic
``celeste.core.agent.serve.serve`` runner. This script starts a standalone
WebSocket agent server that owns the cold-chain drivers and registers both
the :class:`SystemDataToolkit` and the pharma-specific
:class:`PharmaColdChainToolkit`, so the remote engine's ``call_tool`` /
``list_tools`` requests execute the pharma SQL/tool logic on the server.

It also loads the pharma seed data into the configured ``DATABASE_URL``
before serving, so the cold_chain tools' SQL queries (telemetry_log, hubs,
batches, ...) succeed. Seed loading is best-effort: a failure logs a warning
but does not abort serving, so a seed-load bug doesn't mask a real bug.

Usage::

    # Default (SQLite, no auth):
    python serve_agent.py

    # Real Postgres + bearer auth:
    DATABASE_URL=postgresql+asyncpg://localhost:5432/pharma_coldchain \\
    python serve_agent.py --host 0.0.0.0 --port 8900 --auth-token secret

This is the server half of the remote tier. Run it in one process, then
drive it from another process with ``run_remote.py`` (the client).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from celeste.core.agent.serve import serve
from celeste.toolkits.system_data import SystemDataToolkit

# NOTE: this file lives in examples/ and MAY import PharmaColdChainToolkit.
# The generic core serve.py must not.
from examples.pharma_coldchain.tools.pharma_toolkit import PharmaColdChainToolkit
from examples.pharma_coldchain.seed_data.load import load_seed_data

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_SEED_DIR = Path(__file__).resolve().parent / "seed_data"


async def _load_seed_best_effort(database_url: str | None) -> None:
    """Load pharma seed data best-effort before serving.

    cold_chain.check_temperature_excursion() and other pharma tools query
    telemetry_log / hubs / batches directly. Without seed data the queries
    fail with ``no such table``. A failure here only logs a warning so a
    seed-load bug doesn't mask a real server bug.
    """
    if not database_url:
        logger.info(
            "No DATABASE_URL provided; skipping pharma seed data load. "
            "Cold-chain SQL queries may fail until seed data is loaded."
        )
        return
    try:
        logger.info(
            "Loading pharma seed data from %s into %s", _SEED_DIR, database_url
        )
        counts = await load_seed_data(database_url, _SEED_DIR)
        logger.info("Seed data loaded: %s", counts)
    except Exception as exc:
        logger.warning(
            "Pharma seed data load failed; cold_chain SQL queries may fail. "
            "Server will still start. Cause: %s",
            exc,
        )


def main() -> None:
    """CLI entry point: parse args, load seed, and serve forever."""
    parser = argparse.ArgumentParser(
        description=(
            "Pharma Cold-Chain remote agent server. Owns the cold-chain "
            "drivers and toolkits and serves them over WebSocket."
        ),
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8900,
        help="Bind port (default: 8900).",
    )
    parser.add_argument(
        "--workdir",
        default=".",
        help="Working directory for drivers (default: '.').",
    )
    parser.add_argument(
        "--auth-token",
        default=None,
        help="Optional bearer token clients must present.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Database URL for seed data loading. Defaults to the "
            "DATABASE_URL env var if set; otherwise seed loading is skipped."
        ),
    )
    args = parser.parse_args()

    # Resolve the database URL: explicit flag wins, else fall back to env.
    import os

    database_url = args.database_url or os.environ.get("DATABASE_URL")

    toolkits = [SystemDataToolkit(), PharmaColdChainToolkit()]

    async def _run() -> None:
        await _load_seed_best_effort(database_url)
        await serve(
            host=args.host,
            port=args.port,
            workdir=args.workdir,
            toolkits=toolkits,
            auth_token=args.auth_token,
        )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
