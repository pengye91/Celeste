import { describe, it, expect } from "vitest";
import {
  aggregateFeatureChecks,
  summarizeFleet,
  summarizeFleetFromWorkflows,
  type FeatureCheck,
  type WorkflowWorkflowEvent,
} from "@/lib/featureVerification";

function makeEvent(
  partial: Partial<WorkflowWorkflowEvent> & {
    event_type: string;
    timestamp: string;
  }
): WorkflowWorkflowEvent {
  return {
    id: partial.id ?? `evt-${partial.event_type}-${partial.timestamp}`,
    sequence_number: partial.sequence_number ?? 0,
    event_type: partial.event_type,
    event_data: partial.event_data ?? null,
    timestamp: partial.timestamp,
  };
}

describe("aggregateFeatureChecks", () => {
  it("returns six not_exercised checks for an empty event stream", () => {
    const checks = aggregateFeatureChecks([]);
    expect(checks).toHaveLength(6);
    expect(checks.every((c) => c.status === "not_exercised")).toBe(true);
    expect(checks.map((c) => c.name)).toEqual([
      "Security audit pipeline",
      "Saga compensation",
      "Multi-workspace concurrency",
      "Human escalation",
      "OPA replanning",
      "Checkpoint lineage",
    ]);
  });

  it("marks security audit pass when all audits are safe", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "s1",
        event_type: "SECURITY_AUDIT",
        event_data: { result: "safe" },
        timestamp: "2026-06-12T10:00:00Z",
      }),
      makeEvent({
        id: "s2",
        event_type: "SECURITY_AUDIT",
        event_data: { result: "safe" },
        timestamp: "2026-06-12T10:01:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const security = checks.find((c) => c.name === "Security audit pipeline")!;
    expect(security.status).toBe("pass");
    expect(security.detail).toContain("2 audits");
  });

  it("marks security audit fail when any audit is blocked", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "s1",
        event_type: "SECURITY_AUDIT",
        event_data: { result: "safe" },
        timestamp: "2026-06-12T10:00:00Z",
      }),
      makeEvent({
        id: "s2",
        event_type: "SECURITY_AUDIT",
        event_data: { result: "blocked" },
        timestamp: "2026-06-12T10:01:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const security = checks.find((c) => c.name === "Security audit pipeline")!;
    expect(security.status).toBe("fail");
  });

  it("marks saga compensation pass on triggered/completed", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "c1",
        event_type: "COMPENSATION_TRIGGERED",
        event_data: { node: "node-a" },
        timestamp: "2026-06-12T10:00:00Z",
      }),
      makeEvent({
        id: "c2",
        event_type: "COMPENSATION_COMPLETED",
        event_data: { node: "node-a" },
        timestamp: "2026-06-12T10:01:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const saga = checks.find((c) => c.name === "Saga compensation")!;
    expect(saga.status).toBe("pass");
  });

  it("marks saga compensation fail on any COMPENSATION_FAILED", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "c1",
        event_type: "COMPENSATION_TRIGGERED",
        event_data: {},
        timestamp: "2026-06-12T10:00:00Z",
      }),
      makeEvent({
        id: "c2",
        event_type: "COMPENSATION_FAILED",
        event_data: { error: "boom" },
        timestamp: "2026-06-12T10:01:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const saga = checks.find((c) => c.name === "Saga compensation")!;
    expect(saga.status).toBe("fail");
  });

  it("marks multi-workspace concurrency pass on overlapping spawns", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "w1",
        event_type: "WORKSPACE_SPAWN",
        event_data: { workspace_id: "ws-1" },
        timestamp: "2026-06-12T10:00:00Z",
      }),
      makeEvent({
        id: "w2",
        event_type: "WORKSPACE_SPAWN",
        event_data: { workspace_id: "ws-2" },
        timestamp: "2026-06-12T10:00:30Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const ws = checks.find((c) => c.name === "Multi-workspace concurrency")!;
    expect(ws.status).toBe("pass");
  });

  it("marks multi-workspace concurrency pass when event_data reports max_concurrent_workspaces >= 2", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "w1",
        event_type: "WORKSPACE_SPAWN",
        event_data: { workspace_id: "ws-1", max_concurrent_workspaces: 2 },
        timestamp: "2026-06-12T10:00:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const ws = checks.find((c) => c.name === "Multi-workspace concurrency")!;
    expect(ws.status).toBe("pass");
    expect(ws.detail).toContain("max_concurrent_workspaces");
  });

  it("marks multi-workspace concurrency not_exercised for a single spawn", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "w1",
        event_type: "WORKSPACE_SPAWN",
        event_data: { workspace_id: "ws-1" },
        timestamp: "2026-06-12T10:00:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const ws = checks.find((c) => c.name === "Multi-workspace concurrency")!;
    expect(ws.status).toBe("not_exercised");
  });

  it("marks human escalation pass on ESCALATE", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "e1",
        event_type: "ESCALATE",
        event_data: { reason: "need human" },
        timestamp: "2026-06-12T10:00:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const esc = checks.find((c) => c.name === "Human escalation")!;
    expect(esc.status).toBe("pass");
  });

  it("marks human escalation pass on WORKFLOW_PAUSED", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "p1",
        event_type: "WORKFLOW_PAUSED",
        event_data: {},
        timestamp: "2026-06-12T10:00:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const esc = checks.find((c) => c.name === "Human escalation")!;
    expect(esc.status).toBe("pass");
  });

  it("marks OPA replanning pass on >=2 PLAN_GENERATED events", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "p1",
        event_type: "PLAN_GENERATED",
        event_data: { cycle: 1 },
        timestamp: "2026-06-12T10:00:00Z",
      }),
      makeEvent({
        id: "p2",
        event_type: "PLAN_GENERATED",
        event_data: { cycle: 2 },
        timestamp: "2026-06-12T10:01:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const opa = checks.find((c) => c.name === "OPA replanning")!;
    expect(opa.status).toBe("pass");
    expect(opa.detail).toContain("2 plans");
  });

  it("marks OPA replanning not_exercised on exactly one PLAN_GENERATED", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "p1",
        event_type: "PLAN_GENERATED",
        event_data: { cycle: 1 },
        timestamp: "2026-06-12T10:00:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const opa = checks.find((c) => c.name === "OPA replanning")!;
    expect(opa.status).toBe("not_exercised");
  });

  it("marks checkpoint lineage pass on any CHECKPOINT event", () => {
    const events: WorkflowWorkflowEvent[] = [
      makeEvent({
        id: "k1",
        event_type: "CHECKPOINT",
        event_data: { line: "node-1" },
        timestamp: "2026-06-12T10:00:00Z",
      }),
    ];
    const checks = aggregateFeatureChecks(events);
    const cp = checks.find((c) => c.name === "Checkpoint lineage")!;
    expect(cp.status).toBe("pass");
  });
});

