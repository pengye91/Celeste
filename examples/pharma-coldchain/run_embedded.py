#!/usr/bin/env python3
"""Pharma Cold-Chain Example — Embedded SDK Mode (stub).

Embeds Celeste-DAG inside a user's FastAPI application, demonstrating
library usage, custom endpoints, and integration patterns.

Usage:
    python run_embedded.py [--host 127.0.0.1] [--port 9000]

This is a stub implementation. Embedded mode requires a FastAPI app
with the Celeste engine wired into custom endpoints.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_GOAL_FILE = Path(__file__).resolve().parent / "goal.md"


def _load_goal() -> str:
    """Load the workflow goal from goal.md."""
    if _GOAL_FILE.exists():
        return _GOAL_FILE.read_text().strip()
    return "Pharma cold-chain crisis response — see goal.md"


async def run_pharma_embedded(
    host: str = "127.0.0.1",
    port: int = 9000,
) -> dict:
    """Run the pharma scenario in embedded mode (stub).

    Args:
        host: Host to bind the embedded FastAPI server to.
        port: Port to listen on.

    Returns:
        A dict with status and result information.
    """
    logger.info("Embedded mode stub: host=%s port=%d", host, port)
    logger.info("Goal: %s", _load_goal())

    # Embedded mode requires building a FastAPI app with the engine.
    # When implemented, this will create a FastAPI instance, wire in
    # custom endpoints, and serve the pharma scenario as an API.
    result = {
        "mode": "embedded",
        "status": "not_implemented",
        "host": host,
        "port": port,
        "message": (
            "Embedded mode is not yet fully implemented. "
            "Use run_local.py for local mode execution. When implemented, "
            "this will create a FastAPI app with endpoints like "
            "POST /workflows, GET /workflows/{id}, and POST /workflows/{id}/resume."
        ),
    }
    logger.info("Embedded mode result: %s", result)
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pharma Cold-Chain Example — Embedded SDK Mode",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind the server to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="Port to listen on",
    )
    args = parser.parse_args()
    asyncio.run(run_pharma_embedded(host=args.host, port=args.port))


if __name__ == "__main__":
    main()
