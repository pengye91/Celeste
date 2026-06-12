#!/usr/bin/env python3
"""Pharma Cold-Chain Example — Local Mode.

Runs the pharma cold-chain crisis response scenario entirely in-process
with real LLM calls and optional real Docker services. No network
overhead — all components execute in the same Python process.

Usage:
    # Run with default settings (SQLite, Anthropic Claude):
    python run_local.py

    # Run with a real PostgreSQL and custom API key:
    DATABASE_URL=postgresql+asyncpg://localhost:5432/pharma_coldchain \\
    ANTHROPIC_API_KEY=sk-ant-... \\
    python run_local.py

    # Run with OpenAI:
    LLM_PROVIDER=openai LLM_MODEL=gpt-4o \\
    OPENAI_API_KEY=sk-... \\
    python run_local.py
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from celeste.config.settings import EngineSettings, reset_settings
from celeste.core.agent.agent import EnvironmentAgent
from celeste.core.engine import Engine
from celeste.core.evaluator import Evaluator
from celeste.core.planner import Planner
from celeste.toolkits.system_data import SystemDataToolkit

# Custom pharma cold-chain toolkit — wraps GDP compliance, telemetry parsing,
# temperature excursion detection, and customs import rules. Registered with
# the agent below so the planner can discover and invoke all four tools.
from examples.pharma_coldchain.tools.pharma_toolkit import PharmaColdChainToolkit

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_GOAL_FILE = Path(__file__).resolve().parent / "goal.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_goal() -> str:
    """Load the workflow goal from goal.md."""
    if _GOAL_FILE.exists():
        return _GOAL_FILE.read_text().strip()
    logger.warning("goal.md not found at %s; using default goal", _GOAL_FILE)
    return "Pharma cold-chain crisis response"


def _build_settings(
    database_url: str | None = None,
    api_key: str | None = None,
) -> EngineSettings:
    """Build engine settings, respecting explicit overrides.

    Args:
        database_url: Override the default DATABASE_URL.
        api_key: Override the default LLM_API_KEY.

    Returns:
        An EngineSettings instance configured for this example.
    """
    # Reset any cached singleton so our env vars take effect
    reset_settings()

    # Build a settings instance from the current environment
    settings = EngineSettings()

    if database_url:
        from pydantic import SecretStr

        settings.DATABASE_URL = SecretStr(database_url)

    if api_key:
        from pydantic import SecretStr

        settings.LLM_API_KEY = SecretStr(api_key)

    return settings


def _build_llm_client(settings: EngineSettings) -> Any:
    """Build the appropriate LLM client based on LLM_PROVIDER setting.

    Returns an instance of AnthropicClient, OpenAIClient, GeminiClient,
    or OllamaClient.
    """
    provider = settings.LLM_PROVIDER

    if provider == "anthropic":
        from celeste.core.llm.anthropic import AnthropicClient

        return AnthropicClient(settings)
    elif provider == "openai":
        from celeste.core.llm.openai import OpenAIClient

        return OpenAIClient(settings)
    elif provider == "gemini":
        from celeste.core.llm.gemini import GeminiClient

        return GeminiClient(settings)
    elif provider == "ollama":
        from celeste.core.llm.ollama import OllamaClient

        return OllamaClient(settings)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


async def run_pharma_local(
    database_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Run the pharma cold-chain scenario in local mode.

    Sets up all components (engine, agent, planner, evaluator) in-process,
    loads the goal from goal.md, executes the OPA loop, and returns a
    structured result including the workflow result and evaluation report.

    Args:
        database_url: Optional override for DATABASE_URL (default: SQLite).
        api_key: Optional override for LLM_API_KEY (default: from env).

    Returns:
        A dict with keys: workflow_id, status, cycles, token_usage,
        evaluation_report.
    """
    settings = _build_settings(database_url=database_url, api_key=api_key)

    # ------------------------------------------------------------------
    # 1. Build LLM client
    # ------------------------------------------------------------------
    llm_client = _build_llm_client(settings)

    # ------------------------------------------------------------------
    # 2. Build toolkits
    # ------------------------------------------------------------------
    # SystemDataToolkit: SQL queries, file operations, and process management.
    # PharmaColdChainToolkit: GDP compliance, telemetry, customs, excursion.
    toolkit = SystemDataToolkit()
    pharma_toolkit = PharmaColdChainToolkit()

    # ------------------------------------------------------------------
    # 3. Build agent (in-process, no network)
    # ------------------------------------------------------------------
    agent = EnvironmentAgent.in_process(
        workdir=".",
        toolkits=[toolkit, pharma_toolkit],
    )

    # ------------------------------------------------------------------
    # 4. Build planner and evaluator
    # ------------------------------------------------------------------
    planner = Planner(llm_client=llm_client, toolkits=[toolkit, pharma_toolkit])
    evaluator = Evaluator(llm_client=llm_client)

    # ------------------------------------------------------------------
    # 5. Load goal
    # ------------------------------------------------------------------
    goal = _load_goal()
    logger.info("Goal loaded (%d chars): %s...", len(goal), goal[:80])

    # ------------------------------------------------------------------
    # 6. Run engine
    # ------------------------------------------------------------------
    engine = Engine(settings=settings)
    await engine.start()
    logger.info("Engine started")

    workflow_result = None
    evaluation_report = None

    try:
        logger.info("Starting OPA loop for pharma cold-chain scenario...")
        workflow_result = await engine.run(
            goal=goal,
            agent=agent,
            planner=planner,
            evaluator=evaluator,
        )
        logger.info("Workflow completed with status: %s", workflow_result.status)

        # ------------------------------------------------------------------
        # 7. Collect evaluation report
        # ------------------------------------------------------------------
        if workflow_result.workflow_id:
            try:
                from celeste.evaluation import Evaluator as EvalEvaluator

                eval_reporter = EvalEvaluator(
                    workflow_id=str(workflow_result.workflow_id)
                )
                evaluation_report = await eval_reporter.evaluate()
                logger.info("Evaluation report generated")
            except Exception as exc:
                logger.warning(
                    "Could not generate evaluation report: %s", exc
                )
    finally:
        await engine.stop()
        logger.info("Engine stopped")

    # ------------------------------------------------------------------
    # 8. Return structured result
    # ------------------------------------------------------------------
    result: dict[str, Any] = {
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


def _print_result(result: dict[str, Any]) -> None:
    """Print a human-readable summary to stdout."""
    print()
    print("=" * 65)
    print("  Pharma Cold-Chain Scenario — Local Mode Result")
    print("=" * 65)
    print()
    print(f"  Workflow ID:   {result['workflow_id']}")
    print(f"  Status:        {result['status']}")
    print(f"  OPA Cycles:    {result['cycles']}")
    print(f"  LLM Tokens:    {result['token_usage']}")
    print()

    eval_report = result.get("evaluation_report")
    if eval_report and isinstance(eval_report, dict):
        overall = eval_report.get("overall", "N/A")
        print(f"  Evaluation:    {overall}")
        features = eval_report.get("features", {})
        for name, info in features.items():
            icon = {"PASS": "✓", "FAIL": "✗", "NOT_EXERCISED": "-"}.get(
                info.get("status", ""), "?"
            )
            print(f"    {icon} {name}: {info.get('status', '?')}")
    print()
    print("=" * 65)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for run_local.py."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Pharma Cold-Chain Example — Local Mode",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL (default: sqlite+aiosqlite:///celeste.db)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="LLM API key (default: from ANTHROPIC_API_KEY env var)",
    )
    args = parser.parse_args()

    result = asyncio.run(
        run_pharma_local(
            database_url=args.database_url,
            api_key=args.api_key,
        )
    )
    _print_result(result)


if __name__ == "__main__":
    main()
