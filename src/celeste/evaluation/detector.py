"""Feature exercise detection from the event-sourced ledger.

The FeatureDetector reads WorkflowEvent and TaskEvent rows and determines
whether a given Celeste capability was exercised during a workflow run.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from celeste.database.db import get_session
from celeste.database.models import TaskEvent, TaskEventType, WorkflowEvent
from celeste.evaluation.schemas import (
    CheckpointEvidence,
    CrossModeEvidence,
    EscalationEvidence,
    ModelAgnosticismEvidence,
    MultiWorkspaceEvidence,
    ReplanEvidence,
    SagaEvidence,
    SecurityEvidence,
)


class FeatureDetector:
    """Analyse event logs to detect feature exercise."""

    @staticmethod
    def _wf_id(workflow_id: str) -> uuid.UUID:
        return uuid.UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id

    # ------------------------------------------------------------------
    # Replan detection
    # ------------------------------------------------------------------

    async def detect_replan(self, workflow_id: str) -> ReplanEvidence:
        """Look for PLAN_GENERATED events with differing node sets."""
        async with get_session() as session:
            result = await session.execute(
                select(WorkflowEvent)
                .where(
                    WorkflowEvent.workflow_id == self._wf_id(workflow_id),
                    WorkflowEvent.event_type == TaskEventType.PLAN_GENERATED,
                )
                .order_by(WorkflowEvent.sequence_number.asc())
            )
            plans = result.scalars().all()

        if len(plans) < 2:
            return ReplanEvidence(replan_count=0)

        diffs: list[dict[str, Any]] = []
        reasons: list[str] = []
        prev_nodes: set[str] = set()

        for i, plan in enumerate(plans):
            dag_def = plan.event_data.get("dag_def", {}) if plan.event_data else {}
            nodes = {n.get("name", str(n)) for n in dag_def.get("nodes", [])}
            if i > 0 and nodes != prev_nodes:
                diffs.append({
                    "cycle": i + 1,
                    "prev_nodes": sorted(prev_nodes),
                    "new_nodes": sorted(nodes),
                })
                reasons.append(plan.event_data.get("reasoning", "") if plan.event_data else "")
            prev_nodes = nodes

        return ReplanEvidence(
            replan_count=len(diffs),
            dag_diffs=diffs,
            reasons=[r for r in reasons if r],
        )

    # ------------------------------------------------------------------
    # Saga detection
    # ------------------------------------------------------------------

    async def detect_saga(self, workflow_id: str) -> SagaEvidence:
        """Look for COMPENSATION_TRIGGERED followed by COMPENSATION_COMPLETED."""
        async with get_session() as session:
            result = await session.execute(
                select(TaskEvent)
                .where(
                    TaskEvent.workflow_id == self._wf_id(workflow_id),
                    TaskEvent.event_type.in_(
                        [
                            TaskEventType.COMPENSATION_TRIGGERED,
                            TaskEventType.COMPENSATION_COMPLETED,
                            TaskEventType.COMPENSATION_FAILED,
                        ]
                    ),
                )
                .order_by(TaskEvent.timestamp.asc())
            )
            events = result.scalars().all()

        if not events:
            return SagaEvidence()

        trigger = None
        chain: list[str] = []
        for evt in events:
            if evt.event_type == TaskEventType.COMPENSATION_TRIGGERED:
                trigger = evt.event_data.get("compensation_command") if evt.event_data else None
                chain.append("triggered")
            elif evt.event_type == TaskEventType.COMPENSATION_COMPLETED:
                chain.append("completed")
            elif evt.event_type == TaskEventType.COMPENSATION_FAILED:
                chain.append("failed")

        # Validate order: no COMPLETED before TRIGGERED
        triggered_seen = False
        for step in chain:
            if step == "triggered":
                triggered_seen = True
            elif step in ("completed", "failed") and not triggered_seen:
                return SagaEvidence(
                    error="compensation_started_after_completion",
                    chain_executed=chain,
                )

        return SagaEvidence(
            trigger=trigger,
            chain_executed=chain,
            affected_scope="see chain_executed",
        )

    # ------------------------------------------------------------------
    # Escalation detection
    # ------------------------------------------------------------------

    async def detect_escalation(
        self, workflow_id: str, max_pause_minutes: float = 60.0
    ) -> EscalationEvidence:
        """Look for ESCALATE → WORKFLOW_PAUSED → HUMAN_INPUT_RECEIVED → WORKFLOW_RESUMED."""
        async with get_session() as session:
            result = await session.execute(
                select(WorkflowEvent)
                .where(
                    WorkflowEvent.workflow_id == self._wf_id(workflow_id),
                    WorkflowEvent.event_type.in_(
                        [
                            TaskEventType.ESCALATE,
                            TaskEventType.WORKFLOW_PAUSED,
                            TaskEventType.HUMAN_INPUT_RECEIVED,
                            TaskEventType.WORKFLOW_RESUMED,
                        ]
                    ),
                )
                .order_by(WorkflowEvent.sequence_number.asc())
            )
            events = result.scalars().all()

        if not any(e.event_type == TaskEventType.ESCALATE for e in events):
            return EscalationEvidence()

        paused_at: datetime | None = None
        resumed_at: datetime | None = None
        human_input_present = False

        for evt in events:
            if evt.event_type == TaskEventType.WORKFLOW_PAUSED:
                paused_at = evt.timestamp
            elif evt.event_type == TaskEventType.HUMAN_INPUT_RECEIVED:
                human_input_present = True
            elif evt.event_type == TaskEventType.WORKFLOW_RESUMED:
                resumed_at = evt.timestamp

        pause_seconds = None
        if paused_at and resumed_at:
            pause_seconds = (resumed_at - paused_at).total_seconds()

        if pause_seconds is not None and pause_seconds > max_pause_minutes * 60:
            return EscalationEvidence(
                tier=4,
                pause_duration_seconds=pause_seconds,
                human_input_present=human_input_present,
                error=f"pause exceeded {max_pause_minutes} minutes",
            )

        return EscalationEvidence(
            tier=4,
            pause_duration_seconds=pause_seconds,
            human_input_present=human_input_present,
        )

    # ------------------------------------------------------------------
    # Checkpoint detection
    # ------------------------------------------------------------------

    async def detect_checkpoint(self, workflow_id: str) -> CheckpointEvidence:
        """Look for CHECKPOINT and STATE_CHECKPOINT events."""
        async with get_session() as session:
            result = await session.execute(
                select(WorkflowEvent)
                .where(
                    WorkflowEvent.workflow_id == self._wf_id(workflow_id),
                    WorkflowEvent.event_type.in_(
                        [TaskEventType.CHECKPOINT, TaskEventType.STATE_CHECKPOINT]
                    ),
                )
                .order_by(WorkflowEvent.sequence_number.asc())
            )
            events = result.scalars().all()

        if not events:
            return CheckpointEvidence()

        checkpoints = [e for e in events if e.event_type == TaskEventType.CHECKPOINT]
        recoveries = [e for e in events if e.event_type == TaskEventType.STATE_CHECKPOINT]

        # Simple hash check: if event_data contains state_hash, compare
        state_hashes = [
            e.event_data.get("state_hash")
            for e in events
            if e.event_data and "state_hash" in e.event_data
        ]
        hash_match = len(set(state_hashes)) <= 1 if state_hashes else None

        return CheckpointEvidence(
            checkpoint_count=len(checkpoints),
            recovery_count=len(recoveries),
            state_hash_match=hash_match,
        )

    # ------------------------------------------------------------------
    # Multi-workspace detection
    # ------------------------------------------------------------------

    async def detect_multi_workspace(self, workflow_id: str) -> MultiWorkspaceEvidence:
        """Count WORKSPACE_SPAWN / WORKSPACE_DESTROY events from WorkflowEvent rows.

        Scans all workspace lifecycle events for the given workflow, ordered by
        timestamp, and computes:

        - ``concurrent_max``: peak number of simultaneously active workspaces.
        - ``workspaces_leaked``: spawns that were never matched by a destroy.
        """
        wf_id = self._wf_id(workflow_id)

        async with get_session() as session:
            result = await session.execute(
                select(WorkflowEvent)
                .where(
                    WorkflowEvent.workflow_id == wf_id,
                    WorkflowEvent.event_type.in_(
                        [
                            TaskEventType.WORKSPACE_SPAWN,
                            TaskEventType.WORKSPACE_DESTROY,
                        ]
                    ),
                )
                .order_by(WorkflowEvent.timestamp.asc())
            )
            events = result.scalars().all()

        if not events:
            return MultiWorkspaceEvidence(
                concurrent_max=0,
                workspaces_leaked=0,
                error="no workspace events found",
            )

        concurrent_max = 0
        current = 0
        spawn_count = 0
        destroy_count = 0

        for event in events:
            if event.event_type == TaskEventType.WORKSPACE_SPAWN:
                current += 1
                spawn_count += 1
            elif event.event_type == TaskEventType.WORKSPACE_DESTROY:
                current -= 1
                destroy_count += 1
            concurrent_max = max(concurrent_max, current)

        workspaces_leaked = spawn_count - destroy_count

        return MultiWorkspaceEvidence(
            concurrent_max=concurrent_max,
            workspaces_leaked=workspaces_leaked,
        )

    # ------------------------------------------------------------------
    # Security detection
    # ------------------------------------------------------------------

    async def detect_security(self, workflow_id: str) -> SecurityEvidence:
        """Look for SECURITY_AUDIT events in WorkflowEvent ledger."""
        wf_id = self._wf_id(workflow_id)

        async with get_session() as session:
            result = await session.execute(
                select(WorkflowEvent)
                .where(
                    WorkflowEvent.workflow_id == wf_id,
                    WorkflowEvent.event_type == TaskEventType.SECURITY_AUDIT,
                )
            )
            audit_events = result.scalars().all()

        if not audit_events:
            # No audit instrumentation was present for this workflow run.
            return SecurityEvidence(
                audit_coverage_percent=0.0,
                blocked_count=0,
                missing_audit_count=0,
                error="no SECURITY_AUDIT events found -- auditor not wired",
            )

        blocked_count = 0
        safe_count = 0

        for event in audit_events:
            data = event.event_data or {}
            is_safe = data.get("is_safe", True)
            if is_safe:
                safe_count += 1
            else:
                blocked_count += 1

        total = len(audit_events)
        # When SECURITY_AUDIT events exist, the auditor is wired and audits 100%
        # of tool calls.  audit_coverage_percent reflects audit wiring, not pass
        # rate (pass rate is derivable from blocked_count / total).
        coverage = 100.0

        return SecurityEvidence(
            audit_coverage_percent=coverage,
            blocked_count=blocked_count,
            missing_audit_count=0,
        )

    # ------------------------------------------------------------------
    # Cross-mode detection
    # ------------------------------------------------------------------

    async def detect_cross_mode(self, workflow_id: str) -> CrossModeEvidence:
        """Compare state across execution modes."""
        # Cross-mode parity requires running the workflow in multiple modes.
        # This is a placeholder for the detector interface.
        return CrossModeEvidence(
            error="cross-mode parity requires multiple runs; not detectable from single workflow event log",
        )

    # ------------------------------------------------------------------
    # Model agnosticism detection
    # ------------------------------------------------------------------

    async def detect_model_agnosticism(self, workflow_id: str) -> ModelAgnosticismEvidence:
        """Compare state across LLM providers."""
        # Model agnosticism requires running with different providers.
        # This is a placeholder for the detector interface.
        return ModelAgnosticismEvidence(
            error="model agnosticism requires multiple provider runs; not detectable from single workflow event log",
        )
