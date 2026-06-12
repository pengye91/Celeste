"""Runtime metrics collection for Celeste evaluation.

Collects node counts, cycle latencies, and token usage from the event log.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from celeste.database.db import get_session
from celeste.database.models import TaskEvent, TaskEventType, TaskNode, WorkflowEvent
from celeste.evaluation.schemas import RuntimeMetrics, TokenCostBreakdown


class MetricsCollector:
    """Collect runtime metrics from the event-sourced ledger."""

    @staticmethod
    def _wf_id(workflow_id: str) -> uuid.UUID:
        return uuid.UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id

    async def collect(self, workflow_id: str) -> RuntimeMetrics:
        """Gather runtime metrics for a workflow."""
        async with get_session() as session:
            # OPA cycles = number of CYCLE_STARTED events
            cycle_result = await session.execute(
                select(func.count(WorkflowEvent.id))
                .where(
                    WorkflowEvent.workflow_id == self._wf_id(workflow_id),
                    WorkflowEvent.event_type == TaskEventType.CYCLE_STARTED,
                )
            )
            opa_cycles = cycle_result.scalar() or 0

            # Node counts
            node_result = await session.execute(
                select(TaskNode.status, func.count(TaskNode.id))
                .where(TaskNode.workflow_id == self._wf_id(workflow_id))
                .group_by(TaskNode.status)
            )
            status_counts = dict(node_result.all())

            total_nodes = sum(status_counts.values())
            completed_nodes = status_counts.get("completed", 0)
            failed_nodes = status_counts.get("failed", 0)

            # Compensated nodes
            comp_result = await session.execute(
                select(func.count(TaskEvent.id))
                .where(
                    TaskEvent.workflow_id == self._wf_id(workflow_id),
                    TaskEvent.event_type == TaskEventType.COMPENSATION_COMPLETED,
                )
            )
            compensated_nodes = comp_result.scalar() or 0

            # Average cycle latency (if we have cycle start/end events)
            # For simplicity, we estimate based on available events.
            avg_latency = None

        return RuntimeMetrics(
            opa_cycles=opa_cycles,
            total_nodes=total_nodes,
            completed_nodes=completed_nodes,
            failed_nodes=failed_nodes,
            compensated_nodes=compensated_nodes,
            avg_cycle_latency_ms=avg_latency,
        )

    async def collect_token_cost(self, workflow_id: str) -> TokenCostBreakdown:
        """Estimate token cost from event log metadata.

        In a production system this would read actual LLM usage metadata.
        Here we estimate from event counts.
        """
        async with get_session() as session:
            plan_result = await session.execute(
                select(func.count(WorkflowEvent.id))
                .where(
                    WorkflowEvent.workflow_id == self._wf_id(workflow_id),
                    WorkflowEvent.event_type == TaskEventType.PLAN_GENERATED,
                )
            )
            planner_calls = plan_result.scalar() or 0

            eval_result = await session.execute(
                select(func.count(WorkflowEvent.id))
                .where(
                    WorkflowEvent.workflow_id == self._wf_id(workflow_id),
                    WorkflowEvent.event_type == TaskEventType.EVALUATION_RESULT,
                )
            )
            evaluator_calls = eval_result.scalar() or 0

            # Rough estimates
            planner_tokens = planner_calls * 900
            evaluator_tokens = evaluator_calls * 800
            security_tokens = 0  # Not yet instrumented

            total = planner_tokens + evaluator_tokens + security_tokens
            # Rough cost at ~$0.03 per 1K tokens (Claude 3.5 Sonnet)
            estimated_cost = total * 0.00003

        return TokenCostBreakdown(
            planner_tokens=planner_tokens,
            evaluator_tokens=evaluator_tokens,
            security_tokens=security_tokens,
            total_tokens=total,
            estimated_cost_usd=estimated_cost,
        )
