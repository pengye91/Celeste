"""
Pydantic schemas for the Celeste-DAG Web API.

Request/response models for validating and serializing API payloads.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DAGNodeInput(BaseModel):
    """Input schema for a single DAG node in a workflow creation request."""

    name: str = Field(max_length=255)
    task_type: str = Field(max_length=64)
    command: str = Field(max_length=8192)
    arguments: dict = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list, max_length=1000)
    compensation_command: str | None = Field(default=None, max_length=8192)
    compensation_arguments: dict | None = None


class CreateWorkflowRequest(BaseModel):
    """Request body for POST /api/workflows."""

    name: str = Field(max_length=255)
    description: str = Field(default="", max_length=2048)
    nodes: list[DAGNodeInput] = Field(min_length=1, max_length=1000)
    variables: dict = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    """Response for workflow creation and simple operations."""

    workflow_id: str
    status: str


class WorkflowListItem(BaseModel):
    """Response item for GET /api/workflows listing."""

    id: str
    name: str
    status: str
    created_at: str


class WorkflowDetailResponse(BaseModel):
    """Response for GET /api/workflows/{id}."""

    id: str
    name: str
    description: str
    status: str
    dag_definition: dict
    created_at: str
    updated_at: str


class NodeStatusItem(BaseModel):
    """Node status entry for workflow status response."""

    name: str
    status: str


class WorkflowStatusResponse(BaseModel):
    """Response for GET /api/workflows/{id}/status."""

    workflow_id: str
    status: str
    nodes: list[NodeStatusItem]
    progress: float


class NodeStatusResponse(BaseModel):
    """Response item for GET /api/workflows/{id}/nodes."""

    id: str
    name: str
    task_type: str
    status: str
    outputs: str | None


class EventResponse(BaseModel):
    """Response item for GET /api/workflows/{id}/events."""

    id: str
    event_type: str
    event_data: dict | None
    timestamp: str


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


# ---------------------------------------------------------------------------
# Monitoring UI schemas (Phase 0)
# ---------------------------------------------------------------------------


class PaginationParams(BaseModel):
    """Shared pagination query parameters."""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class WorkflowListResponse(BaseModel):
    """Response for GET /api/workflows with pagination."""

    items: list[WorkflowListItem]
    total: int
    limit: int
    offset: int


class WorkflowEventResponse(BaseModel):
    """Response item for GET /api/workflows/{id}/workflow-events."""

    id: str
    event_type: str
    event_data: dict | None
    sequence_number: int
    timestamp: str


class WorkflowMetricsResponse(BaseModel):
    """Response for GET /api/workflows/{id}/metrics."""

    workflow_id: str
    cycle_count: int
    total_nodes: int
    completed_nodes: int
    failed_nodes: int
    completed_percent: float
    elapsed_seconds: float
    llm_tokens_accumulated: int | None
    max_concurrent_workspaces: int
    security_pass_rate: float | None


class GlobalEventResponse(BaseModel):
    """Response item for GET /api/events global event stream."""

    id: str
    event_source: str  # "task" or "workflow"
    workflow_id: str
    event_type: str
    event_data: dict | None
    timestamp: str


class CORSOrigins(BaseModel):
    """Configuration model for CORS allowed origins."""

    origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class RegisterAgentRequest(BaseModel):
    """Request body for POST /agents/register."""

    url: str
    auth_token: str | None = None
    metadata: dict = Field(default_factory=dict)


class RegisterAgentResponse(BaseModel):
    """Response for POST /agents/register."""

    agent_id: str
    status: str


class AgentStatusResponse(BaseModel):
    """Response for GET /agents/{id}/status."""

    agent_id: str
    status: str
    last_seen: str | None


class AgentListItem(BaseModel):
    """Response item for GET /agents listing."""

    agent_id: str
    url: str
    status: str
    metadata: dict
    registered_at: str


class DeleteAgentResponse(BaseModel):
    """Response for DELETE /agents/{id}."""

    success: bool
