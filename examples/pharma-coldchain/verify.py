#!/usr/bin/env python3
"""Pharma Cold-Chain Example — Verification Wrapper.

Thin wrapper around celeste.evaluation.Evaluator that:
1. Runs the scenario in the requested mode (local/remote/embedded).
2. Collects evaluation metrics from the durable event ledger.
3. Prints a human-readable report.

Usage:
    python verify.py --mode=local --workflow-id=<uuid>
    python verify.py --mode=remote
    python verify.py --mode=embedded --workflow-id=<uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from celeste.evaluation import (
    Evaluator,
    format_report,
    assert_replan_occurred,
    assert_saga_compensation,
    assert_escalation,
    assert_checkpoint_state_match,
    assert_multi_workspace,
    assert_security_pipeline,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def verify_workflow(
    workflow_id: str,
    mode: str = "local",
) -> dict[str, Any]:
    """Run verification for a completed pharma cold-chain workflow.

    Loads the durable event ledger for the given workflow, exercises all
    feature detectors, runs scenario-specific assertions, and returns a
    structured report.

    Args:
        workflow_id: UUID of the completed workflow to evaluate.
        mode: Execution mode used (local, remote, or embedded).

    Returns:
        A dict containing the full evaluation report.
    """
    evaluator = Evaluator(workflow_id=workflow_id)

    # Register pharma-specific assertions
    evaluator.assertions.add(
        assert_replan_occurred(min_count=1)
    )
    evaluator.assertions.add(
        assert_saga_compensation(
            trigger_pattern="B-1847",
            expected_chain=["triggered", "completed"],
        )
    )
    evaluator.assertions.add(
        assert_escalation(
            tier=4,
            resolved=True,
            max_pause_minutes=60,
        )
    )
    evaluator.assertions.add(
        assert_checkpoint_state_match()
    )
    evaluator.assertions.add(
        assert_multi_workspace(min_concurrent=4)
    )
    evaluator.assertions.add(
        assert_security_pipeline(min_blocked=1)
    )

    report = await evaluator.evaluate()

    # Build return dict
    result = {
        "workflow_id": workflow_id,
        "mode": mode,
        "overall": report.overall,
        "features": {
            name: {
                "status": fr.status,
                "evidence": fr.evidence,
            }
            for name, fr in report.features.items()
        },
        "warnings": report.warnings,
        "token_cost": report.token_cost.model_dump()
        if hasattr(report.token_cost, "model_dump")
        else str(report.token_cost),
    }

    return result


def print_report(result: dict[str, Any]) -> None:
    """Print a human-readable evaluation report to stdout."""
    print()
    print("=" * 65)
    print("  Celeste Evaluation Report  |  Pharma Cold-Chain Example")
    print("=" * 65)
    print()
    print(f"  Workflow ID:  {result['workflow_id']}")
    print(f"  Mode:         {result['mode']}")
    print(f"  Overall:      {result['overall']}")
    print()
    print("  Features:")
    for name, info in result.get("features", {}).items():
        status_icon = {
            "PASS": "✓",
            "FAIL": "✗",
            "NOT_EXERCISED": "-",
        }.get(info["status"], "?")
        print(f"    {status_icon} {name:25s}  {info['status']}")
    print()
    if result.get("warnings"):
        print("  Warnings:")
        for w in result["warnings"]:
            print(f"    - {w}")
        print()
    print("  Token Cost:")
    tc = result.get("token_cost", {})
    if isinstance(tc, dict):
        for key, val in tc.items():
            print(f"    {key}: {val}")
    else:
        print(f"    {tc}")
    print()
    print("=" * 65)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pharma Cold-Chain Example — Verification",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "remote", "embedded"],
        default="local",
        help="Execution mode to verify (default: local)",
    )
    parser.add_argument(
        "--workflow-id",
        default=None,
        help="UUID of the workflow to evaluate (required unless running the scenario)",
    )
    parser.add_argument(
        "--run-first",
        action="store_true",
        default=False,
        help="Run the scenario in the chosen mode before verifying",
    )
    args = parser.parse_args()

    workflow_id = args.workflow_id

    if args.run_first or workflow_id is None:
        logger.info(
            "No --workflow-id provided; run the scenario first with "
            "run_local.py and pass the resulting workflow ID."
        )
        logger.info(
            "Example: python run_local.py  (prints workflow_id on completion)"
        )
        sys.exit(1)

    result = asyncio.run(
        verify_workflow(workflow_id=workflow_id, mode=args.mode)
    )
    print_report(result)


if __name__ == "__main__":
    main()
