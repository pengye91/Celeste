"""Assertion registry and scenario-specific assertion helpers.

Assertions are registered against a workflow and evaluated after detection
to produce PASS/FAIL verdicts.
"""

from __future__ import annotations

from typing import Any, Callable

from celeste.evaluation.schemas import FeatureResult


class AssertionResult:
    """Result of running a single assertion."""

    def __init__(
        self,
        name: str,
        passed: bool,
        message: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.passed = passed
        self.message = message
        self.evidence = evidence or {}

    def to_feature_result(self) -> FeatureResult:
        return FeatureResult(
            name=self.name,
            status="PASS" if self.passed else "FAIL",
            evidence=self.evidence,
            assertion=self.message,
        )


AssertionFn = Callable[[str], AssertionResult]


class AssertionRegistry:
    """Registry of assertions to evaluate against a workflow."""

    def __init__(self) -> None:
        self._assertions: list[AssertionFn] = []

    def add(self, assertion: AssertionFn) -> None:
        """Register an assertion function."""
        self._assertions.append(assertion)

    def clear(self) -> None:
        """Remove all registered assertions."""
        self._assertions.clear()

    async def evaluate(self, workflow_id: str) -> list[AssertionResult]:
        """Run all registered assertions against the workflow."""
        results: list[AssertionResult] = []
        for assertion in self._assertions:
            try:
                result = await assertion(workflow_id)
                results.append(result)
            except Exception as exc:
                results.append(
                    AssertionResult(
                        name=getattr(assertion, "__name__", "unknown"),
                        passed=False,
                        message=f"Assertion raised exception: {exc}",
                    )
                )
        return results


# ---------------------------------------------------------------------------
# Scenario-specific assertion helpers
# ---------------------------------------------------------------------------


def assert_replan_occurred(min_count: int = 1) -> AssertionFn:
    """Assert that dynamic replanning occurred at least ``min_count`` times."""

    async def _assert(workflow_id: str) -> AssertionResult:
        from celeste.evaluation.detector import FeatureDetector

        detector = FeatureDetector()
        evidence = await detector.detect_replan(workflow_id)
        passed = evidence.replan_count >= min_count
        return AssertionResult(
            name="assert_replan_occurred",
            passed=passed,
            message=f"replan_count={evidence.replan_count} (expected >= {min_count})",
            evidence=evidence.model_dump(),
        )

    _assert.__name__ = "assert_replan_occurred"
    return _assert


def assert_saga_compensation(
    trigger_pattern: str = "",
    expected_chain: list[str] | None = None,
) -> AssertionFn:
    """Assert that saga compensation occurred with the expected chain."""

    async def _assert(workflow_id: str) -> AssertionResult:
        from celeste.evaluation.detector import FeatureDetector

        detector = FeatureDetector()
        evidence = await detector.detect_saga(workflow_id)
        passed = bool(evidence.chain_executed)
        if trigger_pattern and evidence.trigger:
            passed = passed and (trigger_pattern in evidence.trigger)
        if expected_chain and evidence.chain_executed:
            passed = passed and evidence.chain_executed == expected_chain
        return AssertionResult(
            name="assert_saga_compensation",
            passed=passed,
            message=f"trigger={evidence.trigger}, chain={evidence.chain_executed}",
            evidence=evidence.model_dump(),
        )

    _assert.__name__ = "assert_saga_compensation"
    return _assert


def assert_escalation(
    tier: int = 4,
    resolved: bool = True,
    max_pause_minutes: float = 60.0,
) -> AssertionFn:
    """Assert that tiered escalation occurred and was resolved."""

    async def _assert(workflow_id: str) -> AssertionResult:
        from celeste.evaluation.detector import FeatureDetector

        detector = FeatureDetector()
        evidence = await detector.detect_escalation(workflow_id, max_pause_minutes)
        passed = evidence.tier == tier
        if resolved:
            passed = passed and evidence.human_input_present
        if evidence.error:
            passed = False
        return AssertionResult(
            name="assert_escalation",
            passed=passed,
            message=f"tier={evidence.tier}, human_input={evidence.human_input_present}",
            evidence=evidence.model_dump(),
        )

    _assert.__name__ = "assert_escalation"
    return _assert


def assert_checkpoint_state_match() -> AssertionFn:
    """Assert that continue-as-new preserved state correctly."""

    async def _assert(workflow_id: str) -> AssertionResult:
        from celeste.evaluation.detector import FeatureDetector

        detector = FeatureDetector()
        evidence = await detector.detect_checkpoint(workflow_id)
        passed = evidence.checkpoint_count > 0 and evidence.state_hash_match is not False
        return AssertionResult(
            name="assert_checkpoint_state_match",
            passed=passed,
            message=f"checkpoints={evidence.checkpoint_count}, hash_match={evidence.state_hash_match}",
            evidence=evidence.model_dump(),
        )
    _assert.__name__ = "assert_checkpoint_state_match"
    return _assert


def assert_multi_workspace(min_concurrent: int = 4) -> AssertionFn:
    """Assert that multi-workspace parallelism reached the threshold."""

    async def _assert(workflow_id: str) -> AssertionResult:
        from celeste.evaluation.detector import FeatureDetector

        detector = FeatureDetector()
        evidence = await detector.detect_multi_workspace(workflow_id)
        passed = evidence.concurrent_max >= min_concurrent and evidence.workspaces_leaked == 0
        return AssertionResult(
            name="assert_multi_workspace",
            passed=passed,
            message=f"concurrent_max={evidence.concurrent_max}, leaked={evidence.workspaces_leaked}",
            evidence=evidence.model_dump(),
        )
    _assert.__name__ = "assert_multi_workspace"
    return _assert


def assert_security_pipeline(
    min_blocked: int = 1,
    full_audit_coverage: bool = True,
) -> AssertionFn:
    """Assert that the security pipeline blocked dangerous calls."""

    async def _assert(workflow_id: str) -> AssertionResult:
        from celeste.evaluation.detector import FeatureDetector

        detector = FeatureDetector()
        evidence = await detector.detect_security(workflow_id)
        passed = evidence.blocked_count >= min_blocked
        if full_audit_coverage:
            passed = passed and evidence.missing_audit_count == 0
        if evidence.error:
            passed = False
        return AssertionResult(
            name="assert_security_pipeline",
            passed=passed,
            message=f"blocked={evidence.blocked_count}, missing_audit={evidence.missing_audit_count}",
            evidence=evidence.model_dump(),
        )

    _assert.__name__ = "assert_security_pipeline"
    return _assert
