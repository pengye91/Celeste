"""
Tests for the database session manager in celeste_dag.database.db.

Follows strict TDD: these tests are written BEFORE the implementation.
Uses SQLite async engine for testability.

Tests cover:
- Engine creation with SQLite (in-memory and file-based)
- Session factory creates AsyncSession instances
- get_session() context manager yields usable sessions
- init_db() creates all tables
- close_db() disposes engine
- Auto-switching between SQLite and PostgreSQL URL patterns
- Session can perform CRUD operations (insert + query via ORM)
- Proper cleanup on context manager exit (commit/rollback behavior)
"""

import os
import tempfile
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from celeste_dag.database.models import (
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
# Helpers
# ---------------------------------------------------------------------------

SQLITE_MEMORY_URL = "sqlite+aiosqlite://"
SQLITE_FILE_URL_TEMPLATE = "sqlite+aiosqlite:///{}"
POSTGRES_URL = "postgresql+asyncpg://user:pass@localhost:5432/testdb"


def _make_file_url() -> tuple[str, str]:
    """Create a temporary file-based SQLite URL and return (url, dir)."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    url = SQLITE_FILE_URL_TEMPLATE.format(db_path)
    return url, tmpdir


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_db_module():
    """Reset module-level state between tests so engines don't leak."""
    import celeste_dag.database.db as db_mod

    # Reset module-level engine/session variables before each test
    db_mod._engine = None
    db_mod._async_session_factory = None
    yield
    # Clean up after test
    if db_mod._engine is not None:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.run_until_complete(db_mod._engine.dispose())
        except Exception:
            pass
    db_mod._engine = None
    db_mod._async_session_factory = None


@pytest.fixture()
def sqlite_memory_settings():
    """Return an EngineSettings-like object with SQLite in-memory URL."""
    from celeste_dag.config.settings import EngineSettings

    return EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL)


@pytest.fixture()
def sqlite_file_settings():
    """Return an EngineSettings-like object with SQLite file-based URL."""
    from celeste_dag.config.settings import EngineSettings

    url, _ = _make_file_url()
    return EngineSettings(DATABASE_URL=url)


# ---------------------------------------------------------------------------
# Engine creation
# ---------------------------------------------------------------------------


class TestEngineCreation:
    """Engine is created correctly from settings.DATABASE_URL."""

    async def test_create_engine_sqlite_memory(self, sqlite_memory_settings):
        from celeste_dag.database.db import create_engine_from_settings

        engine = create_engine_from_settings(sqlite_memory_settings)
        assert engine is not None
        assert "sqlite" in str(engine.url)
        await engine.dispose()

    async def test_create_engine_sqlite_file(self, sqlite_file_settings):
        from celeste_dag.database.db import create_engine_from_settings

        engine = create_engine_from_settings(sqlite_file_settings)
        assert engine is not None
        assert "sqlite" in str(engine.url)
        await engine.dispose()

    async def test_create_engine_postgres_url(self):
        """Engine creation with postgres URL should not fail (no actual connection)."""
        from celeste_dag.config.settings import EngineSettings
        from celeste_dag.database.db import create_engine_from_settings

        settings = EngineSettings(DATABASE_URL=POSTGRES_URL)
        engine = create_engine_from_settings(settings)
        assert engine is not None
        assert "postgresql" in str(engine.url) or "postgres" in str(engine.url)
        await engine.dispose()

    async def test_engine_url_uses_secret_value(self, sqlite_memory_settings):
        """Ensure .get_secret_value() is used, not the raw SecretStr."""
        from celeste_dag.database.db import create_engine_from_settings

        engine = create_engine_from_settings(sqlite_memory_settings)
        # The engine URL should be a string, not a SecretStr representation
        assert "SecretStr" not in str(engine.url)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Auto-switching between SQLite and PostgreSQL
# ---------------------------------------------------------------------------


