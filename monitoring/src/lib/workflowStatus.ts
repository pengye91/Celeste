import type { WorkflowStatus } from "@/lib/types";

// ------------------------------------------------------------------
// Canonical workflow-status -> presentation mapping.
//
// Every page that renders a workflow status badge/orb MUST go through
// these helpers instead of inlining its own ternary chain. The old
// pattern (a per-page `status === "running" ? ... : "idle"` ladder)
// silently dropped new statuses — e.g. "escalated" rendered as a benign
// grey "idle" orb across the dashboard, list, and detail pages even
// though the engine persists it as a terminal, needs-attention state.
// Centralizing the mapping here means adding a status is a one-file
// change and no page can forget it.
// ------------------------------------------------------------------

/** StatusOrb variant names (mirrors the component's full variant set). */
export type StatusOrbVariant =
  | "idle"
  | "running"
  | "success"
  | "warning"
  | "error"
  | "info";

/** Badge variant names that make sense for a workflow status. */
export type StatusBadgeVariant =
  | "success"
  | "default"
  | "danger"
  | "warning"
  | "muted"
  | "info";

export interface StatusVariant {
  orb: StatusOrbVariant;
  badge: StatusBadgeVariant;
}

/**
 * Presentation mapping for each canonical workflow status.
 *
 * - running   -> live/green (aurora)
 * - completed -> success (aurora)
 * - failed    -> error/danger (mars/red) — terminal, crashed
 * - escalated -> error/danger (mars/red) — terminal, exhausted a safety
 *   limit and escalated out-of-band. Same severity as failed (it is a
 *   terminal problem state) but distinguished from `paused` (which is
 *   resumable/waiting, hence warning/amber). The text label tells them
 *   apart; the color signals "needs attention".
 * - paused    -> warning/amber (solar) — waiting, resumable
 * - pending   -> muted — not started
 * - cancelled -> info — intentionally stopped
 *
 * Any unknown status falls back to idle/muted rather than throwing, so a
 * brand-new backend status degrades gracefully instead of breaking the UI.
 */
const STATUS_VARIANTS: Record<WorkflowStatus, StatusVariant> = {
  running: { orb: "running", badge: "success" },
  completed: { orb: "success", badge: "success" },
  failed: { orb: "error", badge: "danger" },
  escalated: { orb: "error", badge: "danger" },
  paused: { orb: "warning", badge: "warning" },
  pending: { orb: "idle", badge: "muted" },
  cancelled: { orb: "info", badge: "info" },
};

const FALLBACK: StatusVariant = { orb: "idle", badge: "muted" };

/** Returns the canonical {orb, badge} pair for a workflow status string. */
export function getStatusVariant(status: string): StatusVariant {
  return STATUS_VARIANTS[status as WorkflowStatus] ?? FALLBACK;
}

/** Returns the StatusOrb variant for a workflow status. */
export function statusOrbVariant(status: string): StatusOrbVariant {
  return getStatusVariant(status).orb;
}

/** Returns the Badge variant for a workflow status. */
export function statusBadgeVariant(status: string): StatusBadgeVariant {
  return getStatusVariant(status).badge;
}

/**
 * Statuses that represent a problem requiring human attention. Used by
 * alert/flare surfaces (e.g. the dashboard AlertFlare). Terminal failure
 * states plus the resumable-waiting `paused` state.
 */
export const ALERT_STATUSES: ReadonlySet<string> = new Set([
  "failed",
  "escalated",
  "paused",
]);

/** True if the status should surface in an alert/flare list. */
export function isAlertStatus(status: string): boolean {
  return ALERT_STATUSES.has(status);
}

/**
 * Statuses that are still in flight (not terminal). Used to decide whether
 * to poll / pulse the orb / show a live indicator.
 */
export const LIVE_STATUSES: ReadonlySet<string> = new Set([
  "running",
  "pending",
]);

/** True if the status is live (may still change). */
export function isLiveStatus(status: string): boolean {
  return LIVE_STATUSES.has(status);
}
