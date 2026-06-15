import type {
  WorkflowListResponse,
  WorkflowDetail,
  WorkflowStatusResponse,
  WorkflowEvent,
  WorkflowWorkflowEvent,
  WorkflowMetrics,
  GlobalEvent,
  AgentListItem,
  RegisterAgentRequest,
  RegisterAgentResponse,
  WorkflowNodeStatus,
  RetentionCleanupResponse,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_CELESTE_API_URL || "http://localhost:8000";

class CelesteAPIError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "CelesteAPIError";
    this.status = status;
  }
}

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new Error("CMC lost contact with Celeste");
  }

  if (res.status >= 500) {
    throw new Error("CMC lost contact with Celeste");
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new CelesteAPIError(`API ${res.status}: ${body}`, res.status);
  }

  return res.json() as Promise<T>;
}

// ------------------------------------------------------------------
// Workflows
// ------------------------------------------------------------------

export async function listWorkflows(opts?: {
  limit?: number;
  offset?: number;
  status?: string;
  created_after?: string;
}): Promise<WorkflowListResponse> {
  const params = new URLSearchParams();
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts?.status) params.set("status", opts.status);
  if (opts?.created_after) params.set("created_after", opts.created_after);
  const query = params.toString();
  return fetchJson<WorkflowListResponse>(`/api/workflows${query ? `?${query}` : ""}`);
}

export async function getWorkflow(id: string): Promise<WorkflowDetail> {
  return fetchJson<WorkflowDetail>(`/api/workflows/${encodeURIComponent(id)}`);
}

export async function getWorkflowStatus(id: string): Promise<WorkflowStatusResponse> {
  return fetchJson<WorkflowStatusResponse>(`/api/workflows/${encodeURIComponent(id)}/status`);
}

export async function getWorkflowEvents(
  id: string,
  opts?: { event_type?: string; since_id?: string; limit?: number }
): Promise<WorkflowEvent[]> {
  const params = new URLSearchParams();
  if (opts?.event_type) params.set("event_type", opts.event_type);
  if (opts?.since_id) params.set("since_id", opts.since_id);
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  const query = params.toString();
  return fetchJson<WorkflowEvent[]>(
    `/api/workflows/${encodeURIComponent(id)}/events${query ? `?${query}` : ""}`
  );
}

export async function getWorkflowWorkflowEvents(
  id: string,
  opts?: { event_type?: string; since_id?: string; limit?: number }
): Promise<WorkflowWorkflowEvent[]> {
  const params = new URLSearchParams();
  if (opts?.event_type) params.set("event_type", opts.event_type);
  if (opts?.since_id) params.set("since_id", opts.since_id);
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  const query = params.toString();
  return fetchJson<WorkflowWorkflowEvent[]>(
    `/api/workflows/${encodeURIComponent(id)}/workflow-events${query ? `?${query}` : ""}`
  );
}

export async function getWorkflowMetrics(id: string): Promise<WorkflowMetrics> {
  return fetchJson<WorkflowMetrics>(`/api/workflows/${encodeURIComponent(id)}/metrics`);
}

export async function getWorkflowNodes(id: string): Promise<WorkflowNodeStatus[]> {
  return fetchJson<WorkflowNodeStatus[]>(`/api/workflows/${encodeURIComponent(id)}/nodes`);
}

export async function getGlobalEvents(opts?: {
  limit?: number;
  offset?: number;
  event_type?: string;
}): Promise<GlobalEvent[]> {
  const params = new URLSearchParams();
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts?.event_type) params.set("event_type", opts.event_type);
  const query = params.toString();
  return fetchJson<GlobalEvent[]>(`/api/events${query ? `?${query}` : ""}`);
}

