"""
Pydantic schemas for the Celeste-DAG Web API.

Request/response models for validating and serializing API payloads.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DAGNodeInput(BaseModel):
    """Input schema for a single DAG node in a workflow creation request."""

    name: str
    task_type: str
    command: str
    arguments: dict = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    compensation_command: str | None = None
    compensation_arguments: dict | None = None


class CreateWorkflowRequest(BaseModel):
    """Request body for POST /api/workflows."""

    name: str
    description: str = ""
    nodes: list[DAGNodeInput] = Field(min_length=1)
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


class ResumeWorkflowRequest(BaseModel):
    """Request body for POST /api/workflows/{id}/resume."""

    human_input: str = Field(min_length=1, max_length=10240)


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


# ---------------------------------------------------------------------------
# Agent management schemas
# ---------------------------------------------------------------------------


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