describe("summarizeFleet", () => {
  it("counts pass, fail, and not_exercised correctly", () => {
    const checks: FeatureCheck[] = [
      { name: "a", status: "pass" },
      { name: "b", status: "pass" },
      { name: "c", status: "fail" },
      { name: "d", status: "not_exercised" },
      { name: "e", status: "not_exercised" },
      { name: "f", status: "not_exercised" },
    ];
    expect(summarizeFleet(checks)).toEqual({ pass: 2, fail: 1, not_exercised: 3 });
  });

  it("returns zeros for an empty list", () => {
    expect(summarizeFleet([])).toEqual({ pass: 0, fail: 0, not_exercised: 0 });
  });

  it("returns zeros for an all-pass list with a not_exercised bucket of 0", () => {
    expect(
      summarizeFleet([
        { name: "x", status: "pass" },
        { name: "y", status: "pass" },
      ])
    ).toEqual({ pass: 2, fail: 0, not_exercised: 0 });
  });
});

describe("summarizeFleetFromWorkflows", () => {
  it("aggregates counts across workflows using the injected fetcher", async () => {
    const fetcher = async (id: string): Promise<WorkflowWorkflowEvent[]> => {
      if (id === "wf-a") {
        return [
          makeEvent({
            id: "a1",
            event_type: "SECURITY_AUDIT",
            event_data: { result: "safe" },
            timestamp: "2026-06-12T10:00:00Z",
          }),
          makeEvent({
            id: "a2",
            event_type: "PLAN_GENERATED",
            event_data: {},
            timestamp: "2026-06-12T10:01:00Z",
          }),
        ];
      }
      if (id === "wf-b") {
        return [
          makeEvent({
            id: "b1",
            event_type: "PLAN_GENERATED",
            event_data: {},
            timestamp: "2026-06-12T10:00:00Z",
          }),
          makeEvent({
            id: "b2",
            event_type: "PLAN_GENERATED",
            event_data: {},
            timestamp: "2026-06-12T10:01:00Z",
          }),
        ];
      }
      return [];
    };

    const summary = await summarizeFleetFromWorkflows(
      [{ id: "wf-a" }, { id: "wf-b" }],
      { fetcher }
    );

    // Each workflow yields 6 checks (12 total).
    // wf-a: 1 pass (security), 1 not_exercised (OPA — 1 plan), 4 not_exercised
    // wf-b: 1 pass (OPA — 2 plans), 5 not_exercised
    expect(summary.total).toBe(12);
    expect(summary.pass).toBe(2);
    expect(summary.fail).toBe(0);
    expect(summary.not_exercised).toBe(10);
  });

  it("treats fetcher errors as empty event streams", async () => {
    const fetcher = async (): Promise<WorkflowWorkflowEvent[]> => {
      throw new Error("network down");
    };
    const summary = await summarizeFleetFromWorkflows(
      [{ id: "wf-x" }],
      { fetcher }
    );
    // 6 checks emitted per workflow, all not_exercised.
    expect(summary.total).toBe(6);
    expect(summary.pass).toBe(0);
    expect(summary.fail).toBe(0);
    expect(summary.not_exercised).toBe(6);
  });

  it("returns zeros when given no workflows", async () => {
    const fetcher = async (): Promise<WorkflowWorkflowEvent[]> => [];
    const summary = await summarizeFleetFromWorkflows([], { fetcher });
    expect(summary).toEqual({ total: 0, pass: 0, fail: 0, not_exercised: 0 });
  });
});
