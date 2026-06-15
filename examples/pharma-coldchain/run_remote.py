#!/usr/bin/env python3
"""Pharma Cold-Chain Example — Remote Mode.

Runs the pharma cold-chain crisis response scenario against a REMOTELY
running Celeste agent server. The planner and evaluator still run locally
(they need the LLM client), but every tool call (``agent.call_tool`` /
``agent.list_tools``) is forwarded over a WebSocket to the server process,
which owns the cold-chain drivers and the
:class:`SystemDataToolkit` / :class:`PharmaColdChainToolkit`.

The server is ASSUMED ALREADY RUNNING. An operator must start it separately,
either::

    # In-tree (recommended for development):
    python examples/pharma-coldchain/serve_agent.py --port 8900

    # Or via docker compose:
    docker compose -f examples/pharma-coldchain/docker-compose.yml up -d celeste-agent

Then this client connects to ``--agent-url`` (default
``ws://localhost:8900/ws``) and drives the OPA loop.

This module REUSES ``run_local.py``'s helpers (settings / LLM client / goal
loading / result printing) by importing them rather than duplicating logic.
``run_local.py`` itself is NOT modified.

Usage::

    # Server already running on the default URL:
    python run_remote.py

    # Custom server URL + auth + Postgres:
    DATABASE_URL=postgresql+asyncpg://localhost:5432/pharma_coldchain \\
    python run_remote.py \\
        --agent-url ws://localhost:8900/ws \\
        --auth-token secret
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

# Reuse run_local.py's helpers — do NOT duplicate. We import them by module
# name (run_local is a sibling script on sys.path when run from the example
# dir, and tests add the example dir to sys.path).
from run_local import (
    _build_llm_client,
    _build_settings,
    _load_goal,
    _print_result,
)

from celeste.core.agent.agent import EnvironmentAgent
from celeste.core.engine import Engine
from celeste.core.evaluator import Evaluator
from celeste.core.planner import Planner
from celeste.toolkits.system_data import SystemDataToolkit

# NOTE: the client builds a planner that needs to advertise the pharma tools,
# but the toolkit tools are EXECUTED on the server. The client only needs the
# toolkit schemas for planning; the pharma toolkit imports are best-effort so
# a missing examples install degrades gracefully.
try:
    from examples.pharma_coldchain.tools.pharma_toolkit import (
        PharmaColdChainToolkit,
    )

    _PHARMA_TOOLKIT_AVAILABLE = True
except Exception:  # pragma: no cover - import guard for stripped envs
    _PHARMA_TOOLKIT_AVAILABLE = False

from examples.pharma_coldchain.seed_data.load import load_seed_data

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _client_toolkits() -> list[Any]:
    """Build the toolkit list used by the LOCAL planner.

    The planner needs tool SCHEMAS to advertise available tools to the LLM.
    Execution happens server-side; these client-side toolkit instances are
    only consulted for ``to_mcp_schemas()`` by the Planner, never executed.
    """
    toolkits: list[Any] = [SystemDataToolkit()]
    if _PHARMA_TOOLKIT_AVAILABLE:
        toolkits.append(PharmaColdChainToolkit())
    return toolkits


async def _load_seed_best_effort(database_url: str | None) -> None:
    """Load pharma seed data into the shared DB best-effort.

    The server and client share the same DATABASE_URL. The server loads seed
    data too (see serve_agent.py), but loading here is idempotent and makes
    the client self-sufficient when pointed at a fresh DB.
    """
    if not database_url:
        logger.info(
            "No DATABASE_URL; skipping client-side seed data load. "
            "Ensure the server has loaded pharma seed data."
        )
        return
    try:
        seed_dir = Path(__file__).resolve().parent / "seed_data"
        logger.info("Loading pharma seed data from %s into %s", seed_dir, database_url)
        counts = await load_seed_data(database_url, seed_dir)
        logger.info("Seed data loaded: %s", counts)
    except Exception as exc:
        logger.warning(
            "Pharma seed data load failed on client; cold_chain SQL queries "
            "may fail. Cause: %s",
            exc,
        )


async def run_pharma_remote(
    agent_url: str = "ws://localhost:8900/ws",
    auth_token: str | None = None,
    database_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Run the pharma cold-chain scenario in remote mode.

    Connects to a running agent server at ``agent_url``, drives the OPA loop
    with a locally-built planner/evaluator (real LLM), and forwards every
    tool call to the server over WebSocket.

    The server must already be running (start ``serve_agent.py`` or the
    ``celeste-agent`` compose service separately).

    Args:
        agent_url: WebSocket URL of the running agent server.
        auth_token: Optional bearer token the server requires.
        database_url: Optional DATABASE_URL override (same DB the server
            queries). Used for best-effort client-side seed loading.
        api_key: Optional LLM_API_KEY override for the local planner.

    Returns:
        A dict with keys: mode, workflow_id, status, cycles, token_usage,
        evaluation_report (same shape as ``run_pharma_local`` plus
        ``mode="remote"``).
    """
    settings = _build_settings(database_url=database_url, api_key=api_key)

    # 1. Build LLM client + planner/evaluator (local; they need the LLM).
    llm_client = _build_llm_client(settings)
    toolkits = _client_toolkits()
    planner = Planner(llm_client=llm_client, toolkits=toolkits)
    evaluator = Evaluator(llm_client=llm_client)

    # 2. Load goal.
    goal = _load_goal()
    logger.info("Goal loaded (%d chars): %s...", len(goal), goal[:80])

    # 3. Best-effort client-side seed load into the shared DB.
    db_url = (
        database_url
        if database_url
        else settings.DATABASE_URL.get_secret_value()
    )
    await _load_seed_best_effort(db_url)

    # 4. Build a REMOTE agent (no drivers/toolkits; everything forwards).
    agent = EnvironmentAgent.remote(url=agent_url, auth_token=auth_token)
    await agent.start()
    logger.info("Remote agent connected to %s", agent_url)

    # 5. Run the engine (transport-agnostic; only calls call_tool/list_tools).
    engine = Engine(settings=settings)
    await engine.start()
    logger.info("Engine started")

    workflow_result = None
    evaluation_report = None

    try:
        logger.info("Starting OPA loop (remote) for pharma cold-chain scenario...")
        workflow_result = await engine.run(
            goal=goal,
            agent=agent,
            planner=planner,
            evaluator=evaluator,
            max_llm_cost_usd=settings.MAX_LLM_COST_USD,
        )
        logger.info("Workflow completed with status: %s", workflow_result.status)

        if workflow_result.workflow_id:
            try:
                from celeste.evaluation import Evaluator as EvalEvaluator

                eval_reporter = EvalEvaluator(
                    workflow_id=str(workflow_result.workflow_id)
                )
                evaluation_report = await eval_reporter.evaluate()
                logger.info("Evaluation report generated")
            except Exception as exc:
                logger.warning("Could not generate evaluation report: %s", exc)
    finally:
        await engine.stop()
        logger.info("Engine stopped")
        await agent.stop()
        logger.info("Remote agent disconnected")

    # 6. Return structured result (same shape as run_local + mode).
    result: dict[str, Any] = {
        "mode": "remote",
        "agent_url": agent_url,
        "workflow_id": str(workflow_result.workflow_id)
        if workflow_result and workflow_result.workflow_id
        else None,
        "status": workflow_result.status if workflow_result else "unknown",
        "cycles": workflow_result.cycle_count if workflow_result else 0,
        "token_usage": workflow_result.llm_tokens_accumulated
        if workflow_result
        else 0,
        "evaluation_report": (
            evaluation_report.model_dump()
            if hasattr(evaluation_report, "model_dump")
            else str(evaluation_report)
        )
        if evaluation_report
        else None,
    }

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for run_remote.py."""
    parser = argparse.ArgumentParser(
        description=(
            "Pharma Cold-Chain Example — Remote Mode. Connects to a running "
            "Celeste agent server and drives the OPA loop over WebSocket."
        ),
    )
    parser.add_argument(
        "--agent-url",
        default="ws://localhost:8900/ws",
        help="WebSocket URL of the Celeste agent server (default: ws://localhost:8900/ws).",
    )
    parser.add_argument(
        "--auth-token",
        default=None,
        help="Optional bearer token the server requires.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL override (same DB the server queries).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="LLM API key override (default: from LLM_API_KEY env var).",
    )
    args = parser.parse_args()

    result = asyncio.run(
        run_pharma_remote(
            agent_url=args.agent_url,
            auth_token=args.auth_token,
            database_url=args.database_url,
            api_key=args.api_key,
        )
    )
    _print_result(result)


if __name__ == "__main__":
    main()
