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
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import select

from celeste_dag.config.settings import EngineSettings
from celeste_dag.core.engine import Engine
from celeste_dag.core.planner import DAGNode, DAGPlan
from celeste_dag.core.workspaces.base import BaseWorkspace
from celeste_dag.database.db import get_session
from celeste_dag.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    Workflow,
    WorkflowStatus,
)
from celeste_dag.api.schemas import (
    CreateWorkflowRequest,
    WorkflowResponse,
    WorkflowListItem,
    WorkflowDetailResponse,
    WorkflowStatusResponse,
    NodeStatusItem,
    NodeStatusResponse,
    EventResponse,
    ErrorResponse,
)

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
        response_model=list[WorkflowListItem],
        tags=["workflows"],
    )
    async def list_workflows():
        """List all workflows."""
        workflows: list[WorkflowListItem] = []
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).order_by(Workflow.created_at.desc())
            )
            for wf in result.scalars().all():
                workflows.append(
                    WorkflowListItem(
                        id=str(wf.id),
                        name=wf.name,
                        status=wf.status.value,
                        created_at=wf.created_at.isoformat(),
                    )
                )
        return workflows

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
        """Start executing a submitted workflow."""
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Verify workflow exists
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == wf_uuid)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

        # Run workflow in background so the API returns immediately
        def _on_task_done(task: asyncio.Task) -> None:
            """Done-callback that catches exceptions from background tasks."""
            if task.cancelled():
                return
            if exc := task.exception():
                logger.error(
                    "Workflow %s failed with unhandled exception: %s",
                    workflow_id, exc,
                )
                # Best effort: update workflow status to failed
                try:
                    import asyncio as _aio
                    loop = _aio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(_mark_workflow_failed(wf_uuid))
                except Exception:
                    logger.error(
                        "Could not mark workflow %s as failed", workflow_id,
                    )

        async def _mark_workflow_failed(wf_id: uuid.UUID) -> None:
            """Best-effort update of workflow status to failed."""
            try:
                async with get_session() as session:
                    result = await session.execute(
                        select(Workflow).where(Workflow.id == wf_id)
                    )
                    workflow = result.scalar_one_or_none()
                    if workflow is not None:
                        workflow.status = WorkflowStatus.FAILED
            except Exception:
                logger.error("Failed to update workflow %s status", wf_id)

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
        limit: int = Query(default=50, ge=1, le=500),
    ):
        """Get all TaskEvents for a workflow (audit log)."""
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

            # Build query
            stmt = (
                select(TaskEvent)
                .where(TaskEvent.workflow_id == wf_uuid)
                .order_by(TaskEvent.timestamp.asc())
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
        """Cancel a running workflow."""
        try:
            wf_uuid = uuid.UUID(workflow_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Cancel the running asyncio.Task if one exists
        if str(wf_uuid) in app.state.running_tasks:
            app.state.running_tasks[str(wf_uuid)].cancel()
            del app.state.running_tasks[str(wf_uuid)]

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

        return WorkflowResponse(workflow_id=workflow_id, status="cancelled")

    return app
