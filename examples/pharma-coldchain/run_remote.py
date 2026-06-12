#!/usr/bin/env python3
"""Pharma Cold-Chain Example — Remote Mode (stub).

Runs the pharma cold-chain crisis response scenario in remote mode,
connecting to a Celeste agent server via WebSocket.

Usage:
    python run_remote.py [--agent-url ws://localhost:8900/ws]

This is a stub implementation. Remote mode requires a running
celeste-agent service (see docker-compose.yml).
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


async def run_pharma_remote(
    agent_url: str = "ws://localhost:8900/ws",
) -> dict:
    """Run the pharma scenario in remote mode (stub).

    Args:
        agent_url: WebSocket URL of the running Celeste agent server.

    Returns:
        A dict with status and result information.
    """
    logger.info("Remote mode stub: connecting to agent at %s", agent_url)
    logger.info("Goal: %s", _load_goal())

    # Remote mode requires a running agent server.
    # When implemented, this will establish a persistent WebSocket
    # connection and drive the OPA loop remotely.
    result = {
        "mode": "remote",
        "status": "not_implemented",
        "agent_url": agent_url,
        "message": (
            "Remote mode is not yet fully implemented. "
            "Use run_local.py for local mode execution, or start the "
            "celeste-agent service (docker compose up celeste-agent) and "
            "connect via WebSocket."
        ),
    }
    logger.info("Remote mode result: %s", result)
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pharma Cold-Chain Example — Remote Mode",
    )
    parser.add_argument(
        "--agent-url",
        default="ws://localhost:8900/ws",
        help="WebSocket URL of the Celeste agent server",
    )
    args = parser.parse_args()
    asyncio.run(run_pharma_remote(agent_url=args.agent_url))


if __name__ == "__main__":
    main()
