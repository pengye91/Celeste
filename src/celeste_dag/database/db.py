"""
Database session manager for the Celeste-DAG engine.

Provides:
- create_engine_from_settings(): Build an async SQLAlchemy engine from EngineSettings.
- get_session_factory(): Return an async_sessionmaker for creating AsyncSession instances.
- get_session(): Async context manager that yields an AsyncSession with auto-commit/rollback.
- init_db(): Create all tables (idempotent).
- close_db(): Dispose of the engine and clean up module state.

Auto-switches between SQLite (aiosqlite) and PostgreSQL (asyncpg) based on the
DATABASE_URL scheme. Uses settings.DATABASE_URL (a SecretStr) via .get_secret_value().
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from celeste_dag.config.settings import EngineSettings
from celeste_dag.database.models import Base


# ---------------------------------------------------------------------------
# Module-level state (lazily initialised)
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_connect_args(url: str) -> dict:
    """Return dialect-specific connect_args for the given database URL.

    For SQLite we disable ``check_same_thread`` so the async engine can
    share connections across coroutines (required by aiosqlite).
    """
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_engine_from_settings(settings: EngineSettings) -> AsyncEngine:
    """Create an ``AsyncEngine`` from an ``EngineSettings`` instance.

    Reads ``settings.DATABASE_URL`` (a ``SecretStr``) via
    ``.get_secret_value()`` and auto-configures connect args for SQLite.
    """
    url = settings.DATABASE_URL.get_secret_value()
    connect_args = _build_connect_args(url)
    return create_async_engine(url, connect_args=connect_args)


def get_session_factory(
    url: str | None = None,
    settings: EngineSettings | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Return a cached ``async_sessionmaker``.

    Accepts either a raw URL string or an ``EngineSettings`` instance.
    On the first call the engine and session factory are created; subsequent
    calls return the cached factory.
    """
    global _engine, _async_session_factory

    if _async_session_factory is not None:
        return _async_session_factory

    if settings is not None:
        _engine = create_engine_from_settings(settings)
    elif url is not None:
        connect_args = _build_connect_args(url)
        _engine = create_async_engine(url, connect_args=connect_args)
    else:
        raise ValueError("Either url or settings must be provided")

    _async_session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return _async_session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` with automatic commit / rollback.

    * On clean exit the session is committed and then closed.
    * On exception the session is rolled back and then closed; the
      exception is re-raised.
    """
    if _async_session_factory is None:
        raise RuntimeError(
            "Database not initialised. Call init_db() before get_session()."
        )

    session: AsyncSession = _async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db(
    url: str | None = None,
    settings: EngineSettings | None = None,
) -> AsyncEngine:
    """Create all tables and return the ``AsyncEngine``.

    Idempotent: if the engine already exists the cached instance is returned.
    Accepts either a raw URL string or an ``EngineSettings`` instance.
    """
    global _engine, _async_session_factory

    if _engine is not None:
        return _engine

    if settings is not None:
        _engine = create_engine_from_settings(settings)
    elif url is not None:
        connect_args = _build_connect_args(url)
        _engine = create_async_engine(url, connect_args=connect_args)
    else:
        raise ValueError("Either url or settings must be provided")

    _async_session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return _engine


async def close_db() -> None:
    """Dispose of the engine and reset module-level state."""
    global _engine, _async_session_factory

    if _engine is not None:
        await _engine.dispose()

    _engine = None
    _async_session_factory = None
