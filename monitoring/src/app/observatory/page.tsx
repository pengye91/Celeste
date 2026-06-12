"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Input } from "@/components/ui/input";
import Telescope from "lucide-react/dist/esm/icons/telescope";
import X from "lucide-react/dist/esm/icons/x";
import Filter from "lucide-react/dist/esm/icons/filter";
import { useLiveGlobalEvents } from "@/hooks/useLiveGlobalEvents";
import { useWorkflows } from "@/hooks/useWorkflow";
import { useUrlState } from "@/hooks/useUrlState";
import { summarizeFleetFromWorkflows } from "@/lib/featureVerification";
import type { FeatureCheck, WorkflowListItem, WorkflowWorkflowEvent } from "@/lib/types";
import { EventTicker } from "@/components/observatory/event-ticker";
import { FeatureVerificationSummary } from "@/components/observatory/feature-verification-summary";
import { LiveIndicator } from "@/components/observatory/live-indicator";
import { ProviderMix } from "@/components/observatory/provider-mix";

/**
 * Observatory — fleet-wide, real-time view of the CMC.
 *
 * Spec §6.13 / §6.14 / §5.3:
 *   PRIMARY  — Live event ticker (3s polling via useGlobalEvents).
 *   SECONDARY — Fleet-wide feature verification roll-up.
 *   TERTIARY  — Provider mix (only when event_data carries a key).
 *
 * Asymmetric layout: the ticker takes ~7/12 of the row, the
 * verification summary takes ~5/12. Provider mix sits below in a
 * single full-width panel. This is anti-pattern #2 from the design
 * notes (no 3-column feature grid).
 *
 * Next.js 16 requires `useSearchParams` (consumed by `useUrlState`) to
 * be rendered inside a `<Suspense>` boundary so the rest of the page
 * can still be prerendered. We split the page into a thin wrapper
 * (this component) and a body (`ObservatoryContent`) that owns the
 * URL state.
 */
export default function ObservatoryPage() {
  return (
    <Shell>
      <Suspense fallback={<ObservatoryFallback />}>
        <ObservatoryContent />
      </Suspense>
    </Shell>
  );
}

function ObservatoryFallback() {
  // Render the shell chrome so the page feels responsive even before
  // the URL state is resolved. Live indicator stays hidden because we
  // don't know whether SSE is connected yet.
  return (
    <div className="space-y-6" data-testid="observatory-fallback">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-display tracking-wide text-comet-100">
            Observatory
          </h1>
          <p className="text-sm text-comet-500 mt-1">
            Fleet-wide event stream and feature verification
          </p>
        </div>
      </header>
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-7 h-64 rounded-sm bg-space-800/40 border border-space-700 animate-pulse" />
        <div className="lg:col-span-5 h-64 rounded-sm bg-space-800/40 border border-space-700 animate-pulse" />
      </div>
    </div>
  );
}

