#!/usr/bin/env python3
"""Pharma Cold-Chain Example — Embedded SDK Mode.

Embeds the Celeste-DAG engine inside a FastAPI application and drives the
OPA (Observe-Plan-Act) loop over HTTP/ASGI. This is the third deployment
tier alongside Local (``run_local.py``) and Remote (``run_remote.py``).

In embedded mode the engine, agent, planner and evaluator all live inside
the FastAPI process, and the run is started via the ``POST /api/runs``
endpoint. Because the OPA loop persists ``Workflow`` + ``TaskEvent`` rows to
``settings.DATABASE_URL`` as it runs, the existing monitoring endpoints
(``GET /api/workflows``, ``/api/workflows/{id}/status``, ...) surface the
run live with no extra wiring — making this tier ideal for a monitoring UI.

Two ways to use this module:

1. **In-process (default, used by tests / CI):** ``run_pharma_embedded()``
   builds the app, drives a full run via ``httpx.AsyncClient`` over an
   ``ASGITransport`` (no real network socket), polls until terminal, and
   returns the same structured result dict as ``run_local`` / ``run_remote``
   (plus ``mode="embedded"``).

2. **Real server (``--serve``):** start uvicorn on ``host:port`` so an
   external UI (e.g. CMC at :3000) can proxy to it, POST the run, and keep
   the server up until terminal/timeout. This is the monitoring-UI use case.

This module REUSES ``run_local.py``'s helpers (settings / goal loading /
result printing) by importing them rather than duplicating logic.
``run_local.py`` itself is NOT modified.

Usage::

    # In-process drive (no real server):
    python run_embedded.py

    # Real uvicorn server for a monitoring UI:
    python run_embedded.py --serve --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

# Reuse run_local.py's helpers — do NOT duplicate. run_local is a sibling
# script on sys.path when run from the example dir (and tests add the
# example dir to sys.path).
from run_local import (
    _build_llm_client,
    _build_settings,
    _load_goal,
    _print_result,
)

from celeste.api.app import create_app
from celeste.core.engine import Engine  # noqa: F401  (re-exported for clarity)
from celeste.core.evaluator import Evaluator
from celeste.core.planner import Planner
from celeste.toolkits.system_data import SystemDataToolkit

# Domain toolkits live in examples/ and are wired here (NOT in core).
try:
    from examples.pharma_coldchain.tools.pharma_toolkit import (
        PharmaColdChainToolkit,
    )

    _PHARMA_TOOLKIT_AVAILABLE = True
except Exception:  # pragma: no cover - import guard for stripped envs
    _PHARMA_TOOLKIT_AVAILABLE = False

# This module (examples/) IS allowed to import the pharma seed loader.
# It passes it into create_app via DI so src/celeste/** stays decoupled.
from examples.pharma_coldchain.seed_data.load import load_seed_data

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# The seed-data directory lives next to this script (the caller owns the
# path; core never computes it). This fixes the old off-by-one bug where
# app.py resolved parents[2] -> src/examples/... (NONEXISTENT).
_SEED_DIR = Path(__file__).resolve().parent / "seed_data"


# ---------------------------------------------------------------------------
# Toolkit wiring
# ---------------------------------------------------------------------------


def _embedded_toolkits() -> list[Any]:
    """Build the toolkit list for the embedded in-process agent.

    The embedded agent executes tools in-process, so it needs BOTH the
    system toolkit and the pharma toolkit (when available).
    """
    toolkits: list[Any] = [SystemDataToolkit()]
    if _PHARMA_TOOLKIT_AVAILABLE:
        toolkits.append(PharmaColdChainToolkit())
    return toolkits


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------


_TERMINAL_STATUSES = {"completed", "paused", "failed", "escalated", "cancelled"}


async def _poll_run(
    client: httpx.AsyncClient,
    run_id: str,
    *,
    timeout: float = 900.0,
    interval: float = 0.5,
) -> dict[str, Any]:
    """Poll GET /api/runs/{run_id} until a terminal status is reached.

    Returns the final RunStatus payload.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    last: dict[str, Any] = {}
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/runs/{run_id}")
        resp.raise_for_status()
        last = resp.json()
        if last.get("status") in _TERMINAL_STATUSES:
            return last
        await asyncio.sleep(interval)
    return last


