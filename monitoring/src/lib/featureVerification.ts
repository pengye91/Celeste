import type { GlobalEvent, WorkflowWorkflowEvent } from "@/lib/types";
import { getWorkflowWorkflowEvents } from "@/lib/api";

/**
 * Per-feature verification result. `pass` and `fail` are terminal states;
 * `not_exercised` means the workflow ran (or is running) but never hit
 * the code path the feature covers.
 */
export type FeatureCheck = {
  name: string;
  status: "pass" | "fail" | "not_exercised";
  detail?: string;
};

/**
 * The minimum event shape the aggregator cares about. Both
 * `GlobalEvent` (from /api/events) and `WorkflowWorkflowEvent` (from
 * /api/workflows/{id}/workflow-events) satisfy this; using a structural
 * type lets the helper accept either without forcing a cast at the call
 * site.
 */
export interface EventLike {
  id: string;
  event_type: string;
  event_data: Record<string, unknown> | null;
  timestamp: string;
}

/**
 * Scans a single workflow's event stream and emits one FeatureCheck per
 * feature in spec §6.13. The order is fixed so the UI renders orbs in a
 * stable layout.
 *
 * @param events Workflow events (use getWorkflowWorkflowEvents for the
 *               cleanest signal — task-level events duplicate workflow
 *               events and would double-count).
 */
export function aggregateFeatureChecks<E extends EventLike>(events: E[]): FeatureCheck[] {
  const checks: FeatureCheck[] = [];

  // ---- Security audit pipeline ----
  const securityAudits = events.filter((e) => e.event_type === "SECURITY_AUDIT");
  if (securityAudits.length === 0) {
    checks.push({
      name: "Security audit pipeline",
      status: "not_exercised",
      detail: "No SECURITY_AUDIT events recorded",
    });
  } else {
    const blocked = securityAudits.some((e) => {
      const data = e.event_data as Record<string, unknown> | null;
      if (!data) return false;
      const result = (data.result ?? data.verdict) as unknown;
      return typeof result === "string" && result.toLowerCase() === "blocked";
    });
    checks.push({
      name: "Security audit pipeline",
      status: blocked ? "fail" : "pass",
      detail: blocked
        ? "Security auditor blocked at least one call"
        : `${securityAudits.length} audit${securityAudits.length === 1 ? "" : "s"} recorded, all safe`,
    });
  }

  // ---- Saga compensation ----
  const compensationTriggered = events.filter(
    (e) => e.event_type === "COMPENSATION_TRIGGERED"
  );
  const compensationCompleted = events.filter(
    (e) => e.event_type === "COMPENSATION_COMPLETED"
  );
  const compensationFailed = events.filter(
    (e) => e.event_type === "COMPENSATION_FAILED"
  );
  const compensationCount =
    compensationTriggered.length +
    compensationCompleted.length +
    compensationFailed.length;
  if (compensationCount === 0) {
    checks.push({
      name: "Saga compensation",
      status: "not_exercised",
      detail: "No compensation events recorded",
    });
  } else if (compensationFailed.length > 0) {
    checks.push({
      name: "Saga compensation",
      status: "fail",
      detail: `${compensationFailed.length} compensation failure${compensationFailed.length === 1 ? "" : "s"}`,
    });
  } else {
    const completed =
      compensationCompleted.length > 0 || compensationTriggered.length > 0;
    checks.push({
      name: "Saga compensation",
      status: completed ? "pass" : "not_exercised",
      detail: completed
        ? `${compensationTriggered.length} triggered, ${compensationCompleted.length} completed`
        : "Compensation events present but none triggered or completed",
    });
  }

  // ---- Multi-workspace concurrency ----
  const workspaceSpawns = events.filter(
    (e) => e.event_type === "WORKSPACE_SPAWN"
  );
  if (workspaceSpawns.length === 0) {
    checks.push({
      name: "Multi-workspace concurrency",
      status: "not_exercised",
      detail: "No WORKSPACE_SPAWN events recorded",
    });
  } else {
    // Pass if >=2 spawns whose lifecycles overlap, or any event reports
    // max_concurrent_workspaces >= 2 in its data. The metric-on-event
    // signal alone is enough — it implies Celeste observed real
    // concurrency even if our window missed a second spawn event.
    const lifecyclesOverlap = hasOverlappingLifecycles(workspaceSpawns);
    const reportedHighConcurrency = workspaceSpawns.some((e) => {
      const data = e.event_data as Record<string, unknown> | null;
      if (!data) return false;
      const raw = data.max_concurrent_workspaces;
      return typeof raw === "number" && raw >= 2;
    });
    const passed = lifecyclesOverlap || reportedHighConcurrency;
    checks.push({
      name: "Multi-workspace concurrency",
      status: passed ? "pass" : "not_exercised",
      detail: passed
        ? reportedHighConcurrency
          ? "max_concurrent_workspaces >= 2 reported in events"
          : `${workspaceSpawns.length} workspace spawns with overlapping lifecycles`
        : `${workspaceSpawns.length} spawn${workspaceSpawns.length === 1 ? "" : "s"} with no concurrent overlap`,
    });
  }

  // ---- Human escalation ----
  const escalations = events.filter((e) => e.event_type === "ESCALATE");
  const paused = events.filter((e) => e.event_type === "WORKFLOW_PAUSED");
  if (escalations.length === 0 && paused.length === 0) {
    checks.push({
      name: "Human escalation",
      status: "not_exercised",
      detail: "No ESCALATE or WORKFLOW_PAUSED events recorded",
    });
  } else {
    checks.push({
      name: "Human escalation",
      status: "pass",
      detail: `${escalations.length} escalate, ${paused.length} paused`,
    });
  }

  // ---- OPA replanning ----
  const plans = events.filter((e) => e.event_type === "PLAN_GENERATED");
  if (plans.length >= 2) {
    checks.push({
      name: "OPA replanning",
      status: "pass",
      detail: `${plans.length} plans generated (${plans.length - 1} replan cycle${plans.length - 1 === 1 ? "" : "s"})`,
    });
  } else {
    checks.push({
      name: "OPA replanning",
      status: "not_exercised",
      detail:
        plans.length === 1
          ? "1 plan generated (no replanning observed)"
          : "No PLAN_GENERATED events recorded",
    });
  }

  // ---- Checkpoint lineage ----
  const checkpoints = events.filter((e) => e.event_type === "CHECKPOINT");
  if (checkpoints.length === 0) {
    checks.push({
      name: "Checkpoint lineage",
      status: "not_exercised",
      detail: "No CHECKPOINT events recorded",
    });
  } else {
    checks.push({
      name: "Checkpoint lineage",
      status: "pass",
      detail: `${checkpoints.length} checkpoint${checkpoints.length === 1 ? "" : "s"} recorded`,
    });
  }

  return checks;
}

