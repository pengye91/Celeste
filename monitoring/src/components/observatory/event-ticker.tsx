"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Activity from "lucide-react/dist/esm/icons/activity";
import AlertCircle from "lucide-react/dist/esm/icons/alert-circle";
import Radio from "lucide-react/dist/esm/icons/radio";
import RefreshCw from "lucide-react/dist/esm/icons/refresh-cw";
import type { GlobalEvent } from "@/lib/types";
import { formatRelativeTime, formatTimestamp } from "@/lib/format";
import { EmptyObservatoryIllustration } from "./empty-observatory-illustration";
import { EventSkeleton } from "./event-skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { cn } from "@/lib/utils";

interface EventTickerProps {
  events: GlobalEvent[] | null | undefined;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

/**
 * Decide how to color-code a single event row. The palette is the same
 * one used elsewhere in the app (aurora / solar / mars / nebula) so
 * the observatory feels like one instrument rather than a one-off page.
 */
function eventAccent(eventType: string): {
  dot: string;
  pill: string;
  text: string;
} {
  const et = eventType.toUpperCase();
  if (et.includes("FAIL") || et.includes("ERROR") || et.includes("BLOCKED") || et.includes("CANCEL")) {
    return {
      dot: "bg-mars-500",
      pill: "bg-mars-500/10 text-mars-400 border-mars-500/30",
      text: "text-mars-400",
    };
  }
  if (et.includes("PAUSE") || et.includes("ESCALAT") || et.includes("REPLAN")) {
    return {
      dot: "bg-solar-500",
      pill: "bg-solar-500/10 text-solar-400 border-solar-500/30",
      text: "text-solar-400",
    };
  }
  if (et.includes("AUDIT") || et.includes("CHECKPOINT") || et.includes("PLAN")) {
    return {
      dot: "bg-nebula-500",
      pill: "bg-nebula-500/10 text-nebula-400 border-nebula-500/30",
      text: "text-nebula-400",
    };
  }
  return {
    dot: "bg-aurora-500",
    pill: "bg-aurora-500/10 text-aurora-400 border-aurora-500/30",
    text: "text-aurora-400",
  };
}

/**
 * Build a short, single-line preview of the event_data payload. We
 * deliberately don't try to fully render the JSON — the ticker is
 * glanceable, the detail page is deep.
 */
function previewEventData(data: GlobalEvent["event_data"]): string {
  if (!data) return "—";
  try {
    const keys = Object.keys(data);
    if (keys.length === 0) return "—";
    const parts: string[] = [];
    for (const k of keys.slice(0, 3)) {
      const v = data[k];
      if (v === null || v === undefined) continue;
      let rendered: string;
      if (typeof v === "string") rendered = v.length > 40 ? v.slice(0, 40) + "…" : v;
      else if (typeof v === "number" || typeof v === "boolean") rendered = String(v);
      else rendered = JSON.stringify(v).slice(0, 40);
      parts.push(`${k}=${rendered}`);
    }
    if (parts.length === 0) return "—";
    return parts.join(" · ");
  } catch {
    return "(unserializable)";
  }
}

export function EventTicker({ events, isLoading, error, refetch }: EventTickerProps) {
  // ---- Loading state ----
  if (isLoading) {
    return (
      <section
        aria-label="Event stream loading"
        className="space-y-3"
      >
        <div className="flex items-center gap-2 text-sm text-comet-500">
          <span
            className="inline-block h-2 w-2 rounded-full bg-aurora-500 animate-pulse"
            aria-hidden="true"
          />
          <span>Connecting to event stream…</span>
        </div>
        <EventSkeleton rows={6} />
      </section>
    );
  }

  // ---- Error state ----
  if (error) {
    return (
      <section
        role="alert"
        aria-label="Event stream disconnected"
        className="rounded-lg border border-mars-500/30 bg-mars-900/10 p-6"
      >
        <div className="flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-mars-400 shrink-0 mt-0.5" aria-hidden="true" />
          <div className="flex-1 space-y-2">
            <p className="text-mars-400 text-sm font-medium">
              Disconnected from event stream
            </p>
            <p className="text-comet-500 text-xs font-mono break-all">
              {error instanceof Error ? error.message : "Unknown error"}
            </p>
            <button
              type="button"
              onClick={refetch}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-sm border border-mars-500/40",
                "bg-mars-500/10 px-3 py-1.5 text-xs text-mars-400",
                "hover:bg-mars-500/20 transition-colors",
                "focus:outline-none focus:ring-2 focus:ring-aurora-500/50"
              )}
            >
              <RefreshCw className="w-3 h-3" aria-hidden="true" />
              Reconnect
            </button>
          </div>
        </div>
      </section>
    );
  }

  // ---- Empty state ----
  if (!events || events.length === 0) {
    return (
      <section
        aria-label="No recent events"
        className="rounded-lg border border-space-600 bg-space-800/40 p-8"
      >
        <EmptyState
          icon={<EmptyObservatoryIllustration />}
          title="No events in the last hour"
          description="The observatory is listening on /api/events with a 3s refresh. Activity will appear here as soon as Celeste emits."
        />
      </section>
    );
  }

  // ---- Success / partial state ----
  return (
    <LiveTicker
      events={events}
    />
  );
}

