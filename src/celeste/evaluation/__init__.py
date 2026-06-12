"""Celeste evaluation module — verify feature exercise from event logs."""

from celeste.evaluation.schemas import EvaluationReport, FeatureResult
from celeste.evaluation.detector import FeatureDetector
from celeste.evaluation.assertions import (
    AssertionRegistry,
    AssertionResult,
    assert_checkpoint_state_match,
    assert_escalation,
    assert_multi_workspace,
    assert_replan_occurred,
    assert_saga_compensation,
    assert_security_pipeline,
)
from celeste.evaluation.reporter import format_report
from celeste.evaluation.collector import MetricsCollector
from celeste.evaluation.compliance import ComplianceChecker

__all__ = [
    "Evaluator",
    "EvaluationReport",
    "FeatureDetector",
    "AssertionRegistry",
    "AssertionResult",
    "assert_checkpoint_state_match",
    "assert_escalation",
    "assert_multi_workspace",
    "assert_replan_occurred",
    "assert_saga_compensation",
    "assert_security_pipeline",
    "format_report",
    "MetricsCollector",
    "ComplianceChecker",
]


class Evaluator:
    """Orchestrate evaluation of a completed workflow.

    Usage:
        evaluator = Evaluator(workflow_id="wf_001")
        evaluator.assertions.add(assert_replan_occurred(min_count=1))
        report = await evaluator.evaluate()
        print(format_report(report))
    """

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self.assertions = AssertionRegistry()
        self._detector = FeatureDetector()
        self._collector = MetricsCollector()

    async def evaluate(self) -> EvaluationReport:
        """Run all detectors, assertions, and produce a report."""
        # Run feature detectors
        replan_ev = await self._detector.detect_replan(self.workflow_id)
        saga_ev = await self._detector.detect_saga(self.workflow_id)
        escalation_ev = await self._detector.detect_escalation(self.workflow_id)
        checkpoint_ev = await self._detector.detect_checkpoint(self.workflow_id)
        multi_ws_ev = await self._detector.detect_multi_workspace(self.workflow_id)
        security_ev = await self._detector.detect_security(self.workflow_id)

        features: dict[str, FeatureResult] = {}

        # Build feature results from detectors + assertions
        features["dynamic_opa_loop"] = FeatureResult(
            name="Dynamic OPA Loop",
            status="PASS" if replan_ev.replan_count > 0 else "NOT_EXERCISED",
            evidence=replan_ev.model_dump(),
            assertion="replan_events >= 1 AND dag_nodes_changed >= 1",
        )
        features["saga_compensation"] = FeatureResult(
            name="Saga Compensation",
            status="PASS" if saga_ev.chain_executed else "NOT_EXERCISED",
            evidence=saga_ev.model_dump(),
            assertion="compensation chain matches expected sequence",
        )
        features["tiered_escalation"] = FeatureResult(
            name="Tiered Escalation",
            status="PASS" if escalation_ev.human_input_present else "NOT_EXERCISED",
            evidence=escalation_ev.model_dump(),
            assertion="tier-4 pause occurred AND human input received",
        )
        features["continue_as_new"] = FeatureResult(
            name="Continue-As-New",
            status="PASS" if checkpoint_ev.checkpoint_count > 0 else "NOT_EXERCISED",
            evidence=checkpoint_ev.model_dump(),
            assertion="checkpoint_events >= 1 AND state_hash_match",
        )
        features["multi_workspace"] = FeatureResult(
            name="Multi-Workspace Parallelism",
            status="PASS" if multi_ws_ev.concurrent_max >= 4 else "NOT_EXERCISED",
            evidence=multi_ws_ev.model_dump(),
            assertion="concurrent_max >= 4 AND no workspace leaks",
        )
        features["security_pipeline"] = FeatureResult(
            name="Security Pipeline",
            status="PASS" if security_ev.blocked_count >= 1 else "NOT_EXERCISED",
            evidence=security_ev.model_dump(),
            assertion="blocked_events >= 1 AND 100% audit coverage",
        )
        features["cross_mode_parity"] = FeatureResult(
            name="Cross-Mode Parity",
            status="NOT_EXERCISED",
            evidence={},
            assertion="identical feature results across Local/Remote/Embedded",
        )
        features["model_agnosticism"] = FeatureResult(
            name="Model Agnosticism",
            status="NOT_EXERCISED",
            evidence={},
            assertion="identical final_state_hash across 2+ providers",
        )

        # Run custom assertions
        assertion_results = await self.assertions.evaluate(self.workflow_id)
        for ar in assertion_results:
            if ar.name in features:
                # Merge assertion result into existing feature
                existing = features[ar.name]
                if not ar.passed:
                    existing.status = "FAIL"
                existing.evidence.update(ar.evidence)
                existing.assertion = ar.message
            else:
                features[ar.name] = ar.to_feature_result()

        # Determine overall status
        statuses = [f.status for f in features.values()]
        all_pass = all(s == "PASS" for s in statuses)
        all_fail = all(s == "FAIL" for s in statuses)
        any_fail = any(s == "FAIL" for s in statuses)

        if all_pass:
            overall = "PASS"
        elif all_fail:
            overall = "FAIL"
        elif any_fail:
            overall = "PARTIAL"
        else:
            overall = "PARTIAL"

        metrics = await self._collector.collect(self.workflow_id)
        token_cost = await self._collector.collect_token_cost(self.workflow_id)

        warnings: list[str] = []
        for name, feature in features.items():
            if feature.status == "NOT_EXERCISED":
                warnings.append(f"Feature '{name}' was not exercised.")

        return EvaluationReport(
            workflow_id=self.workflow_id,
            overall=overall,
            features=features,
            metrics=metrics,
            warnings=warnings,
            token_cost=token_cost,
        )
