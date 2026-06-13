"""Tests that the in-process pharma runner marks Workflows FAILED on crash.

Symptom: `run_pharma_local` runs the engine in-process. When the planner
raises (e.g. truncated JSON), the try/finally stops the engine and returns
a result with status="failed", but the Workflow DB row is never updated.
CMC keeps showing the workflow as "running" indefinitely.

These tests pin down the contract: any unhandled exception during
`engine.run(...)` must result in the Workflow row's status being FAILED
in the database.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _add_example_to_path() -> None:
    """Ensure the example directory is on sys.path for imports."""
    example_dir = str(
        Path(__file__).resolve().parent.parent
        / "examples"
        / "pharma-coldchain"
    )
    if example_dir not in sys.path:
        sys.path.insert(0, example_dir)


@pytest.mark.asyncio
async def test_run_pharma_local_marks_workflow_failed_on_engine_crash(tmp_path):
    """When engine.run() raises, run_pharma_local must mark the Workflow row FAILED.

    The OPA loop creates the Workflow row with status=RUNNING as its first
    step. If planner/agent/evaluator raises an unhandled exception that
    escapes the loop, the row stays RUNNING. The runner is responsible for
    the exception path: catch, flip status to FAILED, re-raise.
    """
    _add_example_to_path()

    db_path = tmp_path / "crash_test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    # Set up a fresh, empty database.
    from celeste.config.settings import EngineSettings
    from celeste.database.db import close_db, init_db

    settings = EngineSettings(DATABASE_URL=db_url)  # type: ignore[arg-type]
    await init_db(settings=settings)

    try:
        # Seed a Workflow row that simulates the state the OPA loop would
        # create right after _create_workflow() — RUNNING with no result yet.
        from celeste.database.db import get_session
        from celeste.database.models import Workflow, WorkflowStatus

        wf_id = uuid.uuid4()
        async with get_session() as session:
            session.add(
                Workflow(
                    id=wf_id,
                    name="Test goal",
                    status=WorkflowStatus.RUNNING,
                    dag_definition={"goal": "Test goal"},
                )
            )

        # Import run_pharma_local lazily so the example dir is on sys.path.
        import run_local

        # Build a mock engine whose .run() raises, simulating the planner
        # blowing up with a JSON parse error or similar.
        mock_engine = MagicMock()
        mock_engine.start = AsyncMock()
        mock_engine.stop = AsyncMock()
        mock_engine.run = AsyncMock(
            side_effect=RuntimeError("planner raised: truncated JSON"),
        )

        # Patch the helpers that build real LLM clients / toolkits.
        with patch.object(run_local, "Engine", return_value=mock_engine), \
             patch.object(run_local, "_build_settings", return_value=settings), \
             patch.object(
                 run_local, "_build_llm_client", return_value=MagicMock(),
             ), \
             patch.object(run_local, "_load_goal", return_value="Test goal"):
            with pytest.raises(RuntimeError, match="truncated JSON"):
                await run_local.run_pharma_local(
                    database_url=db_url,
                    api_key="sk-test",
                )

        # After the crash, the Workflow row must be FAILED — not RUNNING.
        async with get_session() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_id)
            )
            wf = result.scalar_one()
            assert wf.status == WorkflowStatus.FAILED, (
                f"Expected workflow {wf_id} to be FAILED after crash, "
                f"got status={wf.status}"
            )
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_run_pharma_local_re_raises_after_marking_failed(tmp_path):
    """The runner must re-raise the original exception after marking FAILED."""
    _add_example_to_path()

    db_path = tmp_path / "re_raise_test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    from celeste.config.settings import EngineSettings
    from celeste.database.db import close_db, init_db

    settings = EngineSettings(DATABASE_URL=db_url)  # type: ignore[arg-type]
    await init_db(settings=settings)

    try:
        import run_local

        mock_engine = MagicMock()
        mock_engine.start = AsyncMock()
        mock_engine.stop = AsyncMock()
        mock_engine.run = AsyncMock(
            side_effect=ValueError("boom"),
        )

        with patch.object(run_local, "Engine", return_value=mock_engine), \
             patch.object(run_local, "_build_settings", return_value=settings), \
             patch.object(
                 run_local, "_build_llm_client", return_value=MagicMock(),
             ), \
             patch.object(run_local, "_load_goal", return_value="Test goal"):
            with pytest.raises(ValueError, match="boom"):
                await run_local.run_pharma_local(
                    database_url=db_url,
                    api_key="sk-test",
                )

        # The stop() must have been called via the finally block.
        mock_engine.stop.assert_awaited()
    finally:
        await close_db()