async def _fetch_evaluation(client: httpx.AsyncClient, workflow_id: str | None) -> Any:
    """Best-effort fetch of the evaluation report for the workflow."""
    if not workflow_id:
        return None
    try:
        from celeste.evaluation import Evaluator as EvalEvaluator

        eval_reporter = EvalEvaluator(workflow_id=workflow_id)
        report = await eval_reporter.evaluate()
        logger.info("Evaluation report generated")
        return report
    except Exception as exc:
        logger.warning("Could not generate evaluation report: %s", exc)
        return None


def _to_result_dict(
    status_payload: dict[str, Any],
    evaluation_report: Any,
) -> dict[str, Any]:
    """Build the structured result dict (same shape as run_local/remote)."""
    return {
        "mode": "embedded",
        "workflow_id": status_payload.get("workflow_id"),
        "status": status_payload.get("status", "unknown"),
        "cycles": 0,  # not surfaced by /api/runs; fetch via /metrics if needed
        "token_usage": 0,
        "evaluation_report": (
            evaluation_report.model_dump()
            if hasattr(evaluation_report, "model_dump")
            else str(evaluation_report)
        )
        if evaluation_report
        else None,
    }


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


async def run_pharma_embedded(
    host: str = "127.0.0.1",
    port: int = 9000,
    *,
    database_url: str | None = None,
    api_key: str | None = None,
    goal: str | None = None,
) -> dict[str, Any]:
    """Run the pharma cold-chain scenario in embedded mode.

    Builds a FastAPI app with the Celeste engine embedded, wires the pharma
    toolkits, and drives a full OPA-loop run over an ASGI transport (no real
    network socket). Polls until the run reaches a terminal status and
    returns the same structured result shape as ``run_pharma_local`` /
    ``run_pharma_remote`` plus ``mode="embedded"``.

    Args:
        host: Bind host (used only for the ``--serve`` path; the in-process
            drive uses an ASGI transport).
        port: Bind port (used only for the ``--serve`` path).
        database_url: Optional DATABASE_URL override.
        api_key: Optional LLM_API_KEY override.
        goal: Optional goal override (default: load from goal.md).

    Returns:
        A dict with keys: mode, workflow_id, status, cycles, token_usage,
        evaluation_report.
    """
    settings = _build_settings(database_url=database_url, api_key=api_key)
    toolkits = _embedded_toolkits()

    # Build the real LLM-backed cognitive stack for the embedded run. The
    # factories are only invoked when the run is started, so we pass them
    # through unchanged here; tests override them with fakes.
    def _planner_factory(s, tks, llm):
        return Planner(llm_client=llm, toolkits=tks)

    def _evaluator_factory(s, llm):
        return Evaluator(llm_client=llm)

    llm_client = _build_llm_client(settings)

    app = create_app(
        settings=settings,
        toolkits=toolkits,
        planner_factory=_planner_factory,
        evaluator_factory=_evaluator_factory,
        llm_client=llm_client,
        seed_loader=load_seed_data,
        seed_dir=_SEED_DIR,
    )

    the_goal = goal or _load_goal()
    logger.info("Embedded run goal (%d chars): %s...", len(the_goal), the_goal[:80])

    # Manually drive the lifespan (startup/shutdown) since the ASGI transport
    # does not handle lifespan events automatically.
    lifespan_cm = app.router.lifespan_context(app)
    await lifespan_cm.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://embedded") as client:
            logger.info("POST /api/runs (goal=%d chars)", len(the_goal))
            resp = await client.post("/api/runs", json={"goal": the_goal})
            resp.raise_for_status()
            run_id = resp.json()["run_id"]
            logger.info("Started embedded run %s", run_id)

            status_payload = await _poll_run(client, run_id)
            logger.info(
                "Embedded run %s terminal: status=%s workflow_id=%s",
                run_id,
                status_payload.get("status"),
                status_payload.get("workflow_id"),
            )

            evaluation_report = await _fetch_evaluation(
                client, status_payload.get("workflow_id")
            )
    finally:
        # Cancel any lingering background run tasks before teardown.
        if hasattr(app.state, "running_run_tasks"):
            for rid, task in list(app.state.running_run_tasks.items()):
                if not task.done():
                    task.cancel()
            for rid, task in list(app.state.running_run_tasks.items()):
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            app.state.running_run_tasks.clear()
        await lifespan_cm.__aexit__(None, None, None)

    return _to_result_dict(status_payload, evaluation_report)


