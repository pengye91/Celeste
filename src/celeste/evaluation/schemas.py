"""Pydantic models for Celeste evaluation reports and metrics."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Evidence models
# ---------------------------------------------------------------------------


class ReplanEvidence(BaseModel):
    """Evidence of dynamic replanning in a workflow."""

    replan_count: int = 0
    dag_diffs: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class SagaEvidence(BaseModel):
    """Evidence of saga compensation in a workflow."""

    trigger: str | None = None
    chain_executed: list[str] = Field(default_factory=list)
    affected_scope: str | None = None
    error: str | None = None


class EscalationEvidence(BaseModel):
    """Evidence of tiered escalation in a workflow."""

    tier: int | None = None
    pause_duration_seconds: float | None = None
    human_input_present: bool = False
    error: str | None = None


class CheckpointEvidence(BaseModel):
    """Evidence of continue-as-new checkpointing."""

    checkpoint_count: int = 0
    recovery_count: int = 0
    state_hash_match: bool | None = None
    error: str | None = None


class MultiWorkspaceEvidence(BaseModel):
    """Evidence of multi-workspace parallelism."""

    concurrent_max: int = 0
    workspaces_leaked: int = 0
    error: str | None = None


class SecurityEvidence(BaseModel):
    """Evidence of security pipeline operation."""

    audit_coverage_percent: float = 0.0
    blocked_count: int = 0
    false_positive_count: int = 0
    missing_audit_count: int = 0
    error: str | None = None


class CrossModeEvidence(BaseModel):
    """Evidence of cross-mode parity."""

    modes_tested: list[str] = Field(default_factory=list)
    state_hashes: dict[str, str] = Field(default_factory=dict)
    match: bool | None = None
    error: str | None = None


class ModelAgnosticismEvidence(BaseModel):
    """Evidence of model agnosticism."""

    providers_tested: list[str] = Field(default_factory=list)
    state_hashes: dict[str, str] = Field(default_factory=dict)
    match: bool | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------


class FeatureResult(BaseModel):
    """Result for a single feature verification."""

    name: str
    status: Literal["PASS", "FAIL", "NOT_EXERCISED"]
    evidence: dict[str, Any] = Field(default_factory=dict)
    assertion: str = ""


class RuntimeMetrics(BaseModel):
    """Runtime execution metrics."""

    opa_cycles: int = 0
    total_nodes: int = 0
    completed_nodes: int = 0
    failed_nodes: int = 0
    compensated_nodes: int = 0
    avg_cycle_latency_ms: float | None = None


class TokenCostBreakdown(BaseModel):
    """Token usage and cost breakdown."""

    planner_tokens: int = 0
    evaluator_tokens: int = 0
    security_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class EvaluationReport(BaseModel):
    """Structured evaluation report for a workflow."""

    workflow_id: str
    overall: Literal["PASS", "FAIL", "PARTIAL"]
    features: dict[str, FeatureResult] = Field(default_factory=dict)
    metrics: RuntimeMetrics = Field(default_factory=RuntimeMetrics)
    warnings: list[str] = Field(default_factory=list)
    token_cost: TokenCostBreakdown = Field(default_factory=TokenCostBreakdown)
