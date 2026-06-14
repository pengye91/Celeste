"""Workflow retention policy and cleanup (TODO-19).

Workflows accumulate forever today: every OPA-loop run, every checkpointed
"continued-as-new" run, every cancelled workflow stays in the database. Over
time this degrades the Workflows list, the Dashboard, and the event-stream
endpoints that scan ``task_events`` / ``workflow_events``.

This module implements an explicit, conservative retention sweep:

- Only **terminal** workflows (``completed``, ``failed``, ``cancelled``,
  ``escalated``) are ever deleted. Pending / running / paused workflows are
  left untouched.
- Only workflows older than ``WORKFLOW_RETENTION_DAYS`` are eligible.
- A terminal workflow that still has a **child run** (``parent_workflow_id``
  lineage from TODO-20) is preserved so operators never lose a
  "continued as" chain mid-history. The whole lineage is cleaned up only once
  the leaf is itself eligible.
- Cascading FKs on ``task_nodes`` / ``task_events`` / ``workflow_events``
  (``cascade="all, delete-orphan"``) handle the children rows, so deleting a
  ``Workflow`` row drops its entire audit trail in one statement.

The sweep is a pure async function: the engine can schedule it on a timer, a
scheduler job can call it, or an operator can trigger it via the API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from celeste.config.settings import EngineSettings
from celeste.database.db import get_session
from celeste.database.models import Workflow, WorkflowStatus

logger = logging.getLogger(__name__)


# Terminal workflow statuses eligible for cleanup. Pending / running / paused
# are always preserved (an in-flight or operator-resumable workflow is never
# reaped out from under the engine).
TERMINAL_STATUSES: tuple[WorkflowStatus, ...] = (
    WorkflowStatus.COMPLETED,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED,
    WorkflowStatus.ESCALATED,
)


async def cleanup_old_workflows(
    settings: EngineSettings | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete terminal workflows older than ``WORKFLOW_RETENTION_DAYS``.

    Returns a dict with the count of workflows deleted under ``"deleted"``.

    Safe to call repeatedly (idempotent). When ``WORKFLOW_RETENTION_DAYS``
    is ``0`` (the default), retention is disabled and this is a no-op.

    Args:
        settings: Engine settings. Defaults to the cached singleton.
        now: Override the reference "current" time. Mainly for tests; in
            production this is ``datetime.now(timezone.utc)``.
    """
    from celeste.config.settings import get_settings

    settings = settings or get_settings()
    retention_days = settings.WORKFLOW_RETENTION_DAYS

    # 0 disables retention entirely.
    if retention_days <= 0:
        return {"deleted": 0}

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    deleted_count = 0
    async with get_session() as session:
        # Find terminal workflows older than the cutoff that are NOT the
        # parent of any other workflow. We exclude lineage parents so a
        # checkpoint chain is never severed mid-history: deleting a parent
        # would orphan its child's parent_workflow_id and break the "continued
        # as" trail operators rely on. The whole chain becomes eligible only
        # once the leaf run is itself past retention.
        #
        # Strategy: select candidate ids, then drop any id that appears as
        # a parent_workflow_id on another row. SQLAlchemy cascade handles
        # child task_nodes / task_events / workflow_events rows on delete.
        candidates_stmt = (
            select(Workflow.id)
            .where(Workflow.status.in_(TERMINAL_STATUSES))
            .where(Workflow.created_at < cutoff)
        )
        candidate_rows = (await session.execute(candidates_stmt)).all()
        candidate_ids = [row[0] for row in candidate_rows]

        if not candidate_ids:
            return {"deleted": 0}

        # Set of ids referenced as a parent by some other workflow.
        parents_stmt = (
            select(Workflow.parent_workflow_id)
            .where(Workflow.parent_workflow_id.in_(candidate_ids))
            .where(Workflow.parent_workflow_id.is_not(None))
        )
        parent_rows = (await session.execute(parents_stmt)).all()
        protected_parent_ids = {row[0] for row in parent_rows}

        deletable_ids = [
            wid for wid in candidate_ids if wid not in protected_parent_ids
        ]

        if not deletable_ids:
            return {"deleted": 0}

        # Load + delete via ORM so the relationship cascades fire
        # (all, delete-orphan on task_nodes / task_events / workflow_events).
        to_delete = (
            await session.execute(
                select(Workflow).where(Workflow.id.in_(deletable_ids))
            )
        ).scalars().all()

        for wf in to_delete:
            await session.delete(wf)

        deleted_count = len(to_delete)

    logger.info(
        "Workflow retention sweep: deleted %d terminal workflow(s) older than %d day(s)",
        deleted_count,
        retention_days,
    )
    return {"deleted": deleted_count}


async def count_retention_candidates(
    settings: EngineSettings | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """Count terminal workflows past retention age (for dry-run / reporting).

    Unlike :func:`cleanup_old_workflows` this does NOT exclude lineage
    parents: it reports everything that is past age, so operators can see the
    raw backlog before running a sweep.
    """
    from celeste.config.settings import get_settings

    settings = settings or get_settings()
    retention_days = settings.WORKFLOW_RETENTION_DAYS
    if retention_days <= 0:
        return 0

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    async with get_session() as session:
        stmt = (
            select(func.count(Workflow.id))
            .where(Workflow.status.in_(TERMINAL_STATUSES))
            .where(Workflow.created_at < cutoff)
        )
        return int((await session.execute(stmt)).scalar() or 0)
