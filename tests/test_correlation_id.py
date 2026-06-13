"""
Tests for OBS-002: correlation_id column on TaskEvent and WorkflowEvent.

These tests verify that:
- correlation_id column exists on both TaskEvent and WorkflowEvent
- The column is nullable (so existing rows and rows without correlation still work)
- The column is indexed (so correlation queries are fast)
- Events can be queried/filtered by correlation_id
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, select

from celeste.database.models import (
    Base,
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)


@pytest.fixture()
def engine():
    """Create a synchronous SQLite in-memory engine for testing."""
    from sqlalchemy import create_engine, event

    eng = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def sample_workflow(engine):
    """Create a Workflow and TaskNode row directly via sync session."""
    from sqlalchemy.orm import Session

    with Session(bind=engine) as session:
        wf = Workflow(
            name="corr-test",
            status=WorkflowStatus.RUNNING,
            dag_definition={"nodes": []},
        )
        session.add(wf)
        session.flush()
        node = TaskNode(
            workflow_id=wf.id,
            name="n1",
            task_type="tool_execution",
            status=TaskNodeStatus.PENDING,
            command="echo",
            arguments={},
        )
        session.add(node)
        session.flush()
        return wf.id, node.id


class TestCorrelationIdColumn:
    """TaskEvent and WorkflowEvent must expose a correlation_id column."""

    def test_task_event_has_correlation_id_column(self, engine):
        inspector = inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("task_events")}
        assert "correlation_id" in cols, (
            "TaskEvent must have a correlation_id column for OBS-002"
        )

    def test_workflow_event_has_correlation_id_column(self, engine):
        inspector = inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("workflow_events")}
        assert "correlation_id" in cols, (
            "WorkflowEvent must have a correlation_id column for OBS-002"
        )

    def test_task_event_correlation_id_is_nullable(self, engine):
        from sqlalchemy.orm import Session

        wf_id = uuid.uuid4()
        node_id = uuid.uuid4()
        with Session(bind=engine) as session:
            session.add(
                Workflow(id=wf_id, name="wf", status=WorkflowStatus.RUNNING, dag_definition={})
            )
            session.add(
                TaskNode(
                    id=node_id,
                    workflow_id=wf_id,
                    name="n",
                    task_type="tool_execution",
                    status=TaskNodeStatus.PENDING,
                    command="echo",
                    arguments={},
                )
            )
            session.flush()
            # correlation_id is omitted -> should default to None
            ev = TaskEvent(
                task_node_id=node_id,
                workflow_id=wf_id,
                event_type=TaskEventType.NODE_STARTED,
            )
            session.add(ev)
            session.flush()
            assert ev.correlation_id is None

    def test_workflow_event_correlation_id_is_nullable(self, engine):
        from sqlalchemy.orm import Session

        wf_id = uuid.uuid4()
        with Session(bind=engine) as session:
            session.add(
                Workflow(id=wf_id, name="wf", status=WorkflowStatus.RUNNING, dag_definition={})
            )
            session.flush()
            ev = WorkflowEvent(
                workflow_id=wf_id,
                event_type=TaskEventType.CHECKPOINT,
                sequence_number=1,
            )
            session.add(ev)
            session.flush()
            assert ev.correlation_id is None

    def test_task_event_correlation_id_is_indexed(self, engine):
        inspector = inspect(engine)
        idxs = inspector.get_indexes("task_events")
        idx_cols = [tuple(i["column_names"]) for i in idxs]
        assert ("correlation_id",) in idx_cols or any(
            "correlation_id" in (i["column_names"] or ()) for i in idxs
        ), "correlation_id must be indexed for fast correlation lookups"

    def test_workflow_event_correlation_id_is_indexed(self, engine):
        inspector = inspect(engine)
        idxs = inspector.get_indexes("workflow_events")
        idx_cols = [tuple(i["column_names"]) for i in idxs]
        assert ("correlation_id",) in idx_cols or any(
            "correlation_id" in (i["column_names"] or ()) for i in idxs
        ), "correlation_id must be indexed on workflow_events"

    def test_task_event_correlation_id_round_trip(self, engine):
        """Set correlation_id on creation and read it back."""
        from sqlalchemy.orm import Session

        wf_id = uuid.uuid4()
        node_id = uuid.uuid4()
        corr = uuid.uuid4()
        with Session(bind=engine) as session:
            session.add(
                Workflow(id=wf_id, name="wf", status=WorkflowStatus.RUNNING, dag_definition={})
            )
            session.add(
                TaskNode(
                    id=node_id,
                    workflow_id=wf_id,
                    name="n",
                    task_type="tool_execution",
                    status=TaskNodeStatus.PENDING,
                    command="echo",
                    arguments={},
                )
            )
            ev = TaskEvent(
                task_node_id=node_id,
                workflow_id=wf_id,
                event_type=TaskEventType.NODE_STARTED,
                correlation_id=corr,
            )
            session.add(ev)
            session.commit()

        with Session(bind=engine) as session:
            fetched = session.execute(
                select(TaskEvent).where(TaskEvent.correlation_id == corr)
            ).scalar_one()
            assert fetched.correlation_id == corr

    def test_workflow_event_correlation_id_round_trip(self, engine):
        """Set correlation_id on creation and read it back from workflow_events."""
        from sqlalchemy.orm import Session

        wf_id = uuid.uuid4()
        corr = uuid.uuid4()
        with Session(bind=engine) as session:
            session.add(
                Workflow(id=wf_id, name="wf", status=WorkflowStatus.RUNNING, dag_definition={})
            )
            ev = WorkflowEvent(
                workflow_id=wf_id,
                event_type=TaskEventType.CHECKPOINT,
                sequence_number=1,
                correlation_id=corr,
            )
            session.add(ev)
            session.commit()

        with Session(bind=engine) as session:
            fetched = session.execute(
                select(WorkflowEvent).where(WorkflowEvent.correlation_id == corr)
            ).scalar_one()
            assert fetched.correlation_id == corr