class TestAutoSwitching:
    """Engine auto-detects URL scheme and adjusts connect args."""

    async def test_sqlite_gets_connect_args(self):
        """SQLite engine should set check_same_thread=False by default."""
        from celeste_dag.config.settings import EngineSettings
        from celeste_dag.database.db import create_engine_from_settings

        settings = EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL)
        engine = create_engine_from_settings(settings)
        # SQLAlchemy stores connect_args in the dialect
        assert engine.dialect.name == "sqlite"
        await engine.dispose()

    async def test_postgres_no_sqlite_connect_args(self):
        """PostgreSQL engine should NOT have SQLite-specific connect_args."""
        from celeste_dag.config.settings import EngineSettings
        from celeste_dag.database.db import create_engine_from_settings

        settings = EngineSettings(DATABASE_URL=POSTGRES_URL)
        engine = create_engine_from_settings(settings)
        assert engine.dialect.name == "postgresql"
        await engine.dispose()

    async def test_in_memory_url_detected(self):
        """In-memory SQLite URL (empty path) is handled correctly."""
        from celeste_dag.config.settings import EngineSettings
        from celeste_dag.database.db import create_engine_from_settings

        settings = EngineSettings(DATABASE_URL="sqlite+aiosqlite://")
        engine = create_engine_from_settings(settings)
        assert engine.dialect.name == "sqlite"
        await engine.dispose()


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------


class TestSessionFactory:
    """async_sessionmaker creates AsyncSession instances."""

    async def test_get_session_factory(self):
        from celeste_dag.database.db import get_session_factory

        factory = get_session_factory("sqlite+aiosqlite://")
        assert factory is not None

        async with factory() as session:
            assert isinstance(session, AsyncSession)

    async def test_factory_creates_independent_sessions(self):
        """Each call to the factory should produce a new session."""
        from celeste_dag.database.db import get_session_factory

        factory = get_session_factory("sqlite+aiosqlite://")
        async with factory() as s1, factory() as s2:
            assert s1 is not s2


# ---------------------------------------------------------------------------
# get_session context manager
# ---------------------------------------------------------------------------


class TestGetSession:
    """get_session() yields a usable AsyncSession."""

    async def test_get_session_yields_async_session(self):
        from celeste_dag.database.db import get_session, init_db

        await init_db("sqlite+aiosqlite://")
        async with get_session() as session:
            assert isinstance(session, AsyncSession)

    async def test_get_session_can_execute_raw_sql(self):
        from celeste_dag.database.db import get_session, init_db

        await init_db("sqlite+aiosqlite://")
        async with get_session() as session:
            result = await session.execute(text("SELECT 1"))
            row = result.scalar()
            assert row == 1

    async def test_get_session_without_init_raises(self):
        """Calling get_session() before init_db() should raise RuntimeError."""
        from celeste_dag.database.db import get_session

        with pytest.raises(RuntimeError, match="not initialised"):
            async with get_session() as session:
                pass


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


class TestInitDb:
    """init_db() creates all tables in the database."""

    async def test_init_db_creates_all_tables(self):
        from celeste_dag.database.db import init_db

        engine = await init_db("sqlite+aiosqlite://")
        assert engine is not None

        # Use sync inspection via run_sync to verify tables
        def _inspect(connection):
            insp = inspect(connection)
            return insp.get_table_names()

        async with engine.connect() as conn:
            tables = await conn.run_sync(_inspect)

        assert "workflows" in tables
        assert "task_nodes" in tables
        assert "task_events" in tables
        assert "workflow_events" in tables
        await engine.dispose()

    async def test_init_db_idempotent(self):
        """Calling init_db() twice should not raise."""
        from celeste_dag.database.db import init_db

        engine1 = await init_db("sqlite+aiosqlite://")
        engine2 = await init_db("sqlite+aiosqlite://")
        # Second call should return the same engine (module-level singleton)
        assert engine1 is engine2
        await engine1.dispose()

    async def test_init_db_with_settings(self):
        """init_db() accepts an EngineSettings instance."""
        from celeste_dag.config.settings import EngineSettings
        from celeste_dag.database.db import init_db

        settings = EngineSettings(DATABASE_URL=SQLITE_MEMORY_URL)
        engine = await init_db(settings=settings)
        assert engine is not None
        assert engine.dialect.name == "sqlite"
        await engine.dispose()

    async def test_init_db_without_args_raises(self):
        """init_db() with neither url nor settings should raise ValueError."""
        from celeste_dag.database.db import init_db

        with pytest.raises(ValueError, match="Either url or settings"):
            await init_db()