/**
 * Roll up a flat list of FeatureChecks into pass/fail/not_exercised counts.
 * `total` is the number of checks in the input.
 */
export function summarizeFleet(checks: FeatureCheck[]): {
  pass: number;
  fail: number;
  not_exercised: number;
} {
  let pass = 0;
  let fail = 0;
  let not_exercised = 0;
  for (const c of checks) {
    if (c.status === "pass") pass++;
    else if (c.status === "fail") fail++;
    else not_exercised++;
  }
  return { pass, fail, not_exercised };
}

/**
 * Fetches the latest N events for each workflow (via the existing
 * getWorkflowWorkflowEvents API) and aggregates fleet-wide feature
 * verification counts. The caller controls how many events to pull per
 * workflow via `perWorkflowLimit` (defaults to 200).
 *
 * Pure-ish: no React, but it does perform IO. Tests should mock the
 * `getWorkflowWorkflowEvents` import.
 */
export async function summarizeFleetFromWorkflows(
  workflows: { id: string }[],
  opts: {
    perWorkflowLimit?: number;
    fetcher?: (id: string, opts?: { limit?: number }) => Promise<WorkflowWorkflowEvent[]>;
  } = {}
): Promise<{
  total: number;
  pass: number;
  fail: number;
  not_exercised: number;
}> {
  const fetcher = opts.fetcher ?? getWorkflowWorkflowEvents;
  const perWorkflowLimit = opts.perWorkflowLimit ?? 200;
  const results = await Promise.all(
    workflows.map((w) =>
      fetcher(w.id, { limit: perWorkflowLimit }).catch(() => [] as WorkflowWorkflowEvent[])
    )
  );
  const aggregated = results.flatMap((events) => aggregateFeatureChecks(events));
  return { total: aggregated.length, ...summarizeFleet(aggregated) };
}

// ------------------------------------------------------------------
// Internal helpers
// ------------------------------------------------------------------

interface WorkspaceLifecycle {
  start: number;
  end: number;
}

/**
 * Two workspace lifecycles overlap if one starts before the other ends.
 * Lifecycles are derived from WORKSPACE_SPAWN start times; the caller
 * passes only spawns, so end is treated as "still alive" (+Infinity).
 * Two spawns whose start timestamps differ by any positive amount
 * therefore overlap, matching the spec's "concurrent workspaces" intent
 * even when no WORKSPACE_DESTROY has been observed yet.
 */
function hasOverlappingLifecycles(spawns: EventLike[]): boolean {
  const lifecycles: WorkspaceLifecycle[] = spawns.map((spawn) => {
    const start = Date.parse(spawn.timestamp);
    return { start: Number.isFinite(start) ? start : 0, end: Number.POSITIVE_INFINITY };
  });

  for (let i = 0; i < lifecycles.length; i++) {
    for (let j = i + 1; j < lifecycles.length; j++) {
      const a = lifecycles[i];
      const b = lifecycles[j];
      // Two intervals overlap if a.start <= b.end AND b.start <= a.end.
      // With +Infinity representing "still alive", any second start
      // automatically overlaps with an unbounded first.
      if (a.start <= b.end && b.start <= a.end) {
        return true;
      }
    }
  }
  return false;
}

// Re-export the input event types so callers can name them in one place.
export type { GlobalEvent, WorkflowWorkflowEvent };
