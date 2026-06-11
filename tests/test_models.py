"""
Tests for database models — TaskNode, TaskEvent, Workflow.

Follows strict TDD: these tests are written BEFORE the implementation.
Uses synchronous SQLite in-memory sessions for testability.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    """Create a synchronous SQLite in-memory engine for testing."""
    eng = create_engine("sqlite:///:memory:", echo=False)

    # Enable WAL mode and foreign keys for SQLite
    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    """Provide a transactional scope around a series of operations."""
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)

    yield sess

    sess.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def sample_workflow_id() -> uuid.UUID:
    """Return a fixed UUID for use as workflow_id in tests."""
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture()
def sample_workflow(session, sample_workflow_id):
    """Create and return a sample Workflow row."""
    wf = Workflow(
        id=sample_workflow_id,
        name="test-workflow",
        description="A test workflow for unit tests",
        status=WorkflowStatus.PENDING,
        dag_definition={
            "nodes": [
                {"name": "step1", "type": "llm_call"},
                {"name": "step2", "type": "tool_execution"},
            ],
            "edges": [["step1", "step2"]],
        },
    )
    session.add(wf)
    session.flush()
    return wf


# ===========================================================================
# Table Creation
# ===========================================================================


class TestTableCreation:
    """All tables must be created successfully."""

    def test_workflow_table_exists(self, engine):
        inspector = inspect(engine)
        assert "workflows" in inspector.get_table_names()

    def test_task_node_table_exists(self, engine):
        inspector = inspect(engine)
        assert "task_nodes" in inspector.get_table_names()

    def test_task_event_table_exists(self, engine):
        inspector = inspect(engine)
        assert "task_events" in inspector.get_table_names()

    def test_workflow_event_table_exists(self, engine):
        inspector = inspect(engine)
        assert "workflow_events" in inspector.get_table_names()


# ===========================================================================
# Workflow Model
# ===========================================================================


class TestWorkflowCreation:
    """Workflow can be created with all fields."""

    def test_create_workflow_with_all_fields(self, session, sample_workflow):
        wf = sample_workflow
        assert wf.id == uuid.UUID("00000000-0000-0000-0000-000000000001")
        assert wf.name == "test-workflow"
        assert wf.description == "A test workflow for unit tests"
        assert wf.status == WorkflowStatus.PENDING
        assert isinstance(wf.dag_definition, dict)
        assert "nodes" in wf.dag_definition
        assert "edges" in wf.dag_definition

    def test_workflow_uuid_primary_key_auto_generated(self, session):
        """UUID primary key should be auto-generated when not provided."""
        wf = Workflow(
            name="auto-id-workflow",
            status=WorkflowStatus.PENDING,
            dag_definition={},
        )
        session.add(wf)
        session.flush()
        assert wf.id is not None
        assert isinstance(wf.id, uuid.UUID)

    def test_workflow_description_nullable(self, session):
        """description is nullable."""
        wf = Workflow(
            name="no-desc",
            status=WorkflowStatus.RUNNING,
            dag_definition={"key": "value"},
        )
        session.add(wf)
        session.flush()
        assert wf.description is None

    def test_workflow_timestamps_auto_set(self, session):
        """created_at and updated_at must be auto-set on creation."""
        wf = Workflow(
            name="ts-workflow",
            status=WorkflowStatus.PENDING,
            dag_definition={},
        )
        session.add(wf)
        session.flush()
        assert wf.created_at is not None
        assert wf.updated_at is not None
        assert isinstance(wf.created_at, datetime)
        assert isinstance(wf.updated_at, datetime)

    def test_workflow_dag_definition_json(self, session):
        """dag_definition stores arbitrary JSON."""
        dag = {
            "nodes": [
                {"id": "a", "type": "llm_call", "command": "analyze"},
                {"id": "b", "type": "tool_execution", "command": "run"},
            ],
            "edges": [{"from": "a", "to": "b"}],
            "metadata": {"priority": "high"},
        }
        wf = Workflow(
            name="json-test",
            status=WorkflowStatus.PENDING,
            dag_definition=dag,
        )
        session.add(wf)
        session.flush()

        result = session.query(Workflow).filter_by(name="json-test").one()
        assert result.dag_definition == dag

    def test_workflow_all_statuses(self, session):
        """All WorkflowStatus values must be accepted."""
        for status in WorkflowStatus:
            wf = Workflow(
                name=f"status-{status.value}",
                status=status,
                dag_definition={},
            )
            session.add(wf)
        session.flush()
        count = session.query(Workflow).count()
        assert count == len(WorkflowStatus)


# ===========================================================================
# TaskNode Model
# ===========================================================================


class TestTaskNodeCreation:
    """TaskNode can be created with all fields."""

    def test_create_task_node_minimal(self, session, sample_workflow):
        """TaskNode with only required fields."""
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="simple-task",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="analyze_data",
            arguments={},
        )
        session.add(node)
        session.flush()

        assert node.id is not None
        assert isinstance(node.id, uuid.UUID)
        assert node.workflow_id == sample_workflow.id
        assert node.name == "simple-task"
        assert node.task_type == "llm_call"
        assert node.status == TaskNodeStatus.PENDING
        assert node.command == "analyze_data"
        assert node.arguments == {}

    def test_create_task_node_with_all_fields(self, session, sample_workflow):
        """TaskNode with every field populated."""
        prev_id = str(uuid.uuid4())
        next_id = str(uuid.uuid4())
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="full-task",
            task_type="tool_execution",
            status=TaskNodeStatus.RUNNING,
            command="execute_tool",
            arguments={"tool": "bash", "cmd": "ls -la"},
            previous_node_ids=[prev_id],
            next_node_ids=[next_id],
            outputs="Tool executed successfully",
            compensation_command="cleanup_tool",
            compensation_arguments={"tool": "bash", "cmd": "rm -rf /tmp/out"},
            retry_count=1,
            max_retries=5,
        )
        session.add(node)
        session.flush()

        assert node.workflow_id == sample_workflow.id
        assert node.task_type == "tool_execution"
        assert node.status == TaskNodeStatus.RUNNING
        assert node.arguments == {"tool": "bash", "cmd": "ls -la"}
        assert prev_id in node.previous_node_ids
        assert next_id in node.next_node_ids
        assert node.outputs == "Tool executed successfully"
        assert node.compensation_command == "cleanup_tool"
        assert node.compensation_arguments == {"tool": "bash", "cmd": "rm -rf /tmp/out"}
        assert node.retry_count == 1
        assert node.max_retries == 5


class TestTaskNodeDefaults:
    """Default values for TaskNode fields."""

    def test_default_retry_count_is_zero(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="defaults-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="do_something",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.retry_count == 0

    def test_default_max_retries_is_three(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="max-retries-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="do_something",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.max_retries == 3

    def test_default_timestamps(self, session, sample_workflow):
        """created_at and updated_at must be auto-set."""
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="ts-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="do_something",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.created_at is not None
        assert node.updated_at is not None
        assert isinstance(node.created_at, datetime)
        assert isinstance(node.updated_at, datetime)

    def test_default_outputs_is_none(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="outputs-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="do_something",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.outputs is None

    def test_default_compensation_command_is_none(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="comp-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="do_something",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.compensation_command is None

    def test_default_compensation_arguments_is_none(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="comp-args-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="do_something",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.compensation_arguments is None

    def test_default_previous_node_ids_empty(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="adj-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="do_something",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.previous_node_ids is not None
        assert node.previous_node_ids == []

    def test_default_next_node_ids_empty(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="adj-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="do_something",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.next_node_ids is not None
        assert node.next_node_ids == []


class TestTaskNodeStatusEnum:
    """Status enum validation for TaskNode."""

    def test_pending_status(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="s-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.status == TaskNodeStatus.PENDING
        assert node.status.value == "pending"

    def test_running_status(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="s-test",
            task_type="llm_call",
            status=TaskNodeStatus.RUNNING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.status == TaskNodeStatus.RUNNING
        assert node.status.value == "running"

    def test_completed_status(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="s-test",
            task_type="llm_call",
            status=TaskNodeStatus.COMPLETED,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.status == TaskNodeStatus.COMPLETED
        assert node.status.value == "completed"

    def test_failed_status(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="s-test",
            task_type="llm_call",
            status=TaskNodeStatus.FAILED,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert node.status == TaskNodeStatus.FAILED
        assert node.status.value == "failed"

    def test_all_statuses_iterable(self):
        """There must be exactly 4 statuses."""
        assert len(TaskNodeStatus) == 4
        expected = {"pending", "running", "completed", "failed"}
        actual = {s.value for s in TaskNodeStatus}
        assert actual == expected


class TestTaskNodeNullable:
    """Nullable fields on TaskNode."""

    def test_outputs_nullable(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="null-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
            outputs=None,
        )
        session.add(node)
        session.flush()
        assert node.outputs is None

    def test_compensation_command_nullable(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="null-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
            compensation_command=None,
        )
        session.add(node)
        session.flush()
        assert node.compensation_command is None

    def test_compensation_arguments_nullable(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="null-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
            compensation_arguments=None,
        )
        session.add(node)
        session.flush()
        assert node.compensation_arguments is None


class TestTaskNodeJsonFields:
    """JSON fields store and retrieve structured data."""

    def test_arguments_json_dict(self, session, sample_workflow):
        args = {"prompt": "Hello", "temperature": 0.7, "max_tokens": 1024}
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="json-args",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="llm",
            arguments=args,
        )
        session.add(node)
        session.flush()

        result = session.query(TaskNode).filter_by(name="json-args").one()
        assert result.arguments == args
        assert result.arguments["temperature"] == 0.7

    def test_arguments_json_nested(self, session, sample_workflow):
        args = {
            "tool": "bash",
            "env": {"HOME": "/tmp", "PATH": "/usr/bin"},
            "flags": ["-a", "-l"],
        }
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="nested-args",
            task_type="tool_execution",
            status=TaskNodeStatus.PENDING,
            command="run",
            arguments=args,
        )
        session.add(node)
        session.flush()

        result = session.query(TaskNode).filter_by(name="nested-args").one()
        assert result.arguments["env"]["HOME"] == "/tmp"
        assert result.arguments["flags"] == ["-a", "-l"]

    def test_previous_node_ids_json_list(self, session, sample_workflow):
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="prev-ids",
            task_type="fan_out",
            status=TaskNodeStatus.PENDING,
            command="fan_out",
            arguments={},
            previous_node_ids=ids,
        )
        session.add(node)
        session.flush()

        result = session.query(TaskNode).filter_by(name="prev-ids").one()
        assert result.previous_node_ids == ids

    def test_next_node_ids_json_list(self, session, sample_workflow):
        ids = [str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())]
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="next-ids",
            task_type="fan_out",
            status=TaskNodeStatus.PENDING,
            command="fan_out",
            arguments={},
            next_node_ids=ids,
        )
        session.add(node)
        session.flush()

        result = session.query(TaskNode).filter_by(name="next-ids").one()
        assert result.next_node_ids == ids
        assert len(result.next_node_ids) == 3


class TestTaskNodeAdjacencyOperations:
    """Adjacency list operations for DAG traversal."""

    def test_add_to_previous_node_ids(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="adj-op",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
            previous_node_ids=[],
        )
        session.add(node)
        session.flush()

        new_id = str(uuid.uuid4())
        node.previous_node_ids = node.previous_node_ids + [new_id]
        session.flush()

        result = session.query(TaskNode).filter_by(name="adj-op").one()
        assert new_id in result.previous_node_ids

    def test_add_to_next_node_ids(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="adj-op2",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
            next_node_ids=[],
        )
        session.add(node)
        session.flush()

        new_id = str(uuid.uuid4())
        node.next_node_ids = node.next_node_ids + [new_id]
        session.flush()

        result = session.query(TaskNode).filter_by(name="adj-op2").one()
        assert new_id in result.next_node_ids

    def test_multiple_node_dag_chain(self, session, sample_workflow):
        """Simulate a 3-node chain: A -> B -> C."""
        node_a = TaskNode(
            workflow_id=sample_workflow.id,
            name="node-a",
            task_type="llm_call",
            status=TaskNodeStatus.COMPLETED,
            command="step_a",
            arguments={"input": "data"},
            previous_node_ids=[],
            next_node_ids=[],
        )
        session.add(node_a)
        session.flush()

        node_b = TaskNode(
            workflow_id=sample_workflow.id,
            name="node-b",
            task_type="tool_execution",
            status=TaskNodeStatus.RUNNING,
            command="step_b",
            arguments={},
            previous_node_ids=[str(node_a.id)],
            next_node_ids=[],
        )
        session.add(node_b)
        session.flush()

        # Link A -> B
        node_a.next_node_ids = [str(node_b.id)]
        session.flush()

        node_c = TaskNode(
            workflow_id=sample_workflow.id,
            name="node-c",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="step_c",
            arguments={},
            previous_node_ids=[str(node_b.id)],
            next_node_ids=[],
        )
        session.add(node_c)
        session.flush()

        # Link B -> C
        node_b.next_node_ids = [str(node_c.id)]
        session.flush()

        # Verify the chain
        a = session.query(TaskNode).filter_by(name="node-a").one()
        b = session.query(TaskNode).filter_by(name="node-b").one()
        c = session.query(TaskNode).filter_by(name="node-c").one()

        assert str(b.id) in a.next_node_ids
        assert str(a.id) in b.previous_node_ids
        assert str(c.id) in b.next_node_ids
        assert str(b.id) in c.previous_node_ids


# ===========================================================================
# TaskEvent Model
# ===========================================================================


class TestTaskEventCreation:
    """TaskEvent can be created with all fields."""

    def test_create_task_event_minimal(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="event-node",
            task_type="llm_call",
            status=TaskNodeStatus.RUNNING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.NODE_STARTED,
        )
        session.add(event)
        session.flush()

        assert event.id is not None
        assert isinstance(event.id, uuid.UUID)
        assert event.task_node_id == node.id
        assert event.workflow_id == sample_workflow.id
        assert event.event_type == TaskEventType.NODE_STARTED
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)

    def test_create_task_event_with_data(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="event-node-2",
            task_type="tool_execution",
            status=TaskNodeStatus.FAILED,
            command="failing_cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event_data = {
            "error": "ConnectionTimeout",
            "message": "Failed to connect to API after 30s",
            "retry_attempt": 2,
        }
        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.NODE_FAILED,
            event_data=event_data,
        )
        session.add(event)
        session.flush()

        assert event.event_data == event_data
        assert event.event_data["error"] == "ConnectionTimeout"


class TestTaskEventDefaults:
    """Default values for TaskEvent fields."""

    def test_event_data_nullable(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="evt-defaults",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.NODE_STARTED,
        )
        session.add(event)
        session.flush()
        assert event.event_data is None

    def test_timestamp_auto_set(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="ts-event",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.NODE_STARTED,
        )
        session.add(event)
        session.flush()
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)


class TestTaskEventTypeEnum:
    """TaskEventType enum validation."""

    def test_all_event_types(self):
        expected = {
            "node_started",
            "node_completed",
            "node_failed",
            "compensation_triggered",
            "compensation_completed",
            "compensation_failed",
            "state_checkpoint",
            "workflow_submitted",
            "workflow_completed",
            "observation_captured",
            "plan_generated",
            "evaluation_result",
            "precondition_checked",
            "cycle_started",
            "checkpoint",
        }
        actual = {e.value for e in TaskEventType}
        assert actual == expected
        assert len(TaskEventType) == 15

    def test_task_event_type_has_new_opa_values(self):
        """New OPA loop event types must be present in TaskEventType."""
        opa_types = {
            "workflow_submitted",
            "workflow_completed",
            "observation_captured",
            "plan_generated",
            "evaluation_result",
            "precondition_checked",
            "cycle_started",
            "checkpoint",
        }
        actual = {e.value for e in TaskEventType}
        assert opa_types.issubset(actual)

    def test_event_type_values(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="etype-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        for etype in TaskEventType:
            event = TaskEvent(
                task_node_id=node.id,
                workflow_id=sample_workflow.id,
                event_type=etype,
            )
            session.add(event)
        session.flush()

        events = session.query(TaskEvent).filter_by(task_node_id=node.id).all()
        assert len(events) == len(TaskEventType)


# ===========================================================================
# WorkflowEvent Model
# ===========================================================================


class TestWorkflowEventCreation:
    """WorkflowEvent can be created with all fields."""

    def test_create_workflow_event_minimal(self, session, sample_workflow):
        event = WorkflowEvent(
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.WORKFLOW_SUBMITTED,
            sequence_number=1,
        )
        session.add(event)
        session.flush()

        assert event.id is not None
        assert isinstance(event.id, uuid.UUID)
        assert event.workflow_id == sample_workflow.id
        assert event.task_node_id is None
        assert event.event_type == TaskEventType.WORKFLOW_SUBMITTED
        assert event.sequence_number == 1
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)

    def test_create_workflow_event_with_task_node(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="event-node",
            task_type="llm_call",
            status=TaskNodeStatus.RUNNING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event = WorkflowEvent(
            workflow_id=sample_workflow.id,
            task_node_id=node.id,
            event_type=TaskEventType.PLAN_GENERATED,
            sequence_number=2,
            event_data={"plan": ["step1", "step2"]},
        )
        session.add(event)
        session.flush()

        assert event.task_node_id == node.id
        assert event.event_data == {"plan": ["step1", "step2"]}

    def test_workflow_event_sequence_number(self, session, sample_workflow):
        """Sequence numbers must be stored and ordered correctly."""
        for i in range(1, 4):
            event = WorkflowEvent(
                workflow_id=sample_workflow.id,
                event_type=TaskEventType.CYCLE_STARTED,
                sequence_number=i,
            )
            session.add(event)
        session.flush()

        events = (
            session.query(WorkflowEvent)
            .filter_by(workflow_id=sample_workflow.id)
            .order_by(WorkflowEvent.sequence_number)
            .all()
        )
        assert len(events) == 3
        assert events[0].sequence_number == 1
        assert events[1].sequence_number == 2
        assert events[2].sequence_number == 3

    def test_workflow_event_event_data_nullable(self, session, sample_workflow):
        event = WorkflowEvent(
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.WORKFLOW_COMPLETED,
            sequence_number=1,
        )
        session.add(event)
        session.flush()
        assert event.event_data is None

    def test_workflow_event_timestamp_auto_set(self, session, sample_workflow):
        event = WorkflowEvent(
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.CHECKPOINT,
            sequence_number=1,
        )
        session.add(event)
        session.flush()
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)


class TestWorkflowEventRelationship:
    """WorkflowEvent relationship to Workflow."""

    def test_workflow_event_relationship_to_workflow(self, session, sample_workflow):
        event = WorkflowEvent(
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.WORKFLOW_SUBMITTED,
            sequence_number=1,
        )
        session.add(event)
        session.flush()

        result = session.query(WorkflowEvent).first()
        assert result.workflow_id == sample_workflow.id
        assert result.workflow == sample_workflow

    def test_workflow_has_workflow_events(self, session, sample_workflow):
        """Workflow.workflow_events relationship returns WorkflowEvent rows."""
        for i in range(1, 3):
            event = WorkflowEvent(
                workflow_id=sample_workflow.id,
                event_type=TaskEventType.OBSERVATION_CAPTURED,
                sequence_number=i,
            )
            session.add(event)
        session.flush()

        assert len(sample_workflow.workflow_events) == 2
        assert all(
            isinstance(e, WorkflowEvent) for e in sample_workflow.workflow_events
        )

    def test_multiple_workflow_events_per_workflow(self, session, sample_workflow):
        for etype in [
            TaskEventType.WORKFLOW_SUBMITTED,
            TaskEventType.PLAN_GENERATED,
            TaskEventType.WORKFLOW_COMPLETED,
        ]:
            event = WorkflowEvent(
                workflow_id=sample_workflow.id,
                event_type=etype,
                sequence_number=1,
            )
            session.add(event)
        session.flush()

        events = (
            session.query(WorkflowEvent)
            .filter_by(workflow_id=sample_workflow.id)
            .all()
        )
        assert len(events) == 3


# ===========================================================================
# TaskEvent sequence_number
# ===========================================================================


class TestTaskEventSequenceNumber:
    """Optional sequence_number on TaskEvent."""

    def test_task_event_sequence_number_default_none(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="seq-node",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.NODE_STARTED,
        )
        session.add(event)
        session.flush()
        assert event.sequence_number is None

    def test_task_event_sequence_number_set(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="seq-node-2",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.NODE_STARTED,
            sequence_number=42,
        )
        session.add(event)
        session.flush()
        assert event.sequence_number == 42


class TestTaskEventJsonFields:
    """JSON event_data field."""

    def test_event_data_complex_payload(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="json-event",
            task_type="llm_call",
            status=TaskNodeStatus.COMPLETED,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        payload = {
            "state": {
                "outputs": {"result": "success", "tokens_used": 150},
                "checkpoint_id": str(uuid.uuid4()),
            },
            "metadata": {"source": "engine", "version": "0.1.0"},
        }
        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.STATE_CHECKPOINT,
            event_data=payload,
        )
        session.add(event)
        session.flush()

        result = session.query(TaskEvent).filter_by(
            task_node_id=node.id,
            event_type=TaskEventType.STATE_CHECKPOINT,
        ).one()
        assert result.event_data["state"]["outputs"]["tokens_used"] == 150


# ===========================================================================
# Relationships
# ===========================================================================


class TestRelationships:
    """Foreign key relationships between models."""

    def test_task_node_references_workflow(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="rel-test",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        result = session.query(TaskNode).filter_by(name="rel-test").one()
        assert result.workflow_id == sample_workflow.id

    def test_task_event_references_task_node(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="rel-node",
            task_type="llm_call",
            status=TaskNodeStatus.RUNNING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.NODE_STARTED,
        )
        session.add(event)
        session.flush()

        result = session.query(TaskEvent).first()
        assert result.task_node_id == node.id

    def test_task_event_references_workflow(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="rel-node-2",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.NODE_STARTED,
        )
        session.add(event)
        session.flush()

        result = session.query(TaskEvent).first()
        assert result.workflow_id == sample_workflow.id

    def test_multiple_events_per_node(self, session, sample_workflow):
        """A single TaskNode can have many TaskEvents (event sourcing)."""
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="multi-event",
            task_type="llm_call",
            status=TaskNodeStatus.COMPLETED,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        for etype in [
            TaskEventType.NODE_STARTED,
            TaskEventType.STATE_CHECKPOINT,
            TaskEventType.NODE_COMPLETED,
        ]:
            event = TaskEvent(
                task_node_id=node.id,
                workflow_id=sample_workflow.id,
                event_type=etype,
            )
            session.add(event)
        session.flush()

        events = (
            session.query(TaskEvent)
            .filter_by(task_node_id=node.id)
            .order_by(TaskEvent.timestamp)
            .all()
        )
        assert len(events) == 3
        assert events[0].event_type == TaskEventType.NODE_STARTED

    def test_multiple_nodes_per_workflow(self, session, sample_workflow):
        """A single Workflow can have many TaskNodes."""
        for i in range(5):
            node = TaskNode(
                workflow_id=sample_workflow.id,
                name=f"node-{i}",
                task_type="llm_call",
                status=TaskNodeStatus.PENDING,
                command=f"cmd_{i}",
                arguments={"index": i},
            )
            session.add(node)
        session.flush()

        nodes = (
            session.query(TaskNode)
            .filter_by(workflow_id=sample_workflow.id)
            .all()
        )
        assert len(nodes) == 5


# ===========================================================================
# UUID Primary Keys
# ===========================================================================


class TestUUIDPrimaryKeys:
    """UUID primary keys are auto-generated."""

    def test_workflow_id_auto_generated(self, session):
        wf = Workflow(
            name="uuid-wf",
            status=WorkflowStatus.PENDING,
            dag_definition={},
        )
        session.add(wf)
        session.flush()
        assert isinstance(wf.id, uuid.UUID)
        assert wf.id != uuid.UUID(int=0)

    def test_task_node_id_auto_generated(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="uuid-node",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()
        assert isinstance(node.id, uuid.UUID)
        assert node.id != uuid.UUID(int=0)

    def test_task_event_id_auto_generated(self, session, sample_workflow):
        node = TaskNode(
            workflow_id=sample_workflow.id,
            name="uuid-event-node",
            task_type="llm_call",
            status=TaskNodeStatus.PENDING,
            command="cmd",
            arguments={},
        )
        session.add(node)
        session.flush()

        event = TaskEvent(
            task_node_id=node.id,
            workflow_id=sample_workflow.id,
            event_type=TaskEventType.NODE_STARTED,
        )
        session.add(event)
        session.flush()
        assert isinstance(event.id, uuid.UUID)
        assert event.id != uuid.UUID(int=0)

    def test_uuids_are_unique(self, session, sample_workflow):
        """Multiple rows get unique UUIDs."""
        ids = set()
        for i in range(10):
            node = TaskNode(
                workflow_id=sample_workflow.id,
                name=f"unique-{i}",
                task_type="llm_call",
                status=TaskNodeStatus.PENDING,
                command="cmd",
                arguments={},
            )
            session.add(node)
            session.flush()
            ids.add(node.id)
        assert len(ids) == 10


# ===========================================================================
# Enum Definitions
# ===========================================================================


class TestEnumDefinitions:
    """Verify enum types have correct members."""

    def test_task_node_status_values(self):
        assert TaskNodeStatus.PENDING.value == "pending"
        assert TaskNodeStatus.RUNNING.value == "running"
        assert TaskNodeStatus.COMPLETED.value == "completed"
        assert TaskNodeStatus.FAILED.value == "failed"

    def test_workflow_status_values(self):
        assert WorkflowStatus.PENDING.value == "pending"
        assert WorkflowStatus.RUNNING.value == "running"
        assert WorkflowStatus.COMPLETED.value == "completed"
        assert WorkflowStatus.FAILED.value == "failed"

    def test_task_event_type_values(self):
        assert TaskEventType.NODE_STARTED.value == "node_started"
        assert TaskEventType.NODE_COMPLETED.value == "node_completed"
        assert TaskEventType.NODE_FAILED.value == "node_failed"
        assert TaskEventType.COMPENSATION_TRIGGERED.value == "compensation_triggered"
        assert TaskEventType.STATE_CHECKPOINT.value == "state_checkpoint"
        assert TaskEventType.WORKFLOW_SUBMITTED.value == "workflow_submitted"
        assert TaskEventType.WORKFLOW_COMPLETED.value == "workflow_completed"
        assert TaskEventType.OBSERVATION_CAPTURED.value == "observation_captured"
        assert TaskEventType.PLAN_GENERATED.value == "plan_generated"
        assert TaskEventType.EVALUATION_RESULT.value == "evaluation_result"
        assert TaskEventType.PRECONDITION_CHECKED.value == "precondition_checked"
        assert TaskEventType.CYCLE_STARTED.value == "cycle_started"
        assert TaskEventType.CHECKPOINT.value == "checkpoint"