# ---------------------------------------------------------------------------
# close_db
# ---------------------------------------------------------------------------


class TestCloseDb:
    """close_db() disposes of the engine."""

    async def test_close_db_disposes_engine(self):
        from celeste_dag.database.db import close_db, init_db

        engine = await init_db("sqlite+aiosqlite://")
        assert engine is not None
        await close_db()

        # After close, the module-level engine should be None
        import celeste_dag.database.db as db_mod

        assert db_mod._engine is None

    async def test_close_db_without_init(self):
        """Calling close_db() before init_db() should not raise."""
        from celeste_dag.database.db import close_db

        await close_db()  # should be a no-op


# ---------------------------------------------------------------------------
# CRUD operations through session (using file-based SQLite for persistence)
# ---------------------------------------------------------------------------


class TestCrudOperations:
    """Sessions can perform insert and query operations."""

    async def test_insert_and_query_workflow(self):
        from celeste_dag.database.db import get_session, init_db

        url, _ = _make_file_url()
        await init_db(url)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="test-crud-workflow",
                status=WorkflowStatus.PENDING,
                dag_definition={"steps": ["a", "b"]},
            )
            session.add(wf)
            await session.commit()

        async with get_session() as session:
            stmt = select(Workflow).where(Workflow.id == wf_id)
            result = await session.execute(stmt)
            fetched = result.scalar_one()
            assert fetched.name == "test-crud-workflow"
            assert fetched.status == WorkflowStatus.PENDING
            assert fetched.dag_definition == {"steps": ["a", "b"]}

    async def test_insert_and_query_task_node(self):
        from celeste_dag.database.db import get_session, init_db

        url, _ = _make_file_url()
        await init_db(url)

        wf_id = uuid.uuid4()
        node_id = uuid.uuid4()

        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="node-crud-wf",
                status=WorkflowStatus.RUNNING,
                dag_definition={},
            )
            session.add(wf)
            await session.commit()

        async with get_session() as session:
            node = TaskNode(
                id=node_id,
                workflow_id=wf_id,
                name="crud-node",
                task_type="llm_call",
                status=TaskNodeStatus.PENDING,
                command="do_stuff",
                arguments={"key": "value"},
            )
            session.add(node)
            await session.commit()

        async with get_session() as session:
            stmt = select(TaskNode).where(TaskNode.id == node_id)
            result = await session.execute(stmt)
            fetched = result.scalar_one()
            assert fetched.command == "do_stuff"
            assert fetched.arguments == {"key": "value"}

    async def test_insert_and_query_task_event(self):
        from celeste_dag.database.db import get_session, init_db

        url, _ = _make_file_url()
        await init_db(url)

        wf_id = uuid.uuid4()
        node_id = uuid.uuid4()
        event_id = uuid.uuid4()

        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="event-crud-wf",
                status=WorkflowStatus.RUNNING,
                dag_definition={},
            )
            session.add(wf)
            await session.commit()

        async with get_session() as session:
            node = TaskNode(
                id=node_id,
                workflow_id=wf_id,
                name="event-node",
                task_type="tool_execution",
                status=TaskNodeStatus.RUNNING,
                command="run_tool",
                arguments={},
            )
            session.add(node)
            await session.commit()

        async with get_session() as session:
            event = TaskEvent(
                id=event_id,
                task_node_id=node_id,
                workflow_id=wf_id,
                event_type=TaskEventType.NODE_STARTED,
            )
            session.add(event)
            await session.commit()

        async with get_session() as session:
            stmt = select(TaskEvent).where(TaskEvent.id == event_id)
            result = await session.execute(stmt)
            fetched = result.scalar_one()
            assert fetched.event_type == TaskEventType.NODE_STARTED

    async def test_insert_and_query_workflow_event(self):
        from celeste_dag.database.db import get_session, init_db

        url, _ = _make_file_url()
        await init_db(url)

        wf_id = uuid.uuid4()
        event_id = uuid.uuid4()

        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="workflow-event-crud-wf",
                status=WorkflowStatus.RUNNING,
                dag_definition={},
            )
            session.add(wf)
            await session.commit()

        async with get_session() as session:
            event = WorkflowEvent(
                id=event_id,
                workflow_id=wf_id,
                event_type=TaskEventType.WORKFLOW_SUBMITTED,
                sequence_number=1,
                event_data={"source": "api"},
            )
            session.add(event)
            await session.commit()

        async with get_session() as session:
            stmt = select(WorkflowEvent).where(WorkflowEvent.id == event_id)
            result = await session.execute(stmt)
            fetched = result.scalar_one()
            assert fetched.event_type == TaskEventType.WORKFLOW_SUBMITTED
            assert fetched.sequence_number == 1
            assert fetched.event_data == {"source": "api"}

    async def test_orm_query_workflow(self):
        """Full ORM-style select query through AsyncSession."""
        from celeste_dag.database.db import get_session, init_db

        url, _ = _make_file_url()
        await init_db(url)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="orm-query-test",
                status=WorkflowStatus.COMPLETED,
                dag_definition={"nodes": 3},
            )
            session.add(wf)
            await session.commit()

        async with get_session() as session:
            stmt = select(Workflow).where(Workflow.id == wf_id)
            result = await session.execute(stmt)
            fetched_wf = result.scalar_one()
            assert fetched_wf.name == "orm-query-test"
            assert fetched_wf.status == WorkflowStatus.COMPLETED
            assert fetched_wf.dag_definition == {"nodes": 3}


