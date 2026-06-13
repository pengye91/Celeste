"""
SQLAlchemy 2.0 models for the Celeste-DAG Event-Sourced Transaction Log.

Three core tables:
    - workflows: Top-level workflow records with DAG definitions.
    - task_nodes: Individual DAG execution nodes with adjacency lists.
    - task_events: Immutable event-sourced ledger for state transitions.

Uses SQLAlchemy 2.0 DeclarativeBase with Mapped / mapped_column type annotations.
All datetime fields are timezone-aware.
"""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Enum, String, Text, ForeignKey, Integer, Index
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Declarative base for all Celeste-DAG models."""

    type_annotation_map = {
        dict[str, Any]: JSON,
    }


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskNodeStatus(str, enum.Enum):
    """Status of a single DAG task node."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowStatus(str, enum.Enum):
    """Status of an entire workflow."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskEventType(str, enum.Enum):
    """Types of events recorded in the event-sourced ledger."""

    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    COMPENSATION_TRIGGERED = "compensation_triggered"
    COMPENSATION_COMPLETED = "compensation_completed"
    COMPENSATION_FAILED = "compensation_failed"
    STATE_CHECKPOINT = "state_checkpoint"

    # OPA loop event types
    WORKFLOW_SUBMITTED = "workflow_submitted"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    OBSERVATION_CAPTURED = "observation_captured"
    PLAN_GENERATED = "plan_generated"
    EVALUATION_RESULT = "evaluation_result"
    PRECONDITION_CHECKED = "precondition_checked"
    CYCLE_STARTED = "cycle_started"
    CHECKPOINT = "checkpoint"
    ESCALATE = "escalate"
    WORKFLOW_PAUSED = "workflow_paused"
    HUMAN_INPUT_RECEIVED = "human_input_received"
    WORKFLOW_RESUMED = "workflow_resumed"

    # Security audit event type
    SECURITY_AUDIT = "security_audit"

    # Workspace lifecycle event types
    WORKSPACE_SPAWN = "workspace_spawn"
    WORKSPACE_DESTROY = "workspace_destroy"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


class Workflow(Base):
    """Top-level workflow record.

    Each workflow contains a full DAG definition compiled by the planner,
    along with status tracking metadata.
    """

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, name="workflow_status", native_enum=False),
        nullable=False,
        default=WorkflowStatus.PENDING,
    )
    dag_definition: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    human_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(nullable=True)
    llm_tokens_accumulated: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # Relationships
    task_nodes: Mapped[list["TaskNode"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
    )
    task_events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
    )
    workflow_events: Mapped[list["WorkflowEvent"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Workflow id={self.id} name={self.name!r} status={self.status.value!r}>"


# ---------------------------------------------------------------------------
# TaskNode
# ---------------------------------------------------------------------------


class TaskNode(Base):
    """A single execution node in the DAG.

    Tracks the command to run, its arguments, status, and adjacency links
    (previous_node_ids / next_node_ids) for DAG traversal.

    Supports Saga pattern via compensation_command / compensation_arguments.
    """

    __tablename__ = "task_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[TaskNodeStatus] = mapped_column(
        Enum(TaskNodeStatus, name="task_node_status", native_enum=False),
        nullable=False,
        default=TaskNodeStatus.PENDING,
    )
    command: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    previous_node_ids: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    next_node_ids: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    outputs: Mapped[str | None] = mapped_column(Text, nullable=True)
    compensation_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    compensation_arguments: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    # Relationships
    workflow: Mapped["Workflow"] = relationship(back_populates="task_nodes")
    task_events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task_node",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<TaskNode id={self.id} name={self.name!r} "
            f"status={self.status.value!r} type={self.task_type!r}>"
        )


# ---------------------------------------------------------------------------
# TaskEvent
# ---------------------------------------------------------------------------


class TaskEvent(Base):
    """Immutable event-sourced ledger entry.

    Every state transition (start, complete, fail, compensation) is recorded
    here to support durable state replays and audit trails.
    """

    __tablename__ = "task_events"

    __table_args__ = (
        Index("idx_task_events_wf_type", "workflow_id", "event_type"),
        Index("idx_task_events_correlation", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    task_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_nodes.id"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[TaskEventType] = mapped_column(
        Enum(TaskEventType, name="task_event_type", native_enum=False),
        nullable=False,
        index=True,
    )
    event_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    sequence_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
    )
    # OBS-002: correlation_id groups events emitted within the same OPA cycle
    # (or other logical causal unit) so the FeatureDetector and audit
    # consumers can follow causal links across replans and compensations.
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        default=None,
    )
    timestamp: Mapped[datetime] = mapped_column(
        nullable=False,
        default=_utcnow,
    )

    # Relationships
    task_node: Mapped["TaskNode"] = relationship(back_populates="task_events")
    workflow: Mapped["Workflow"] = relationship(back_populates="task_events")

    def __repr__(self) -> str:
        return (
            f"<TaskEvent id={self.id} type={self.event_type.value!r} "
            f"node={self.task_node_id}>"
        )


# ---------------------------------------------------------------------------
# WorkflowEvent
# ---------------------------------------------------------------------------


class WorkflowEvent(Base):
    """Workflow-level event for OPA loop tracking.

    Records high-level workflow lifecycle events (submission, observation,
    planning, evaluation, checkpointing) to support the OPA loop audit trail.
    """

    __tablename__ = "workflow_events"

    __table_args__ = (
        Index("idx_workflow_events_wf_type", "workflow_id", "event_type"),
        Index("idx_workflow_events_correlation", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id"),
        nullable=False,
        index=True,
    )
    task_node_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_nodes.id"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[TaskEventType] = mapped_column(
        Enum(TaskEventType, name="task_event_type", native_enum=False),
        nullable=False,
        index=True,
    )
    event_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    # OBS-002: correlation_id groups events emitted within the same OPA cycle
    # so audit consumers can follow causal links across replans and
    # compensations without relying on timestamp heuristics.
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        default=None,
    )
    timestamp: Mapped[datetime] = mapped_column(
        nullable=False,
        default=_utcnow,
    )

    # Relationships
    workflow: Mapped["Workflow"] = relationship(back_populates="workflow_events")

    def __repr__(self) -> str:
        return (
            f"<WorkflowEvent id={self.id} type={self.event_type.value!r} "
            f"workflow={self.workflow_id} seq={self.sequence_number}>"
        )