# ---------------------------------------------------------------------------
# --serve path: real uvicorn server for a monitoring UI
# ---------------------------------------------------------------------------


async def _serve_and_run(
    settings: Any,
    toolkits: list[Any],
    llm_client: Any,
    goal: str,
    host: str,
    port: int,
    timeout: float,
) -> dict[str, Any]:
    """Start a real uvicorn server, POST a run, poll, then shut down.

    Keeps the server up only long enough to drive the run to a terminal
    status (or ``timeout``). Intended for the monitoring-UI use case where
    CMC at :3000 proxies to this server.
    """
    # uvicorn is imported lazily inside this function so the module can be
    # imported (and the in-process path used) without uvicorn installed,
    # and so _serve_and_run is independently callable.
    import uvicorn

    def _planner_factory(s, tks, llm):
        return Planner(llm_client=llm, toolkits=tks)

    def _evaluator_factory(s, llm):
        return Evaluator(llm_client=llm)

    app = create_app(
        settings=settings,
        toolkits=toolkits,
        planner_factory=_planner_factory,
        evaluator_factory=_evaluator_factory,
        llm_client=llm_client,
        seed_loader=load_seed_data,
        seed_dir=_SEED_DIR,
    )

    config = uvicorn.Config(
        app, host=host, port=port, log_level="info", lifespan="on",
    )
    server = uvicorn.Server(config)

    server_task = asyncio.create_task(server.serve())
    # Wait for the server socket to come up.
    deadline = asyncio.get_event_loop().time() + 10.0
    while not server.started and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.1)

    status_payload: dict[str, Any] = {"status": "unknown"}
    evaluation_report = None
    try:
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            resp = await client.post("/api/runs", json={"goal": goal})
            resp.raise_for_status()
            run_id = resp.json()["run_id"]
            status_payload = await _poll_run(client, run_id, timeout=timeout)
            evaluation_report = await _fetch_evaluation(
                client, status_payload.get("workflow_id")
            )
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            server_task.cancel()

    return _to_result_dict(status_payload, evaluation_report)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for run_embedded.py."""
    parser = argparse.ArgumentParser(
        description=(
            "Pharma Cold-Chain Example — Embedded SDK Mode. Embeds the Celeste "
            "engine in a FastAPI app and drives the OPA loop over HTTP/ASGI."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind the server to (used with --serve).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="Port to listen on (used with --serve).",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help=(
            "Run a real uvicorn server on host:port (for a monitoring UI), "
            "POST the run, and keep the server up until terminal/timeout."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="Max seconds to wait for the run to reach a terminal status.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL override (default: from env / settings).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="LLM API key override (default: from LLM_API_KEY env var).",
    )
    args = parser.parse_args()

    if args.serve:
        settings = _build_settings(database_url=args.database_url, api_key=args.api_key)
        toolkits = _embedded_toolkits()
        llm_client = _build_llm_client(settings)
        goal = _load_goal()
        result = asyncio.run(
            _serve_and_run(
                settings=settings,
                toolkits=toolkits,
                llm_client=llm_client,
                goal=goal,
                host=args.host,
                port=args.port,
                timeout=args.timeout,
            )
        )
    else:
        result = asyncio.run(
            run_pharma_embedded(
                host=args.host,
                port=args.port,
                database_url=args.database_url,
                api_key=args.api_key,
            )
        )
    _print_result(result)


if __name__ == "__main__":
    main()
