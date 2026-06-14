"""Alembic database migrations package for Celeste-DAG.

This package ships with the wheel so deployed environments can run
``alembic upgrade head`` against ``alembic.ini`` (or
``alembic -c src/celeste/migrations/alembic.ini upgrade head``) without a
source checkout.

The migration environment is async-aware: ``env.py`` reads the database URL
from :class:`celeste.config.settings.EngineSettings` (so the same
``DATABASE_URL`` / ``.env`` the engine uses is honoured by migrations) and
uses the sync SQLAlchemy URL form (the async drivers ``aiosqlite`` /
``asyncpg`` are swapped to their sync counterparts internally).
"""