# ---------------------------------------------------------------------------
# Session cleanup / commit / rollback
# ---------------------------------------------------------------------------


class TestSessionCleanup:
    """Session context manager handles commit/rollback properly."""

    async def test_commit_on_clean_exit(self):
        """Data should be committed when context manager exits cleanly."""
        from celeste_dag.database.db import get_session, init_db

        url, _ = _make_file_url()
        await init_db(url)

        wf_id = uuid.uuid4()
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="commit-test",
                status=WorkflowStatus.PENDING,
                dag_definition={},
            )
            session.add(wf)
            # No explicit commit; the context manager should commit

        # Verify data persisted in a new session
        async with get_session() as session:
            stmt = select(Workflow).where(Workflow.id == wf_id)
            result = await session.execute(stmt)
            fetched = result.scalar_one_or_none()
            assert fetched is not None
            assert fetched.name == "commit-test"

    async def test_rollback_on_exception(self):
        """Data should be rolled back when an exception occurs in the context."""
        from celeste_dag.database.db import get_session, init_db

        url, _ = _make_file_url()
        await init_db(url)

        wf_id = uuid.uuid4()
        with pytest.raises(RuntimeError, match="intentional"):
            async with get_session() as session:
                wf = Workflow(
                    id=wf_id,
                    name="rollback-test",
                    status=WorkflowStatus.PENDING,
                    dag_definition={},
                )
                session.add(wf)
                raise RuntimeError("intentional error")

        # Verify data was NOT persisted
        async with get_session() as session:
            stmt = select(Workflow).where(Workflow.id == wf_id)
            result = await session.execute(stmt)
            assert result.scalar_one_or_none() is None

    async def test_session_is_usable_within_context(self):
        """Session is usable and active within the context manager."""
        from celeste_dag.database.db import get_session, init_db

        await init_db("sqlite+aiosqlite://")
        async with get_session() as session:
            # Session should be active and usable
            assert session.is_active
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

    async def test_multiple_sequential_sessions(self):
        """Multiple sequential get_session() calls work correctly."""
        from celeste_dag.database.db import get_session, init_db

        url, _ = _make_file_url()
        await init_db(url)

        wf_id = uuid.uuid4()

        # Session 1: insert
        async with get_session() as session:
            wf = Workflow(
                id=wf_id,
                name="seq-test",
                status=WorkflowStatus.PENDING,
                dag_definition={},
            )
            session.add(wf)

        # Session 2: update status
        async with get_session() as session:
            stmt = select(Workflow).where(Workflow.id == wf_id)
            result = await session.execute(stmt)
            wf = result.scalar_one()
            wf.status = WorkflowStatus.RUNNING

        # Session 3: verify
        async with get_session() as session:
            stmt = select(Workflow).where(Workflow.id == wf_id)
            result = await session.execute(stmt)
            wf = result.scalar_one()
            assert wf.name == "seq-test"
            assert wf.status == WorkflowStatus.RUNNING