function ObservatoryContent() {
  // URL-backed event_type filter. Empty string means "no filter".
  const [eventTypeFilter, setEventTypeFilter] = useUrlState("event_type", "");

  const {
    events,
    isLoading: eventsLoading,
    error: eventsError,
    state: liveState,
    refetch: refetchEvents,
  } = useLiveGlobalEvents({
    limit: 200,
    event_type: eventTypeFilter || undefined,
  });

  const {
    data: workflowsData,
    isLoading: workflowsLoading,
    error: workflowsError,
  } = useWorkflows({ limit: 100 });

  // The fleet summary needs to fetch per-workflow events. We do this
  // client-side, gated on the workflows list being available.
  const workflows: WorkflowListItem[] = useMemo(() => workflowsData?.items ?? [], [workflowsData]);
  const [fleet, setFleet] = useState<{
    summary: { total: number; pass: number; fail: number; not_exercised: number } | null;
    checks: FeatureCheck[];
  } | null>(null);
  const [fleetError, setFleetError] = useState<Error | null>(null);
  // The fleet-loading flag is computed from a ref + state pair so the
  // effect body never calls setState synchronously: state changes
  // only fire from inside async callbacks.
  const [inflight, setInflight] = useState<number>(0);

  useEffect(() => {
    if (workflowsLoading || workflowsError) return;
    if (workflows.length === 0) return;
    // Bump in-flight counter via a microtask so this isn't a
    // synchronous setState in the effect body. (queueMicrotask is a
    // platform API; updating React state from inside it counts as
    // async-from-React's-perspective.)
    queueMicrotask(() => setInflight((n) => n + 1));
    let cancelled = false;
    const fetcher = async (
      id: string,
      opts?: { limit?: number }
    ): Promise<WorkflowWorkflowEvent[]> => {
      const { getWorkflowWorkflowEvents } = await import("@/lib/api");
      return getWorkflowWorkflowEvents(id, opts);
    };
    summarizeFleetFromWorkflows(workflows, { perWorkflowLimit: 100, fetcher })
      .then(async (summary) => {
        if (cancelled) return;
        const { aggregateFeatureChecks } = await import("@/lib/featureVerification");
        const all = await Promise.all(
          workflows.map((w) =>
            fetcher(w.id, { limit: 100 }).catch(() => [] as WorkflowWorkflowEvent[])
          )
        );
        if (cancelled) return;
        const checks = all.flatMap((ev) => aggregateFeatureChecks(ev));
        setFleet({ summary, checks });
        setInflight((n) => Math.max(0, n - 1));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFleetError(err instanceof Error ? err : new Error(String(err)));
        setInflight((n) => Math.max(0, n - 1));
      });
    return () => {
      cancelled = true;
    };
  }, [workflows, workflowsLoading, workflowsError]);

  const fleetLoading = inflight > 0 || workflowsLoading;

  // Derive the empty-fleet state synchronously from the inputs.
  const isWorkflowsEmpty =
    !workflowsLoading && !workflowsError && workflows.length === 0;
  const fleetSummary: {
    total: number;
    pass: number;
    fail: number;
    not_exercised: number;
  } | null =
    isWorkflowsEmpty
      ? { total: 0, pass: 0, fail: 0, not_exercised: 0 }
      : fleet?.summary ?? null;
  const fleetChecks: FeatureCheck[] = isWorkflowsEmpty ? [] : fleet?.checks ?? [];

  // PARTIAL state: ticker already has data, summary is still loading.
  // SUCCESS state: both have data and no errors.
  // ERROR state: either fetch failed.
  // EMPTY state: workflows list is loaded and empty.
  // LOADING state: both fetches are still pending.
  const isTickerLoading = eventsLoading;
  const isTickerError = !!eventsError;
  const isSummaryLoading = fleetLoading || workflowsLoading;

  // For the page-level state, we want the strictest of the two:
  //   - LOADING: everything still loading
  //   - ERROR:   anything failed
  //   - EMPTY:   ticker has nothing AND fleet is empty
  //   - SUCCESS: ticker is live (with or without a populated summary)
  //   - PARTIAL: ticker is live but the summary is still computing
  let stateMode: "loading" | "empty" | "error" | "success" | "partial";
  if (isTickerError) {
    stateMode = "error";
  } else if (isTickerLoading) {
    stateMode = "loading";
  } else if (events && events.length > 0) {
    stateMode = isSummaryLoading ? "partial" : "success";
  } else {
    stateMode = isWorkflowsEmpty ? "empty" : "partial";
  }

  // We don't gate the page on isSummaryError — fleet summary is a
  // secondary signal, and the ticker should keep streaming even if
  // it fails. The summary panel itself shows the error.

  return (
    <div className="space-y-6">
      {/* Page header */}
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-display tracking-wide text-comet-100">
            Observatory
          </h1>
          <p className="text-sm text-comet-500 mt-1">
            Fleet-wide event stream and feature verification
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div
            className="relative w-56"
            role="search"
            aria-label="Filter events by type"
          >
            <Filter
              className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-comet-500"
              aria-hidden="true"
            />
            <label htmlFor="observatory-event-type" className="sr-only">
              Filter events by type
            </label>
            <Input
              id="observatory-event-type"
              placeholder="Filter by event type…"
              value={eventTypeFilter}
              onChange={(e) => setEventTypeFilter(e.target.value)}
              className="pl-8 pr-8 bg-space-800 border-space-500 text-xs h-8"
              data-testid="observatory-event-type-input"
            />
            {eventTypeFilter && (
              <button
                type="button"
                onClick={() => setEventTypeFilter("")}
                aria-label="Clear event type filter"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-comet-500 hover:text-comet-300"
              >
                <X className="w-3.5 h-3.5" aria-hidden="true" />
              </button>
            )}
          </div>
          <LiveIndicator state={liveState} />
          <Panel
            variant="subtle"
            padding="sm"
            className="flex items-center gap-2 text-xs text-comet-400"
            aria-label="Observatory status"
          >
            <Telescope className="w-3.5 h-3.5 text-aurora-400" aria-hidden="true" />
            <span className="font-mono uppercase tracking-wider text-[10px]">
              {stateMode}
            </span>
            {events && (
              <span className="text-comet-600">·</span>
            )}
            {events && (
              <span className="text-comet-500">
                {events.length} event{events.length === 1 ? "" : "s"}
              </span>
            )}
          </Panel>
        </div>
      </header>

      {/* Asymmetric layout: ticker 7/12, summary 5/12. Provider mix below. */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-7">
          <EventTicker
            events={events}
            isLoading={isTickerLoading}
            error={eventsError}
            refetch={refetchEvents}
          />
        </div>
        <div className="lg:col-span-5">
          <FeatureVerificationSummary
            loading={isSummaryLoading}
            error={fleetError ?? workflowsError ?? null}
            summary={fleetSummary}
            checks={fleetChecks}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-12">
          <ProviderMix events={events} />
        </div>
      </div>
    </div>
  );
}
