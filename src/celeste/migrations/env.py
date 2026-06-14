"""Alembic migration environment for Celeste-DAG.

This module is the bridge between Alembic and the Celeste engine. It:

- Resolves the database URL from :class:`celeste.config.settings.EngineSettings`
  (honouring the ``DATABASE_URL`` env var and the project ``.env`` file) so the
  engine and migrations share a single source of truth.
- Translates the async driver schemes used at runtime
  (``sqlite+aiosqlite`` / ``postgresql+asyncpg``) to their synchronous
  counterparts (``sqlite`` / ``postgresql+psycopg2``) for Alembic, which runs
  migrations on a synchronous connection.
- Exposes the full :class:`celeste.database.models.Base.metadata` so
  ``--autogenerate`` diffs against the live models.

Usage::

    # Run from the repo root against the configured DATABASE_URL:
    alembic -c src/celeste/migrations/alembic.ini upgrade head
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import the declarative metadata + models so autogenerate sees every table.
from celeste.database.models import Base  # noqa: F401  (registers tables)
from celeste.config.settings import EngineSettings

# Configure Python logging from alembic.ini when present.
config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # Logging config is non-essential; a missing handler should never
        # block migrations.
        pass


# ---------------------------------------------------------------------------
# Resolve the database URL from EngineSettings.
# ---------------------------------------------------------------------------

# An explicit override wins (useful for CLI: ``x=-c ... alembic ...``).
_CONFIG_URL = os.environ.get("CELESTE_ALEMBIC_DATABASE_URL")


def _resolve_sync_url() -> str:
    """Return a SYNC SQLAlchemy URL derived from EngineSettings.

    EngineSettings stores the runtime (async) URL, e.g.
    ``sqlite+aiosqlite:///celeste.db`` or
    ``postgresql+asyncpg://user:pass@host/db``. Alembic runs migrations on a
    synchronous connection, so we swap to the matching sync driver.
    """
    if _CONFIG_URL:
        url = _CONFIG_URL
    else:
        # Build settings from env/.env exactly the way the engine does.
        url = EngineSettings().DATABASE_URL.get_secret_value()

    # Swap async drivers to their sync equivalents.
    if url.startswith("sqlite+aiosqlite"):
        return url.replace("sqlite+aiosqlite", "sqlite", 1)
    if url.startswith("postgresql+asyncpg"):
        return url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
    return url


# Inject the resolved URL into the Alembic config so the usual machinery
# (``sqlalchemy.url`` key in the ini) is honoured.
config.set_main_option("sqlalchemy.url", _resolve_sync_url())

# Shared metadata target for autogenerate.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render migrations as SQL strings without a live DB connection.

    Used by ``alembic upgrade head --sql``.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
