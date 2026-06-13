"""
FastAPI application for the Celeste-DAG Web API.

Provides REST endpoints for:
- Creating and submitting workflows from DAG plans
- Executing workflows
- Retrieving real-time workflow status, events, and node states
- Cancelling workflows

Uses an app factory pattern (``create_app``) for testability:
the engine lifecycle is bound to FastAPI's startup/shutdown events.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from celeste.config.settings import EngineSettings
from celeste.core.engine import Engine
from celeste.core.planner import DAGNode, DAGPlan
from celeste.core.workspaces.base import BaseWorkspace
from celeste.database.db import get_session
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)
from celeste.api.schemas import (
    CreateWorkflowRequest,
    WorkflowResponse,
    WorkflowListItem,
    WorkflowListResponse,
    WorkflowDetailResponse,
    WorkflowStatusResponse,
    NodeStatusItem,
    NodeStatusResponse,
    EventResponse,
    WorkflowEventResponse,
    WorkflowMetricsResponse,
    GlobalEventResponse,
    ErrorResponse,
    RegisterAgentRequest,
    RegisterAgentResponse,
    AgentStatusResponse,
    AgentListItem,
    DeleteAgentResponse,
)
from celeste.core.agent.agent import EnvironmentAgent

logger = logging.getLogger(__name__)

_API_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    settings: EngineSettings | None = None,
    workspace_factory: Callable[[], BaseWorkspace] | None = None,
) -> FastAPI:
    """Create and configure a FastAPI application instance.

    Parameters
    ----------
    settings:
        Engine settings.  If ``None``, defaults are loaded from the
        environment / ``.env`` file via ``EngineSettings()``.
    workspace_factory:
        Callable that returns a ``BaseWorkspace`` instance.
        If ``None`` the engine's default factory is used.
    """

    engine = Engine(settings=settings, workspace_factory=workspace_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage engine lifecycle: start on startup, stop on shutdown."""
        await engine.start()
        yield
        await engine.stop()

    app = FastAPI(
        title="Celeste-DAG",
        version=_API_VERSION,
        lifespan=lifespan,
    )

    # Store engine reference on app state for route handlers
    app.state.engine = engine
    app.state.running_tasks: dict[str, asyncio.Task] = {}
    app.state.agent_registry: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Request-id middleware + global exception handler
    # ------------------------------------------------------------------

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        """Attach a correlation id to every request and response."""
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Catch unhandled exceptions and return a structured error.

        Logs the stack trace with the request id so failures are traceable.
        """
        rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex
        logger.exception(
            "Unhandled exception on %s %s (request_id=%s)",
            request.method, request.url.path, rid,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "internal_error",
                "request_id": rid,
                "error_type": exc.__class__.__name__,
            },
            headers={"X-Request-ID": rid},
        )

    # ------------------------------------------------------------------
    # CORS middleware
    # ------------------------------------------------------------------

    import os

    from fastapi.middleware.cors import CORSMiddleware

    _cors_raw = os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "version": _API_VERSION}

    # ------------------------------------------------------------------
    # POST /api/workflows
    # ------------------------------------------------------------------

    @app.post(
        "/api/workflows",
        status_code=201,
        response_model=WorkflowResponse,
        tags=["workflows"],
    )
    async def create_workflow(body: CreateWorkflowRequest):
        """Create and submit a workflow from a DAG plan."""
        # Convert API input to planner models
        dag_nodes = []
        for node_input in body.nodes:
            dag_nodes.append(
                DAGNode(
                    name=node_input.name,
                    task_type=node_input.task_type,
                    command=node_input.command,
                    arguments=node_input.arguments,
                    dependencies=node_input.dependencies,
                    compensation_command=node_input.compensation_command,
                    compensation_arguments=node_input.compensation_arguments,
                )
            )

        plan = DAGPlan(
            name=body.name,
            description=body.description,
            nodes=dag_nodes,
            variables=body.variables,
        )

        wf_id = await engine.submit_workflow(plan)
        return WorkflowResponse(workflow_id=str(wf_id), status="pending")

    # ------------------------------------------------------------------
    # GET /api/workflows
    # ------------------------------------------------------------------

    @app.get(
        "/api/workflows",
        response_model=WorkflowListResponse,
        tags=["workflows"],
    )
    async def list_workflows(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        status: str | None = Query(default=None),
        created_after: str | None = Query(default=None),
    ):
        """List workflows with pagination and optional filters."""
        async with get_session() as session:
            stmt = select(Workflow)

            if status is not None:
                try:
                    status_enum = WorkflowStatus(status)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid status: {status}",
                    )
                stmt = stmt.where(Workflow.status == status_enum)

            if created_after is not None:
                try:
                    after_dt = datetime.datetime.fromisoformat(created_after)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid created_after: {created_after}",
                    )
                stmt = stmt.where(Workflow.created_at > after_dt)

            # Total count using SQL COUNT(*) — do not materialise all rows.
            count_stmt = select(func.count()).select_from(Workflow)
            if status is not None:
                count_stmt = count_stmt.where(Workflow.status == status_enum)
            if created_after is not None:
                count_stmt = count_stmt.where(Workflow.created_at > after_dt)
            total_result = await session.execute(count_stmt)
            total = total_result.scalar_one()

            stmt = stmt.order_by(Workflow.created_at.desc()).offset(offset).limit(limit)
            result = await session.execute(stmt)
            workflows = result.scalars().all()

            items = [
                WorkflowListItem(
                    id=str(wf.id),
                    name=wf.name,
                    status=wf.status.value,
                    created_at=wf.created_at.isoformat(),
                )
                for wf in workflows
            ]

        return WorkflowListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # GET /api/workflows/{workflow_id}
    # ------------------------------------------------------------------

    @app.get(
        "/api/workflows/{workflow_id}",
        response_model=WorkflowDetailResponse,
        tags=["workflows"],
    )
    async def get_workflow(workflow_id: str):
        """Get workflow details including DAG definition."""
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_uuid)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

            return WorkflowDetailResponse(
                id=str(wf.id),
                name=wf.name,
                description=wf.description or "",
                status=wf.status.value,
                dag_definition=wf.dag_definition,
                created_at=wf.created_at.isoformat(),
                updated_at=wf.updated_at.isoformat(),
            )

    # ------------------------------------------------------------------
    # POST /api/workflows/{workflow_id}/execute
    # ------------------------------------------------------------------

    @app.post(
        "/api/workflows/{workflow_id}/execute",
        response_model=WorkflowResponse,
        tags=["workflows"],
    )
    async def execute_workflow(workflow_id: str):
        """Start executing a submitted workflow.

        Uses an atomic UPDATE workflow SET status='running'
        WHERE id=:id AND status IN ('pending', 'paused') guard so that
        duplicate concurrent /execute calls cannot both succeed.
        """
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Atomic status guard: only flip pending/paused -> running.
        async with get_session() as session:
            from sqlalchemy import update as _sa_update

            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_uuid)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

            stmt = (
                _sa_update(Workflow)
                .where(
                    Workflow.id == wf_uuid,
                    Workflow.status.in_(
                        (WorkflowStatus.PENDING, WorkflowStatus.PAUSED)
                    ),
                )
                .values(status=WorkflowStatus.RUNNING)
            )
            res = await session.execute(stmt)
            await session.commit()

            if res.rowcount == 0:
                # Either not found (already handled) or status not pending/paused.
                # Re-fetch to give a precise 409 message.
                result = await session.execute(
                    select(Workflow).where(Workflow.id == wf_uuid)
                )
                wf = result.scalar_one_or_none()
                if wf is None:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Cannot execute workflow in '{wf.status.value}' state; "
                        "only pending or paused workflows can be executed."
                    ),
                )

        # Run workflow in background so the API returns immediately
        def _on_task_done(task: asyncio.Task) -> None:
            """Done-callback that cleans up state and records exceptions.

            Always removes the task from running_tasks to prevent unbounded
            growth (api-20). On failure, emits a NODE_FAILED WorkflowEvent
            (api-15) and marks the workflow FAILED.
            """
            key = str(wf_uuid)
            try:
                # api-20: always remove on completion, regardless of outcome.
                app.state.running_tasks.pop(key, None)
            except Exception:
                logger.error("Failed to pop %s from running_tasks", key)

            if task.cancelled():
                return
            exc = task.exception()
            if exc is None:
                return
            logger.error(
                "Workflow %s failed with unhandled exception: %s",
                workflow_id, exc,
            )

            # api-15: emit a NODE_FAILED WorkflowEvent so the failure is
            # part of the audit trail. Best-effort: if the engine already
            # wrote a terminal status, this is still informative.
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_mark_workflow_failed(wf_uuid, exc))
            except Exception:
                logger.error(
                    "Could not schedule failure handler for %s", workflow_id,
                )

        async def _mark_workflow_failed(wf_id: uuid.UUID, exc: BaseException) -> None:
            """Best-effort update of workflow status to FAILED + emit NODE_FAILED event."""
            try:
                async with get_session() as session:
                    result = await session.execute(
                        select(Workflow).where(Workflow.id == wf_id)
                    )
                    workflow = result.scalar_one_or_none()
                    if workflow is None:
                        return
                    # Only mark FAILED if not already in a terminal state.
                    if workflow.status not in (
                        WorkflowStatus.COMPLETED,
                        WorkflowStatus.FAILED,
                        WorkflowStatus.CANCELLED,
                    ):
                        workflow.status = WorkflowStatus.FAILED

                    # Attach NODE_FAILED event to a real node (FK NOT NULL).
                    nodes_result = await session.execute(
                        select(TaskNode).where(TaskNode.workflow_id == wf_id).limit(1)
                    )
                    node = nodes_result.scalar_one_or_none()
                    target_node_id = node.id if node else wf_id
                    if node is None:
                        # No node exists yet — use workflow_id as a synthetic
                        # node id? The FK requires a real TaskNode. Skip
                        # emitting the event in that rare case.
                        return

                    seq_result = await session.execute(
                        select(WorkflowEvent)
                        .where(WorkflowEvent.workflow_id == wf_id)
                        .order_by(WorkflowEvent.sequence_number.desc())
                        .limit(1)
                    )
                    last_event = seq_result.scalar_one_or_none()
                    next_seq = (last_event.sequence_number + 1) if last_event else 1
                    session.add(
                        WorkflowEvent(
                            workflow_id=wf_id,
                            task_node_id=target_node_id,
                            event_type=TaskEventType.NODE_FAILED,
                            sequence_number=next_seq,
                            event_data={
                                "error": exc.__class__.__name__,
                                "message": str(exc),
                            },
                        )
                    )
                    await session.commit()
            except Exception:
                logger.exception("Failed to mark workflow %s as failed", wf_id)

        task = asyncio.create_task(engine.run_workflow(wf_uuid))
        task.add_done_callback(_on_task_done)
        app.state.running_tasks[str(wf_uuid)] = task

        return WorkflowResponse(workflow_id=workflow_id, status="running")

    # ------------------------------------------------------------------
    # GET /api/workflows/{workflow_id}/status
    # ------------------------------------------------------------------

    @app.get(
        "/api/workflows/{workflow_id}/status",
        response_model=WorkflowStatusResponse,
        tags=["workflows"],
    )
    async def get_workflow_status(workflow_id: str):
        """Get real-time DAG status (node states, progress)."""
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_uuid)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            nodes = result.scalars().all()

            node_items = [
                NodeStatusItem(name=n.name, status=n.status.value)
                for n in nodes
            ]

            total = len(nodes)
            completed = sum(
                1 for n in nodes
                if n.status.value in ("completed", "failed", "cancelled")
            )
            progress = completed / total if total > 0 else 0.0

            return WorkflowStatusResponse(
                workflow_id=workflow_id,
                status=wf.status.value,
                nodes=node_items,
                progress=progress,
            )

    # ------------------------------------------------------------------
    # GET /api/workflows/{workflow_id}/events
    # ------------------------------------------------------------------

    @app.get(
        "/api/workflows/{workflow_id}/events",
        response_model=list[EventResponse],
        tags=["workflows"],
    )
    async def get_workflow_events(
        workflow_id: str,
        event_type: str | None = Query(default=None),
        since_id: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ):
        """Get TaskEvents for a workflow with optional cursor and type filter."""
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        async with get_session() as session:
            # Verify workflow exists
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_uuid)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

            # Build query — order by (timestamp, id) for deterministic tiebreaker.
            stmt = (
                select(TaskEvent)
                .where(TaskEvent.workflow_id == wf_uuid)
                .order_by(TaskEvent.timestamp.asc(), TaskEvent.id.asc())
            )

            if event_type is not None:
                try:
                    evt_enum = TaskEventType(event_type)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid event_type: {event_type}",
                    )
                stmt = stmt.where(TaskEvent.event_type == evt_enum)

            if since_id is not None:
                try:
                    since_uuid = uuid.UUID(since_id)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid since_id")
                stmt = stmt.where(TaskEvent.id > since_uuid)

            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            events = result.scalars().all()

            return [
                EventResponse(
                    id=str(e.id),
                    event_type=e.event_type.value,
                    event_data=e.event_data,
                    timestamp=e.timestamp.isoformat(),
                )
                for e in events
            ]

    # ------------------------------------------------------------------
    # GET /api/workflows/{workflow_id}/workflow-events
    # ------------------------------------------------------------------

    @app.get(
        "/api/workflows/{workflow_id}/workflow-events",
        response_model=list[WorkflowEventResponse],
        tags=["workflows"],
    )
    async def get_workflow_workflow_events(
        workflow_id: str,
        event_type: str | None = Query(default=None),
        since_id: str | None = Query(default=None),
        since_seq: int | None = Query(default=None, ge=0),
        limit: int = Query(default=50, ge=1, le=500),
    ):
        """Get WorkflowEvent rows for a workflow with optional cursor and type filter.

        ``since_seq`` is the recommended cursor (uses WorkflowEvent.sequence_number
        which is monotonic). ``since_id`` is retained for backwards compatibility
        but should not be used for pagination because UUIDv4 ordering is random.
        """
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_uuid)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

            # Order by (sequence_number, timestamp) for stable ordering.
            stmt = (
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == wf_uuid)
                .order_by(
                    WorkflowEvent.sequence_number.asc(),
                    WorkflowEvent.timestamp.asc(),
                )
            )

            if event_type is not None:
                try:
                    evt_enum = TaskEventType(event_type)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid event_type: {event_type}",
                    )
                stmt = stmt.where(WorkflowEvent.event_type == evt_enum)

            if since_seq is not None:
                stmt = stmt.where(WorkflowEvent.sequence_number > since_seq)
            elif since_id is not None:
                try:
                    since_uuid = uuid.UUID(since_id)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid since_id")
                stmt = stmt.where(WorkflowEvent.id > since_uuid)

            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            events = result.scalars().all()

            return [
                WorkflowEventResponse(
                    id=str(e.id),
                    event_type=e.event_type.value,
                    event_data=e.event_data,
                    sequence_number=e.sequence_number,
                    timestamp=e.timestamp.isoformat(),
                )
                for e in events
            ]

    # ------------------------------------------------------------------
    # GET /api/workflows/{workflow_id}/metrics
    # ------------------------------------------------------------------

    @app.get(
        "/api/workflows/{workflow_id}/metrics",
        response_model=WorkflowMetricsResponse,
        tags=["workflows"],
    )
    async def get_workflow_metrics(workflow_id: str):
        """Compute and return workflow execution metrics."""
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_uuid)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

            # Cycle count: plan_generated WorkflowEvent rows (or TaskEvent if needed)
            cycle_count_q = select(func.count()).select_from(WorkflowEvent).where(
                WorkflowEvent.workflow_id == wf_uuid,
                WorkflowEvent.event_type == TaskEventType.PLAN_GENERATED,
            )
            cycle_count = (await session.execute(cycle_count_q)).scalar_one()

            # Node counts from TaskNode (one COUNT aggregate, grouped by status)
            node_count_q = (
                select(TaskNode.status, func.count())
                .where(TaskNode.workflow_id == wf_uuid)
                .group_by(TaskNode.status)
            )
            node_counts = dict((await session.execute(node_count_q)).all())
            total_nodes = sum(node_counts.values())
            completed_nodes = node_counts.get(TaskNodeStatus.COMPLETED, 0)
            failed_nodes = node_counts.get(TaskNodeStatus.FAILED, 0)
            completed_percent = (
                (completed_nodes / total_nodes * 100) if total_nodes > 0 else 0.0
            )

            # Elapsed seconds
            now = datetime.datetime.now(datetime.timezone.utc)
            created_at = wf.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=datetime.timezone.utc)
            updated_at = wf.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=datetime.timezone.utc)
            if wf.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
                elapsed_seconds = (updated_at - created_at).total_seconds()
            else:
                elapsed_seconds = (now - created_at).total_seconds()

            # Max concurrent workspaces from WORKSPACE_SPAWN / WORKSPACE_DESTROY events
            spawn_destroy_result = await session.execute(
                select(TaskEvent).where(
                    TaskEvent.workflow_id == wf_uuid,
                    TaskEvent.event_type.in_(
                        [TaskEventType.WORKSPACE_SPAWN, TaskEventType.WORKSPACE_DESTROY]
                    ),
                ).order_by(TaskEvent.timestamp.asc())
            )
            spawn_destroy_events = spawn_destroy_result.scalars().all()
            current = 0
            max_concurrent = 0
            for evt in spawn_destroy_events:
                if evt.event_type == TaskEventType.WORKSPACE_SPAWN:
                    current += 1
                    max_concurrent = max(max_concurrent, current)
                elif evt.event_type == TaskEventType.WORKSPACE_DESTROY:
                    current = max(0, current - 1)

            # Security pass rate from SECURITY_AUDIT events
            audit_result = await session.execute(
                select(TaskEvent).where(
                    TaskEvent.workflow_id == wf_uuid,
                    TaskEvent.event_type == TaskEventType.SECURITY_AUDIT,
                )
            )
            audit_events = audit_result.scalars().all()
            if audit_events:
                safe_count = sum(
                    1
                    for e in audit_events
                    if e.event_data and e.event_data.get("result") == "safe"
                )
                security_pass_rate = safe_count / len(audit_events)
            else:
                security_pass_rate = None

            return WorkflowMetricsResponse(
                workflow_id=str(wf.id),
                cycle_count=cycle_count,
                total_nodes=total_nodes,
                completed_nodes=completed_nodes,
                failed_nodes=failed_nodes,
                completed_percent=completed_percent,
                elapsed_seconds=elapsed_seconds,
                llm_tokens_accumulated=wf.llm_tokens_accumulated,
                max_concurrent_workspaces=max_concurrent,
                security_pass_rate=security_pass_rate,
            )

    # ------------------------------------------------------------------
    # GET /api/events
    # ------------------------------------------------------------------

    @app.get(
        "/api/events",
        response_model=list[GlobalEventResponse],
        tags=["events"],
    )
    async def get_global_events(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        """Global event stream combining TaskEvent and WorkflowEvent, newest first.

        Ordering is by (timestamp DESC, id ASC) so events with identical
        timestamps have a stable, deterministic order across pages.
        """
        async with get_session() as session:
            task_stmt = (
                select(TaskEvent)
                .order_by(TaskEvent.timestamp.desc(), TaskEvent.id.asc())
                .limit(limit + offset)
            )
            task_result = await session.execute(task_stmt)
            task_events = task_result.scalars().all()

            wf_stmt = (
                select(WorkflowEvent)
                .order_by(WorkflowEvent.timestamp.desc(), WorkflowEvent.id.asc())
                .limit(limit + offset)
            )
            wf_result = await session.execute(wf_stmt)
            wf_events = wf_result.scalars().all()

            combined = []
            for e in task_events:
                combined.append(
                    (
                        e.timestamp,
                        str(e.id),
                        GlobalEventResponse(
                            id=str(e.id),
                            event_source="task",
                            workflow_id=str(e.workflow_id),
                            event_type=e.event_type.value,
                            event_data=e.event_data,
                            timestamp=e.timestamp.isoformat(),
                        ),
                    )
                )
            for e in wf_events:
                combined.append(
                    (
                        e.timestamp,
                        str(e.id),
                        GlobalEventResponse(
                            id=str(e.id),
                            event_source="workflow",
                            workflow_id=str(e.workflow_id),
                            event_type=e.event_type.value,
                            event_data=e.event_data,
                            timestamp=e.timestamp.isoformat(),
                        ),
                    )
                )

            # Sort by timestamp DESC; ties broken by id ASC for deterministic ordering.
            # We use two passes: first by id (stable) to get a deterministic
            # tiebreaker, then by timestamp DESC. The secondary sort produces
            # a stable total ordering across pages.
            combined.sort(key=lambda x: x[1])  # secondary: id ASC
            combined.sort(key=lambda x: x[0], reverse=True)  # primary: ts DESC
            paginated = combined[offset : offset + limit]
            return [item[2] for item in paginated]

    # ------------------------------------------------------------------
    # GET /api/workflows/{workflow_id}/nodes
    # ------------------------------------------------------------------

    @app.get(
        "/api/workflows/{workflow_id}/nodes",
        response_model=list[NodeStatusResponse],
        tags=["workflows"],
    )
    async def get_workflow_nodes(workflow_id: str):
        """Get all nodes with their statuses."""
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        async with get_session() as session:
            # Verify workflow exists
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_uuid)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

            result = await session.execute(
                select(TaskNode).where(TaskNode.workflow_id == wf_uuid)
            )
            nodes = result.scalars().all()

            return [
                NodeStatusResponse(
                    id=str(n.id),
                    name=n.name,
                    task_type=n.task_type,
                    status=n.status.value,
                    outputs=n.outputs,
                )
                for n in nodes
            ]

    # ------------------------------------------------------------------
    # DELETE /api/workflows/{workflow_id}
    # ------------------------------------------------------------------

    @app.delete(
        "/api/workflows/{workflow_id}",
        response_model=WorkflowResponse,
        tags=["workflows"],
    )
    async def cancel_workflow(workflow_id: str):
        """Cancel a running workflow.

        Existence check is performed FIRST so a non-existent UUID never
        mutates app.state.running_tasks on the error path.
        """
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Existence check first — before mutating running_tasks.
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_uuid)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

            # Only pending or running workflows can be cancelled
            if wf.status not in (WorkflowStatus.PENDING, WorkflowStatus.RUNNING):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot cancel workflow in '{wf.status.value}' state",
                )

            wf.status = WorkflowStatus.CANCELLED
            await session.commit()

        # Only after the DB transition succeeds, cancel the asyncio.Task.
        task = app.state.running_tasks.pop(str(wf_uuid), None)
        if task is not None and not task.done():
            task.cancel()

        return WorkflowResponse(workflow_id=workflow_id, status="cancelled")

    # ------------------------------------------------------------------
    # Agent management endpoints
    # ------------------------------------------------------------------

    @app.post(
        "/agents/register",
        status_code=201,
        response_model=RegisterAgentResponse,
        tags=["agents"],
    )
    async def register_agent(body: RegisterAgentRequest):
        """Register a remote agent with the engine."""
        agent_id = str(uuid.uuid4())
        agent = EnvironmentAgent.remote(url=body.url, auth_token=body.auth_token)
        app.state.agent_registry[agent_id] = {
            "agent": agent,
            "url": body.url,
            "metadata": body.metadata or {},
            "registered_at": datetime.datetime.now(datetime.timezone.utc),
        }
        return RegisterAgentResponse(agent_id=agent_id, status="pending")

    @app.get(
        "/agents/{agent_id}/status",
        response_model=AgentStatusResponse,
        tags=["agents"],
    )
    async def get_agent_status(agent_id: str):
        """Return the status of a registered agent."""
        record = app.state.agent_registry.get(agent_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        agent: EnvironmentAgent = record["agent"]
        status = "connected" if agent.is_running else "disconnected"
        last_seen = record["registered_at"]
        return AgentStatusResponse(
            agent_id=agent_id,
            status=status,
            last_seen=last_seen.isoformat() if last_seen else None,
        )

    @app.get(
        "/agents",
        response_model=list[AgentListItem],
        tags=["agents"],
    )
    async def list_agents():
        """List all registered agents."""
        items: list[AgentListItem] = []
        for agent_id, record in app.state.agent_registry.items():
            agent: EnvironmentAgent = record["agent"]
            status = "connected" if agent.is_running else "disconnected"
            items.append(
                AgentListItem(
                    agent_id=agent_id,
                    url=record["url"],
                    status=status,
                    metadata=record["metadata"],
                    registered_at=record["registered_at"].isoformat(),
                )
            )
        return items

    @app.delete(
        "/agents/{agent_id}",
        response_model=DeleteAgentResponse,
        tags=["agents"],
    )
    async def delete_agent(agent_id: str):
        """Unregister an agent."""
        if agent_id not in app.state.agent_registry:
            raise HTTPException(status_code=404, detail="Agent not found")
        del app.state.agent_registry[agent_id]
        return DeleteAgentResponse(success=True)

    return app
