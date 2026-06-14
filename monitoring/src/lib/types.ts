export type WorkflowStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "paused"
  | "escalated"
  | "cancelled";

export interface WorkflowListItem {
  id: string;
  name: string;
  status: WorkflowStatus;
  created_at: string;
}

export interface WorkflowListResponse {
  items: WorkflowListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface WorkflowDetail {
  id: string;
  name: string;
  description: string;
  status: WorkflowStatus;
  dag_definition: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  pause_reason?: string;
  pause_duration?: number;
  pause_cycles?: number;
  pause_tokens?: number;
}

export interface NodeStatusItem {
  name: string;
  status: string;
}

export interface WorkflowStatusResponse {
  workflow_id: string;
  status: WorkflowStatus;
  nodes: NodeStatusItem[];
  progress: number;
}

export interface WorkflowEvent {
  id: string;
  event_type: string;
  event_data: Record<string, unknown> | null;
  timestamp: string;
}

export interface WorkflowWorkflowEvent {
  id: string;
  event_type: string;
  event_data: Record<string, unknown> | null;
  sequence_number: number;
  timestamp: string;
}

export interface WorkflowNodeStatus {
  id: string;
  name: string;
  task_type: string;
  status: string;
  outputs?: Record<string, unknown>;
}

export interface WorkflowMetrics {
  workflow_id: string;
  cycle_count: number;
  total_nodes: number;
  completed_nodes: number;
  failed_nodes: number;
  completed_percent: number;
  elapsed_seconds: number;
  llm_tokens_accumulated: number | null;
  max_concurrent_workspaces: number;
  security_pass_rate: number | null;
}

export interface GlobalEvent {
  id: string;
  event_source: "task" | "workflow";
  workflow_id: string;
  event_type: string;
  event_data: Record<string, unknown> | null;
  timestamp: string;
}

export interface EventQuery {
  event_type?: string;
  since_id?: string;
  limit?: number;
}

export interface AgentListItem {
  agent_id: string;
  url: string;
  status: string;
  metadata: Record<string, unknown>;
  registered_at: string;
}

export interface RegisterAgentRequest {
  url: string;
  auth_token?: string;
  metadata?: Record<string, unknown>;
}

export interface RegisterAgentResponse {
  agent_id: string;
  status: string;
}

// Legacy / compatibility types (kept for existing components during migration)
export interface Workflow {
  id: string;
  goal: string;
  status: WorkflowStatus | "escalated";
  cycle_count: number;
  max_cycles: number;
  created_at: string;
  updated_at: string;
  completed_at?: string;
  error_message?: string;
  node_count: number;
  event_count: number;
}

export interface WorkflowNode {
  id: string;
  workflow_id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
  started_at?: string;
  completed_at?: string;
  retry_count: number;
}

export interface DashboardStats {
  total_workflows: number;
  active_workflows: number;
  completed_today: number;
  failed_today: number;
  avg_cycles: number;
  total_events: number;
}

export type EventType =
  | "WORKFLOW_CREATED"
  | "WORKFLOW_STARTED"
  | "WORKFLOW_COMPLETED"
  | "WORKFLOW_FAILED"
  | "WORKFLOW_CANCELLED"
  | "WORKFLOW_ESCALATED"
  | "NODE_CREATED"
  | "NODE_STARTED"
  | "NODE_COMPLETED"
  | "NODE_FAILED"
  | "NODE_RETRY"
  | "PLAN_GENERATED"
  | "EVALUATION"
  | "SECURITY_AUDIT"
  | "WORKSPACE_SPAWN"
  | "WORKSPACE_DESTROY";

// ------------------------------------------------------------------
// Phase 5: Feature verification + agent status
// ------------------------------------------------------------------

/**
 * Result of checking whether a single spec feature was exercised by a
 * workflow's event stream. The observatory renders one orb per check.
 */
export interface FeatureCheck {
  name: string;
  status: "pass" | "fail" | "not_exercised";
  detail?: string;
}

/**
 * Aggregate fleet-wide view of feature verification. `by_feature` is the
 * per-workflow check list (concatenated across the fleet) so the UI can
 * drill down. The top-level counts let the summary card render directly.
 */
export interface FeatureVerificationSummary {
  total: number;
  pass: number;
  fail: number;
  not_exercised: number;
  by_feature: FeatureCheck[];
}

/**
 * CMC's view of an agent's connection state. `connected` and `disconnected`
 * mirror the values Celeste reports; `unknown` covers "haven't asked yet"
 * (loading) and "ask failed" (error) without conflating them.
 */
export type AgentStatus = "connected" | "disconnected" | "unknown";
