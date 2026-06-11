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
        """Create a new WorkflowEvent with type CHECKPOINT.

        Stores the checkpoint_state in the event_data field.
        """
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
                    event_data=checkpoint_state,
                )
            )

        logger.info(
            "Recorded CHECKPOINT event for workflow %s (seq=%d)",
            workflow_id,
            seq,
        )

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