/**
 * Live ticker. Handles:
 * - Debounced aria-live announcements (every 5s, count of new events
 *   only — never the event content).
 * - prefers-reduced-motion override (CSS handles the no-animation
 *   branch; we just keep updates instant).
 */
function LiveTicker({ events }: { events: GlobalEvent[] }) {
  const [announcement, setAnnouncement] = useState<string>("");
  // Initialise refs lazily. The initial values must be pure; the
  // first effect below sets the timestamp.
  const lastSeenIdsRef = useRef<Set<string> | null>(null);
  if (lastSeenIdsRef.current === null) {
    lastSeenIdsRef.current = new Set(events.map((e) => e.id));
  }
  const newSinceLastAnnounceRef = useRef<number>(0);
  const lastAnnounceAtRef = useRef<number>(0);

  // Update "new" tracking whenever the events array changes. Also
  // seeds the announce timestamp on first mount.
  useEffect(() => {
    if (lastAnnounceAtRef.current === 0) {
      lastAnnounceAtRef.current = Date.now();
    }
    if (lastSeenIdsRef.current === null) return;
    const currentIds = new Set(events.map((e) => e.id));
    let newCount = 0;
    for (const id of currentIds) {
      if (!lastSeenIdsRef.current.has(id)) newCount++;
    }
    if (newCount > 0) {
      newSinceLastAnnounceRef.current += newCount;
    }
    lastSeenIdsRef.current = currentIds;
  }, [events]);

  // Debounced announcement: every 5s, summarize the batch.
  useEffect(() => {
    const interval = setInterval(() => {
      if (lastAnnounceAtRef.current === 0) return;
      const now = Date.now();
      if (now - lastAnnounceAtRef.current < 5000) return;
      const n = newSinceLastAnnounceRef.current;
      if (n > 0) {
        setAnnouncement(
          `${n} new event${n === 1 ? "" : "s"} since last update`
        );
        newSinceLastAnnounceRef.current = 0;
      } else {
        setAnnouncement("");
      }
      lastAnnounceAtRef.current = now;
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <section aria-label="Live event ticker" className="space-y-3">
      <header className="flex items-center gap-2 text-sm text-comet-400">
        <span className="relative flex items-center" aria-hidden="true">
          <span className="absolute inline-flex h-2 w-2 rounded-full bg-aurora-500 opacity-60 animate-ping" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-aurora-500" />
        </span>
        <Radio className="w-3.5 h-3.5 text-aurora-400" aria-hidden="true" />
        <span className="font-mono text-xs">LIVE</span>
        <span className="text-comet-600">·</span>
        <span className="text-xs">{events.length} events</span>
        <span
          aria-live="polite"
          aria-atomic="true"
          className="sr-only"
        >
          {announcement}
        </span>
      </header>

      <ol
        className={cn(
          // Asymmetric layout: not a 3-column grid. The ticker is one
          // vertical stream that occupies ~7/12 of the page; the
          // feature summary sits in a 5/12 column beside it.
          "divide-y divide-space-700 rounded-md border border-space-600 bg-space-800/40 overflow-hidden",
          "max-h-[640px] overflow-y-auto"
        )}
        data-testid="event-ticker-list"
      >
        {events.map((event) => {
          const accent = eventAccent(event.event_type);
          return (
            <li
              key={event.id}
              className={cn(
                "flex items-start gap-3 px-3 py-2 hover:bg-space-700/40",
                "transition-colors focus-within:bg-space-700/40"
              )}
            >
              <span
                className={cn("mt-1.5 inline-block h-2 w-2 rounded-full shrink-0", accent.dot)}
                aria-hidden="true"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={cn(
                      "font-mono text-xs px-1.5 py-0.5 rounded-sm border",
                      accent.pill
                    )}
                  >
                    {event.event_type}
                  </span>
                  <Link
                    href={`/workflows/${event.workflow_id}`}
                    className={cn(
                      "font-mono text-xs text-comet-400 hover:text-aurora-400",
                      "transition-colors focus:outline-none focus:ring-2 focus:ring-aurora-500/50 rounded-sm",
                      "truncate max-w-[200px]"
                    )}
                    title={event.workflow_id}
                  >
                    {event.workflow_id.slice(0, 12)}
                  </Link>
                  <span
                    className="text-[10px] text-comet-600 font-mono"
                    title={formatTimestamp(event.timestamp)}
                  >
                    {formatRelativeTime(event.timestamp)}
                  </span>
                </div>
                <p
                  className={cn(
                    "mt-1 text-xs text-comet-400 truncate",
                    "max-w-full"
                  )}
                >
                  {previewEventData(event.event_data)}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

// Re-export Activity icon for any caller that needs a fallback status row
export { Activity };
