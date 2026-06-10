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

from sqlalchemy import JSON, Enum, String, Text, ForeignKey, Integer
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
    COMPLETED = "completed"
    FAILED = "failed"


class TaskEventType(str, enum.Enum):
    """Types of events recorded in the event-sourced ledger."""

    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    COMPENSATION_TRIGGERED = "compensation_triggered"
    STATE_CHECKPOINT = "state_checkpoint"


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

    # Relationships
    task_nodes: Mapped[list["TaskNode"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
    )
    task_events: Mapped[list["TaskEvent"]] = relationship(
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