export async function cancelWorkflow(id: string): Promise<{ workflow_id: string; status: string }> {
  try {
    return await fetchJson<{ workflow_id: string; status: string }>(
      `/api/workflows/${encodeURIComponent(id)}`,
      { method: "DELETE" }
    );
  } catch (err) {
    if (err instanceof CelesteAPIError && err.status === 409) {
      throw new Error("Workflow is already in a terminal state and cannot be cancelled.");
    }
    throw err;
  }
}

export async function resumeWorkflow(
  id: string,
  humanInput?: string
): Promise<{ workflow_id: string; status: string }> {
  try {
    return await fetchJson<{ workflow_id: string; status: string }>(
      `/api/workflows/${encodeURIComponent(id)}/resume`,
      {
        method: "POST",
        body: humanInput ? JSON.stringify({ human_input: humanInput }) : undefined,
      }
    );
  } catch (err) {
    if (err instanceof CelesteAPIError && err.status === 409) {
      throw new Error("Workflow is not in a pausable state and cannot be resumed.");
    }
    throw err;
  }
}

// ------------------------------------------------------------------
// Agents
// ------------------------------------------------------------------

export async function listAgents(): Promise<AgentListItem[]> {
  return fetchJson<AgentListItem[]>("/agents");
}

export async function registerAgent(body: RegisterAgentRequest): Promise<RegisterAgentResponse> {
  return fetchJson<RegisterAgentResponse>("/agents/register", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ------------------------------------------------------------------
// Admin
// ------------------------------------------------------------------

export async function runRetentionCleanup(): Promise<RetentionCleanupResponse> {
  return fetchJson<RetentionCleanupResponse>("/admin/retention/cleanup", {
    method: "POST",
  });
}

// ------------------------------------------------------------------
// Server-Sent Events URL builders
// ------------------------------------------------------------------

/**
 * Returns the URL of the global SSE event stream. Does NOT open the
 * connection — hand the result to a `useSSE` consumer.
 */
export function streamGlobalEvents(opts?: {
  limit?: number;
  event_type?: string;
}): string {
  const params = new URLSearchParams();
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.event_type) params.set("event_type", opts.event_type);
  const query = params.toString();
  return `${API_BASE}/api/events/stream${query ? `?${query}` : ""}`;
}

/**
 * Returns the URL of the per-workflow SSE status stream. Does NOT open
 * the connection — hand the result to a `useSSE` consumer.
 */
export function streamWorkflowStatus(workflowId: string): string {
  return `${API_BASE}/api/workflows/${encodeURIComponent(workflowId)}/status/stream`;
}

// ------------------------------------------------------------------
// Legacy api object (kept for compatibility during migration)
// ------------------------------------------------------------------

import type { Workflow as LegacyWorkflow, WorkflowListResponse as LegacyWorkflowListResponse, WorkflowEvent as LegacyWorkflowEvent, WorkflowNode, DashboardStats } from "@/lib/types";

export const api = {
  workflows: {
    list: (page = 1, pageSize = 20) =>
      fetchJson<LegacyWorkflowListResponse>(`/api/workflows?page=${page}&page_size=${pageSize}`),
    get: (id: string) => fetchJson<LegacyWorkflow>(`/api/workflows/${id}`),
    events: (id: string, page = 1, pageSize = 50) =>
      fetchJson<{ items: LegacyWorkflowEvent[]; total: number }>(`/api/workflows/${id}/events?page=${page}&page_size=${pageSize}`),
    nodes: (id: string) => fetchJson<WorkflowNode[]>(`/api/workflows/${id}/nodes`),
    cancel: (id: string) =>
      fetchJson<LegacyWorkflow>(`/api/workflows/${id}/cancel`, { method: "POST" }),
  },
  dashboard: {
    stats: () => fetchJson<DashboardStats>("/api/dashboard/stats"),
    recentEvents: (limit = 20) =>
      fetchJson<LegacyWorkflowEvent[]>(`/api/dashboard/recent-events?limit=${limit}`),
    activeWorkflows: () => fetchJson<LegacyWorkflow[]>("/api/dashboard/active-workflows"),
  },
};
