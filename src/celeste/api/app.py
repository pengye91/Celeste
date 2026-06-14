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
from typing import Any, Callable

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
    RunRequest,
    RunResponse,
    RunStatus,
)
from celeste.core.agent.agent import EnvironmentAgent
from celeste.toolkits.base import BaseToolkit
from celeste.toolkits.system_data import SystemDataToolkit

logger = logging.getLogger(__name__)


def _utc_iso(dt: datetime.datetime | None) -> str | None:
    """Serialize a DB-sourced datetime as a timezone-aware UTC ISO 8601 string.

    SQLite/aiosqlite strips ``tzinfo`` on retrieval, so DB datetimes are naive
    (UTC value, no offset). Serializing them with bare ``.isoformat()`` yields a
    string with NO timezone marker, which the frontend ``new Date(iso)`` parses
    as LOCAL time — producing wrong relative times.

    This helper re-stamps naive datetimes as UTC so ``.isoformat()`` emits a
    trailing ``+00:00`` offset, while preserving microseconds and passing
    through already-aware datetimes unchanged.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.isoformat()

_API_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Default OPA-loop component factories
#
# These mirror the wiring in run_local._build_llm_client / the real
# Planner / Evaluator constructors. They use the LLM client built from the
# provided settings, so the embedded tier runs the SAME cognitive stack as
# the local tier by default. Tests override them with fake factories that
# need no LLM.
# ---------------------------------------------------------------------------


def _build_llm_client(settings: EngineSettings) -> Any:  # noqa: F821 (typing.Any below)
    """Build the appropriate LLM client from settings (mirrors run_local)."""
    provider = settings.LLM_PROVIDER
    if provider == "anthropic":
        from celeste.core.llm.anthropic import AnthropicClient

        return AnthropicClient(settings)
    elif provider == "openai":
        from celeste.core.llm.openai import OpenAIClient

        return OpenAIClient(settings)
    elif provider == "gemini":
        from celeste.core.llm.gemini import GeminiClient

        return GeminiClient(settings)
    elif provider == "ollama":
        from celeste.core.llm.ollama import OllamaClient

        return OllamaClient(settings)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


def _default_planner_factory(
    settings: EngineSettings,
    toolkits: list[BaseToolkit],
    llm_client: Any,
) -> Any:
    """Build the real LLM-backed Planner (default)."""
    from celeste.core.planner import Planner

    return Planner(llm_client=llm_client, toolkits=toolkits)


def _default_evaluator_factory(
    settings: EngineSettings,
    llm_client: Any,
) -> Any:
    """Build the real LLM-backed Evaluator (default)."""
    from celeste.core.evaluator import Evaluator

    return Evaluator(llm_client=llm_client)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    settings: EngineSettings | None = None,
    workspace_factory: Callable[[], BaseWorkspace] | None = None,
    toolkits: list[BaseToolkit] | None = None,
    planner_factory: Callable[..., Any] | None = None,
    evaluator_factory: Callable[..., Any] | None = None,
    llm_client: Any = None,
    seed_loader: Callable[[str, Any], Any] | None = None,
    seed_dir: Any | None = None,
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
    toolkits:
        Toolkits stashed on ``app.state.toolkits`` and used by the embedded
        ``/api/runs`` endpoint to build the in-process agent. Defaults to a
        single ``SystemDataToolkit`` so the embedded tier is usable out of
        the box. Domain toolkits (e.g. ``PharmaColdChainToolkit``) are passed
        in by the example wiring — core never imports examples.
    planner_factory:
        ``callable(settings, toolkits, llm_client) -> Planner``. Defaults to
        the real LLM-backed ``Planner``. Tests pass a fake that returns a
        trivial fragment without an LLM.
    evaluator_factory:
        ``callable(settings, llm_client) -> Evaluator``. Defaults to the real
        LLM-backed ``Evaluator``.
    llm_client:
        Pre-built LLM client. If ``None`` it is built from ``settings`` (the
        same logic as ``run_local._build_llm_client``).
    seed_loader:
        Optional async callable ``(db_url: str, seed_dir: Path) -> Any`` used
        by the ``/api/runs`` background worker to seed the run's database
        before the OPA loop starts. Injected by example wiring (e.g.
        ``run_embedded.py``) — **core never imports the example seed loader**.
        If ``None`` (default) seed loading is skipped entirely, keeping core
        generic and decoupled from ``examples/**``. Both ``seed_loader`` AND
        ``seed_dir`` must be provided for seeding to run.
    seed_dir:
        Path to the seed-data directory (the caller knows the correct path;
        core never computes it). Passed straight through to ``seed_loader``.
        If ``None`` (default) seed loading is skipped.
    """

    engine = Engine(settings=settings, workspace_factory=workspace_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage engine lifecycle: start on startup, stop on shutdown.

        On shutdown (after ``engine.stop()``) this cancels every in-flight
        ``/api/runs`` background task and marks any run still at status
        ``"running"`` as ``"failed"`` (error=``"shutdown"``) so observers see
        the truth instead of a run stuck "running" forever. Mirrors the
        teardown the test fixture / ``run_embedded`` already do manually.
        """
        await engine.start()
        yield
        await engine.stop()

        # Cancel in-flight /api/runs tasks, then await them with a timeout.
        # Shielding protects against CancelledError bubbling up here.
        running_run_tasks: dict[str, asyncio.Task] = getattr(
            app.state, "running_run_tasks", {}
        )
        for rid, task in list(running_run_tasks.items()):
            if not task.done():
                task.cancel()
        if running_run_tasks:
            try:
                await asyncio.wait(
                    [t for t in running_run_tasks.values()],
                    timeout=2.0,
                )
            except asyncio.CancelledError:
                pass

        # Flip any run still at status "running" to "failed" (error="shutdown").
        runs: dict[str, dict[str, Any]] = getattr(app.state, "runs", {})
        for rid, record in runs.items():
            if record.get("status") == "running":
                record["status"] = "failed"
                record["error"] = "shutdown"

    app = FastAPI(
        title="Celeste-DAG",
        version=_API_VERSION,
        lifespan=lifespan,
    )

    # Store engine reference on app state for route handlers
    app.state.engine = engine
    app.state.settings = settings
    app.state.running_tasks: dict[str, asyncio.Task] = {}
    app.state.agent_registry: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Embedded OPA-loop state (/api/runs)
    #
    # toolkits: the in-process agent's toolkits (default: SystemDataToolkit).
    #   Domain toolkits are injected by the example wiring (core never
    #   imports examples).
    # runs: run_id -> {"status", "workflow_id", "error"} for polling.
    # running_run_tasks: run_id -> asyncio.Task so in-flight runs can be
    #   awaited/cancelled on shutdown.
    # planner_factory / evaluator_factory / llm_client: the cognitive stack
    #   used by /api/runs. Defaults build the real LLM-backed components;
    #   tests inject fakes (no LLM).
    # ------------------------------------------------------------------
    if toolkits is None:
        app.state.toolkits: list[BaseToolkit] = [SystemDataToolkit()]
    else:
        app.state.toolkits = list(toolkits)
    app.state.planner_factory = planner_factory or _default_planner_factory
    app.state.evaluator_factory = evaluator_factory or _default_evaluator_factory
    app.state.llm_client = llm_client
    app.state.runs: dict[str, dict[str, Any]] = {}
    app.state.running_run_tasks: dict[str, asyncio.Task] = {}
    # Seed loading via DI: the caller (example wiring) injects the loader +
    # the correct seed_dir. Core never imports the example loader, and never
    # computes the path itself. When either is None, seeding is skipped.
    app.state.seed_loader = seed_loader
    app.state.seed_dir = seed_dir

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
                    created_at=_utc_iso(wf.created_at),
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
                created_at=_utc_iso(wf.created_at),
                updated_at=_utc_iso(wf.updated_at),
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
                        WorkflowStatus.ESCALATED,
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
                    timestamp=_utc_iso(e.timestamp),
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
                    timestamp=_utc_iso(e.timestamp),
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

            # Elapsed seconds. _utc_iso re-stamps naive (UTC-valued) DB datetimes
            # as timezone-aware UTC; here we mirror that for arithmetic by
            # parsing the helper's output back into an aware datetime.
            now = datetime.datetime.now(datetime.timezone.utc)
            created_at = datetime.datetime.fromisoformat(_utc_iso(wf.created_at))
            updated_at = datetime.datetime.fromisoformat(_utc_iso(wf.updated_at))
            if wf.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED, WorkflowStatus.ESCALATED):
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
                            timestamp=_utc_iso(e.timestamp),
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
                            timestamp=_utc_iso(e.timestamp),
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
            last_seen=_utc_iso(last_seen),
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
                    registered_at=_utc_iso(record["registered_at"]),
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

    # ------------------------------------------------------------------
    # Embedded OPA-loop endpoints: POST /api/runs, GET /api/runs/{run_id}
    #
    # These drive the OPA loop (engine.run) inside the same FastAPI process.
    # The OPA loop persists Workflow + TaskEvent rows to settings.DATABASE_URL
    # as it runs, so the existing monitoring endpoints
    # (GET /api/workflows, /api/workflows/{id}/...) surface the run live with
    # no extra wiring. POST returns immediately (202-style); callers poll
    # GET /api/runs/{run_id} until a terminal status.
    # ------------------------------------------------------------------

    @app.post(
        "/api/runs",
        response_model=RunResponse,
        status_code=202,
        tags=["runs"],
    )
    async def start_run(body: RunRequest):
        """Start an embedded OPA-loop run in the background.

        Builds an in-process agent from ``app.state.toolkits`` plus the
        configured planner/evaluator factories, launches the OPA loop as a
        background ``asyncio.Task``, and returns a ``run_id`` immediately.
        Poll ``GET /api/runs/{run_id}`` for the outcome.
        """
        run_id = uuid.uuid4().hex
        app.state.runs[run_id] = {
            "status": "running",
            "workflow_id": None,
            "error": None,
        }

        task = asyncio.create_task(_run_opa_loop(app, run_id, body))
        app.state.running_run_tasks[run_id] = task
        return RunResponse(run_id=run_id, status="started")

    @app.get(
        "/api/runs/{run_id}",
        response_model=RunStatus,
        tags=["runs"],
    )
    async def get_run(run_id: str):
        """Poll the status of an embedded OPA-loop run."""
        record = app.state.runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return RunStatus(
            run_id=run_id,
            status=record.get("status", "running"),
            workflow_id=record.get("workflow_id"),
            error=record.get("error"),
        )

    # ------------------------------------------------------------------
    # /api/runs background worker
    # ------------------------------------------------------------------

    async def _load_seed_best_effort(db_url: str) -> None:
        """Best-effort load of seed data into ``db_url`` via DI.

        Uses ``app.state.seed_loader`` and ``app.state.seed_dir`` injected by
        the caller (example wiring). Core never imports the example loader and
        never computes the path itself — the caller owns both. When either is
        ``None`` (the default), seeding is skipped entirely so core stays
        generic. Failures are logged and swallowed so a seed-load bug never
        masks a real engine bug.
        """
        seed_loader = app.state.seed_loader
        seed_dir = app.state.seed_dir
        if seed_loader is None or seed_dir is None:
            return  # no loader injected — nothing to load (core is generic)
        try:
            counts = await seed_loader(db_url, seed_dir)
            logger.info("Embedded run: loaded seed data: %s", counts)
        except Exception as exc:
            logger.warning(
                "Embedded run: seed data load failed; downstream SQL "
                "queries may fail. Cause: %s", exc,
            )

    async def _mark_running_workflow_failed(
        engine_ref: Engine, workflow_id: uuid.UUID | None, goal: str, exc: BaseException,
    ) -> None:
        """Best-effort mark a stuck RUNNING workflow FAILED after a crash.

        Mirrors run_local.py's crash handling: the OPA loop creates a
        Workflow row with status=RUNNING before the planner runs. If anything
        raises before the loop flips the status, the row would stay RUNNING
        forever. Mark it FAILED here so observers see the truth.
        """
        try:
            from sqlalchemy import select as _select

            target_id = workflow_id
            if target_id is None:
                async with get_session() as session:
                    result = await session.execute(
                        _select(Workflow)
                        .where(Workflow.name == goal)
                        .where(Workflow.status == WorkflowStatus.RUNNING)
                        .order_by(Workflow.created_at.desc())
                        .limit(1)
                    )
                    wf = result.scalar_one_or_none()
                    if wf is not None:
                        target_id = wf.id

            if target_id is None:
                return
            async with get_session() as session:
                result = await session.execute(
                    _select(Workflow).where(Workflow.id == target_id)
                )
                wf = result.scalar_one_or_none()
                if wf is not None and wf.status not in (
                    WorkflowStatus.COMPLETED,
                    WorkflowStatus.FAILED,
                    WorkflowStatus.CANCELLED,
                    WorkflowStatus.ESCALATED,
                ):
                    wf.status = WorkflowStatus.FAILED
                    await session.commit()
                    logger.info(
                        "Embedded run: marked workflow %s FAILED after crash",
                        target_id,
                    )
        except Exception:
            logger.error(
                "Embedded run: failed to mark workflow FAILED after crash",
                exc_info=True,
            )

    async def _run_opa_loop(app: FastAPI, run_id: str, body: RunRequest) -> None:
        """Background task that drives a single OPA-loop run.

        (a) best-effort load pharma seed data into settings.DATABASE_URL,
        (b) build agent = EnvironmentAgent.in_process(...),
        (c) build planner/evaluator via the injected factories,
        (d) await engine.run(goal, agent, planner, evaluator, ...),
        (e) store the outcome in app.state.runs[run_id]; on exception set
            status="failed" and mark any RUNNING workflow FAILED.
        """
        settings_ref: EngineSettings = app.state.settings
        engine_ref: Engine = app.state.engine
        goal = body.goal
        run_kwargs: dict[str, Any] = {}
        if body.max_cycles is not None:
            run_kwargs["max_cycles"] = body.max_cycles
        if body.max_llm_tokens is not None:
            run_kwargs["max_llm_tokens"] = body.max_llm_tokens

        try:
            # (a) best-effort seed load via DI (loader + path injected by caller).
            db_url = settings_ref.DATABASE_URL.get_secret_value()
            await _load_seed_best_effort(db_url)

            # (b) in-process agent carrying the configured toolkits.
            agent = EnvironmentAgent.in_process(
                workdir=".", toolkits=app.state.toolkits
            )

            # (c) build the cognitive stack via the injected factories.
            llm_client = app.state.llm_client
            if llm_client is None:
                llm_client = _build_llm_client(settings_ref)
            planner = app.state.planner_factory(settings_ref, app.state.toolkits, llm_client)
            evaluator = app.state.evaluator_factory(settings_ref, llm_client)

            # (d) drive the OPA loop.
            workflow_result = await engine_ref.run(
                goal=goal,
                agent=agent,
                planner=planner,
                evaluator=evaluator,
                **run_kwargs,
            )

            wf_id = (
                str(workflow_result.workflow_id)
                if workflow_result and workflow_result.workflow_id
                else None
            )
            status = workflow_result.status if workflow_result else "unknown"
            app.state.runs[run_id] = {
                "status": status,
                "workflow_id": wf_id,
                "error": None,
            }
            logger.info(
                "Embedded run %s completed: status=%s workflow_id=%s",
                run_id, status, wf_id,
            )
        except asyncio.CancelledError:
            # Propagate cancellation; leave the run marked running so the
            # caller sees it was interrupted.
            raise
        except Exception as exc:
            logger.error(
                "Embedded run %s failed: %s", run_id, exc, exc_info=True,
            )
            # The workflow_id is unknown to us on this path — let the
            # best-effort crash handler find the stuck RUNNING row.
            await _mark_running_workflow_failed(engine_ref, None, goal, exc)
            app.state.runs[run_id] = {
                "status": "failed",
                "workflow_id": app.state.runs.get(run_id, {}).get("workflow_id"),
                "error": str(exc),
            }
        finally:
            app.state.running_run_tasks.pop(run_id, None)

    return app
