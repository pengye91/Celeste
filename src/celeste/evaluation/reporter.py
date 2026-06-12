"""Human-readable report formatting for Celeste evaluation reports."""

from __future__ import annotations

from celeste.evaluation.schemas import EvaluationReport, FeatureResult


def format_report(report: EvaluationReport) -> str:
    """Format an EvaluationReport as a human-readable string."""
    lines: list[str] = []
    width = 63

    lines.append("═" * width)
    lines.append(f"  Celeste Evaluation Report  |  Workflow: {report.workflow_id}")
    lines.append("═" * width)
    lines.append("")

    lines.append(f"Overall: {report.overall}")
    lines.append("")

    lines.append("Features:")
    for feature in report.features.values():
        symbol = "✓" if feature.status == "PASS" else "✗" if feature.status == "FAIL" else "○"
        lines.append(f"  {symbol} {feature.name:<25} {feature.status}")
        for key, value in feature.evidence.items():
            lines.append(f"      {key}={value}")
    lines.append("")

    metrics = report.metrics
    lines.append("Metrics:")
    lines.append(f"  OPA Cycles:        {metrics.opa_cycles}")
    lines.append(f"  Total Nodes:       {metrics.total_nodes}")
    lines.append(f"  Completed:         {metrics.completed_nodes}")
    lines.append(f"  Failed:            {metrics.failed_nodes}")
    lines.append(f"  Compensated:       {metrics.compensated_nodes}")
    if metrics.avg_cycle_latency_ms is not None:
        lines.append(f"  Avg Cycle Latency: {metrics.avg_cycle_latency_ms:.1f}ms")
    lines.append("")

    cost = report.token_cost
    lines.append("Token Cost:")
    lines.append(f"  Planner:   {cost.planner_tokens}")
    lines.append(f"  Evaluator: {cost.evaluator_tokens}")
    lines.append(f"  Security:  {cost.security_tokens}")
    lines.append(f"  Total:     {cost.total_tokens}  ≈ ${cost.estimated_cost_usd:.2f}")
    lines.append("")

    if report.warnings:
        lines.append("Warnings:")
        for warning in report.warnings:
            lines.append(f"  - {warning}")
        lines.append("")

    return "\n".join(lines)
