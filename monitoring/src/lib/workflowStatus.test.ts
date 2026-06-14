import { describe, it, expect } from "vitest";
import {
  getStatusVariant,
  statusOrbVariant,
  statusBadgeVariant,
  isAlertStatus,
  isLiveStatus,
  ALERT_STATUSES,
  LIVE_STATUSES,
} from "@/lib/workflowStatus";

// ------------------------------------------------------------------
// Regression coverage for the escalated-status rendering bug.
//
// Before the centralized workflowStatus helper, each page inlined its own
// `status === "running" ? ... : "idle"` ternary chain that silently
// dropped any status it did not enumerate. "escalated" — a terminal,
// needs-attention status the engine persists (see WorkflowStatus.ESCALATED
// in database/models.py) — rendered as a benign grey "idle" orb + "muted"
// badge across the dashboard, list, and detail pages, and never surfaced in
// the AlertFlare. These tests pin the canonical mapping so it cannot drift
// back: every known status resolves to a deliberate variant, escalated is
// treated as error/danger + an alert status, and unknown statuses degrade
// gracefully instead of throwing.
// ------------------------------------------------------------------

describe("getStatusVariant", () => {
  it("maps running to a live/green orb + success badge", () => {
    expect(getStatusVariant("running")).toEqual({ orb: "running", badge: "success" });
  });

  it("maps completed to success", () => {
    expect(getStatusVariant("completed")).toEqual({ orb: "success", badge: "success" });
  });

  it("maps failed to error/danger", () => {
    expect(getStatusVariant("failed")).toEqual({ orb: "error", badge: "danger" });
  });

  // The core regression: escalated must NOT fall through to idle/muted.
  it("maps escalated to error/danger (terminal, needs attention)", () => {
    const v = getStatusVariant("escalated");
    expect(v.orb).toBe("error");
    expect(v.badge).toBe("danger");
  });

  it("maps paused to warning (resumable/waiting)", () => {
    expect(getStatusVariant("paused")).toEqual({ orb: "warning", badge: "warning" });
  });

  it("maps pending to idle/muted", () => {
    expect(getStatusVariant("pending")).toEqual({ orb: "idle", badge: "muted" });
  });

  it("maps cancelled to info", () => {
    expect(getStatusVariant("cancelled")).toEqual({ orb: "info", badge: "info" });
  });

  it("falls back to idle/muted for an unknown status (graceful degradation)", () => {
    expect(getStatusVariant("some-future-status")).toEqual({ orb: "idle", badge: "muted" });
  });

  it("covers every canonical WorkflowStatus (no status unmapped)", () => {
    // If this fails, a new status was added to the WorkflowStatus union
    // without a mapping — add it to STATUS_VARIANTS in workflowStatus.ts.
    const all: Array<string> = [
      "pending",
      "running",
      "completed",
      "failed",
      "paused",
      "escalated",
      "cancelled",
    ];
    for (const s of all) {
      const v = getStatusVariant(s);
      expect(v.orb, `orb for ${s}`).toBeTruthy();
      expect(v.badge, `badge for ${s}`).toBeTruthy();
    }
  });
});

describe("statusOrbVariant / statusBadgeVariant", () => {
  it("statusOrbVariant returns just the orb", () => {
    expect(statusOrbVariant("escalated")).toBe("error");
    expect(statusOrbVariant("running")).toBe("running");
  });

  it("statusBadgeVariant returns just the badge", () => {
    expect(statusBadgeVariant("escalated")).toBe("danger");
    expect(statusBadgeVariant("paused")).toBe("warning");
  });
});

describe("isAlertStatus", () => {
  // The AlertFlare used to miss escalated entirely — an escalated workflow
  // (the human-attention terminal state) never appeared in alerts.
  it("includes failed, escalated, and paused", () => {
    expect(isAlertStatus("failed")).toBe(true);
    expect(isAlertStatus("escalated")).toBe(true);
    expect(isAlertStatus("paused")).toBe(true);
  });

  it("excludes benign / running statuses", () => {
    expect(isAlertStatus("running")).toBe(false);
    expect(isAlertStatus("completed")).toBe(false);
    expect(isAlertStatus("pending")).toBe(false);
    expect(isAlertStatus("cancelled")).toBe(false);
  });

  it("ALERT_STATUSES set matches the predicate", () => {
    expect(ALERT_STATUSES.has("escalated")).toBe(true);
  });
});

describe("isLiveStatus", () => {
  it("treats running and pending as live", () => {
    expect(isLiveStatus("running")).toBe(true);
    expect(isLiveStatus("pending")).toBe(true);
  });

  it("treats terminal statuses as not live", () => {
    expect(isLiveStatus("completed")).toBe(false);
    expect(isLiveStatus("failed")).toBe(false);
    expect(isLiveStatus("escalated")).toBe(false);
    expect(isLiveStatus("paused")).toBe(false);
    expect(isLiveStatus("cancelled")).toBe(false);
  });

  it("LIVE_STATUSES set matches the predicate", () => {
    expect(LIVE_STATUSES.has("running")).toBe(true);
    expect(LIVE_STATUSES.has("escalated")).toBe(false);
  });
});
