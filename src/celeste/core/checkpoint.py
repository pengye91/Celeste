"""
Continue-As-New checkpointing for Celeste-DAG.

Provides CheckpointManager which:
- Monitors WorkflowEvent counts per workflow
- Creates state snapshots (checkpoints) containing goal, context, completed/failed nodes
- Records CHECKPOINT events in the event ledger
- Supports resuming workflows from checkpoint state

Integration with Engine:
- Engine calls _check_and_checkpoint at the end of each OPA cycle
- When threshold is reached, the old workflow is archived and a new workflow
  run is created with the checkpoint state as initial state
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy import func, select

from celeste.config.settings import EngineSettings
from celeste.database.db import get_session
from celeste.database.models import (
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Manages Continue-As-New checkpointing for long-running workflows.

    Attributes:
        _settings: EngineSettings for database connection.
        _event_threshold: Number of WorkflowEvent records that triggers a checkpoint.
    """

    def __init__(
        self,
        settings: EngineSettings | None = None,
        event_threshold: int = 500,
    ) -> None:
        self._settings = settings or EngineSettings()
        self._event_threshold = event_threshold

    async def should_checkpoint(self, workflow_id: uuid.UUID) -> bool:
        """Return True if the workflow has reached the event threshold.

        Counts WorkflowEvent records for the given workflow and compares
        against the configured event_threshold.
        """
        async with get_session() as session:
            result = await session.execute(
                select(func.count(WorkflowEvent.id)).where(
                    WorkflowEvent.workflow_id == workflow_id
                )
            )
            count = result.scalar() or 0

        return count >= self._event_threshold

    async def create_checkpoint(self, workflow_id: uuid.UUID) -> dict[str, Any]:
        """Query the database and return a checkpoint state dict.

        The returned dict contains:
            - goal: str
            - context: dict
            - completed_node_ids: list[str]
            - failed_node_ids: list[str]
            - cycle_count: int
            - llm_tokens_accumulated: int
        """
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")

            dag_def = workflow.dag_definition or {}
            goal = dag_def.get("goal", "")
            context = dag_def.get("context", {})

            # Count cycles from CYCLE_STARTED events
            cycle_result = await session.execute(
                select(func.count(WorkflowEvent.id)).where(
                    WorkflowEvent.workflow_id == workflow_id,
                    WorkflowEvent.event_type == TaskEventType.CYCLE_STARTED,
                )
            )
            cycle_count = cycle_result.scalar() or 0

            # Count LLM tokens from relevant events (stored in event_data)
            token_result = await session.execute(
                select(WorkflowEvent).where(
                    WorkflowEvent.workflow_id == workflow_id,
                )
            )
            events = token_result.scalars().all()
            llm_tokens_accumulated = 0
            for event in events:
                if event.event_data and "llm_tokens" in event.event_data:
                    llm_tokens_accumulated += event.event_data["llm_tokens"]

            # Gather completed and failed node IDs
            node_result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == workflow_id)
            )
            nodes = node_result.scalars().all()

            completed_node_ids = [
                str(n.id) for n in nodes if n.status == TaskNodeStatus.COMPLETED
            ]
            failed_node_ids = [
                str(n.id) for n in nodes if n.status == TaskNodeStatus.FAILED
            ]

        return {
            "goal": goal,
            "context": context,
            "completed_node_ids": completed_node_ids,
            "failed_node_ids": failed_node_ids,
            "cycle_count": cycle_count,
            "llm_tokens_accumulated": llm_tokens_accumulated,
        }

    async def record_checkpoint_event(
        self,
        workflow_id: uuid.UUID,
        checkpoint_state: dict[str, Any],
    ) -> None:
        """Create new WorkflowEvents with types CHECKPOINT and STATE_CHECKPOINT.

        OBS-006: FeatureDetector.detect_checkpoint queries for both event
        types. The CHECKPOINT event stores the snapshot state in event_data;
        the STATE_CHECKPOINT event stores a deterministic state_hash so
        detect_checkpoint can compute hash_match across multiple checkpoints.

        Stores the checkpoint_state in the event_data field.
        """
        # Compute deterministic hash of the checkpoint state so the
        # detector can compare hashes across multiple STATE_CHECKPOINT
        # rows for the same workflow.
        state_hash = self._compute_state_hash(checkpoint_state)

        async with get_session() as session:
            # Get next sequence number
            result = await session.execute(
                select(func.count(WorkflowEvent.id)).where(
                    WorkflowEvent.workflow_id == workflow_id
                )
            )
            seq = (result.scalar() or 0) + 1

            session.add(
                WorkflowEvent(
                    workflow_id=workflow_id,
                    event_type=TaskEventType.CHECKPOINT,
                    sequence_number=seq,
                    event_data={**checkpoint_state, "state_hash": state_hash},
                )
            )

            # OBS-006: emit STATE_CHECKPOINT as a sibling event so the
            # detector's `recoveries = [e for e in events if e.event_type ==
            # TaskEventType.STATE_CHECKPOINT]` query yields non-empty results.
            session.add(
                WorkflowEvent(
                    workflow_id=workflow_id,
                    event_type=TaskEventType.STATE_CHECKPOINT,
                    sequence_number=seq + 1,
                    event_data={
                        "state_hash": state_hash,
                        "completed_node_count": len(
                            checkpoint_state.get("completed_node_ids", [])
                        ),
                        "failed_node_count": len(
                            checkpoint_state.get("failed_node_ids", [])
                        ),
                        "cycle_count": checkpoint_state.get("cycle_count", 0),
                    },
                )
            )

        logger.info(
            "Recorded CHECKPOINT + STATE_CHECKPOINT events for workflow %s (seq=%d)",
            workflow_id,
            seq,
        )

    @staticmethod
    def _compute_state_hash(checkpoint_state: dict[str, Any]) -> str:
        """Deterministic SHA-256 over a sorted JSON serialization of the state."""
        # sort_keys ensures identical dicts hash to the same digest
        # regardless of key order in the source.
        canonical = json.dumps(checkpoint_state, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def resume_from_checkpoint(
        self,
        checkpoint_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Return the state needed to resume a workflow from a checkpoint.

        Returns the checkpoint_state dict directly, which contains all
        fields needed to continue execution.
        """
        return {
            "goal": checkpoint_state.get("goal", ""),
            "context": checkpoint_state.get("context", {}),
            "completed_node_ids": checkpoint_state.get("completed_node_ids", []),
            "failed_node_ids": checkpoint_state.get("failed_node_ids", []),
            "cycle_count": checkpoint_state.get("cycle_count", 0),
            "llm_tokens_accumulated": checkpoint_state.get(
                "llm_tokens_accumulated", 0
            ),
        }
