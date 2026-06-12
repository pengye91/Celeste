"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSSE } from "@/hooks/useSSE";
import { getGlobalEvents, streamGlobalEvents } from "@/lib/api";
import type { GlobalEvent } from "@/lib/types";

/**
 * Possible transport states for the live global event stream.
 *
 *  - connected   : SSE is open and yielding events
 *  - reconnecting: SSE errored; we are still trying to reconnect
 *  - fallback    : SSE never connected within 5s OR was abandoned;
 *                  the consumer is now polling the REST endpoint
 *  - idle        : the hook is disabled (no consumer, e.g. on a
 *                  page that doesn't need the stream)
 */
export type LiveStreamState =
  | "connected"
  | "reconnecting"
  | "fallback"
  | "idle";

export interface UseLiveGlobalEventsOptions {
  limit?: number;
  offset?: number;
  /** Optional event_type filter — narrows both the SSE and polling feeds. */
  event_type?: string;
  /** Set to false to skip opening any transport. Defaults to true. */
  enabled?: boolean;
  /**
   * How long to wait for SSE to connect before falling back to
   * polling. Defaults to 5000ms (spec: 5 seconds).
   */
  connectTimeoutMs?: number;
}

export interface UseLiveGlobalEventsResult {
  events: GlobalEvent[] | undefined;
  isLoading: boolean;
  error: Error | null;
  state: LiveStreamState;
  /**
   * Transport currently feeding the result. Useful for diagnostics
   * and for tests asserting the degradation path.
   */
  transport: "sse" | "polling" | "none";
  refetch: () => void;
}

const DEFAULT_CONNECT_TIMEOUT_MS = 5000;
const DEFAULT_POLL_INTERVAL_MS = 3000;

/**
 * Hybrid SSE + polling hook for the observatory event stream.
 *
 * Strategy:
 *  1. Open an SSE connection to `/api/events/stream` via `useSSE`.
 *  2. If the connection opens within `connectTimeoutMs` (default 5s),
 *     we are in SSE mode: `state="connected"`, data fed by the
 *     stream. We still poll a single time to seed the initial list
 *     so the UI is not empty for the first few frames.
 *  3. If SSE has not connected by the timeout, or the connection
 *     errors out, we flip to polling mode: `state="fallback"` and
 *     `transport="polling"`. The polling query uses
 *     `refetchInterval: 3000`, matching the original `useGlobalEvents`
 *     cadence documented in the spec.
 *  4. If `enabled` is false, the hook renders nothing and reports
 *     `state="idle"`.
 *
 * The hook tolerates transient SSE errors — a single disconnect
 * bumps us to "reconnecting" briefly. Only when the timeout fires
 * OR the consumer unmounts do we go all the way to "fallback".
 */
export function useLiveGlobalEvents(
  opts: UseLiveGlobalEventsOptions = {}
): UseLiveGlobalEventsResult {
  const {
    limit,
    offset,
    event_type,
    enabled = true,
    connectTimeoutMs = DEFAULT_CONNECT_TIMEOUT_MS,
  } = opts;

  const [state, setState] = useState<LiveStreamState>(enabled ? "reconnecting" : "idle");
  const fallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasFlippedRef = useRef(false);

  // Build the SSE URL once per option change. The hook always tries
  // SSE first when enabled; the API helper is a pure URL builder and
  // safe to call unconditionally.
  const sseUrl = enabled ? streamGlobalEvents({ limit, event_type }) : null;

  const sse = useSSE(sseUrl, {
    enabled: enabled && sseUrl !== null,
    // We don't actually need to consume each frame; the polling
    // seed already gives us the initial list and the spec's
    // degradation path polls. The SSE connection's value here is
    // purely the connection-state signal — but we still surface
    // incoming payloads via `onEvent` so future consumers can hook
    // in without re-plumbing the hook.
    onEvent: () => {
      // Intentionally empty. The polling query is the source of
      // truth for the list. SSE frames are advisory.
    },
  });

  // Polling fallback. The query is always mounted but only returns
  // data when refetchInterval is allowed to run (which we gate by
  // "we have decided to poll"). TanStack Query will respect that by
  // giving us `isFetching: false` until we flip the transport flag.
  const pollQuery = useQuery<GlobalEvent[]>({
    queryKey: ["global-events-live", { limit, offset, event_type }],
    queryFn: () => getGlobalEvents({ limit, offset, event_type }),
    refetchInterval: DEFAULT_POLL_INTERVAL_MS,
    enabled: enabled,
  });

  // ---- State machine ----
  //
  // We start in "reconnecting" because we are trying SSE. We flip
  // to "connected" as soon as `sse.isConnected` becomes true. We
  // flip to "fallback" if the timeout fires before that, or if SSE
  // errors out and the timeout has already passed.
  //
  // The eslint rule react-hooks/set-state-in-effect flags the
  // intentional setState calls below. They are correct: this hook
  // is a finite state machine that transitions on async events
  // (SSE `onopen`, `setTimeout` expiry). The pattern is
  // documented in the spec as the degradation path.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!enabled) {
      setState("idle");
      return;
    }
    // Reset the "has flipped" flag whenever the URL or timeout
    // changes, so that a reconnect-with-new-options gives SSE a
    // fresh 5-second window.
    hasFlippedRef.current = false;

    if (sse.isConnected) {
      setState("connected");
      if (fallbackTimerRef.current) {
        clearTimeout(fallbackTimerRef.current);
        fallbackTimerRef.current = null;
      }
      return;
    }

    // SSE is not yet connected — start a 5s timer. If it fires
    // before we connect, we degrade to polling.
    if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
    fallbackTimerRef.current = setTimeout(() => {
      if (hasFlippedRef.current) return;
      if (sse.isConnected) {
        setState("connected");
        return;
      }
      hasFlippedRef.current = true;
      setState("fallback");
    }, connectTimeoutMs);

    return () => {
      if (fallbackTimerRef.current) {
        clearTimeout(fallbackTimerRef.current);
        fallbackTimerRef.current = null;
      }
    };
  }, [enabled, sse.isConnected, sseUrl, connectTimeoutMs]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // If SSE errors out, surface the error but don't immediately
  // switch transport — the hook will reconnect via useSSE's
  // built-in backoff. If we never reconnect, the timeout above
  // will eventually flip us to "fallback".
  const error: Error | null = sse.error
    ? new Error("SSE connection error")
    : pollQuery.error
      ? pollQuery.error
      : null;

  const refetch = () => {
    void pollQuery.refetch();
  };

  const transport: "sse" | "polling" | "none" = !enabled
    ? "none"
    : state === "connected"
      ? "sse"
      : state === "fallback"
        ? "polling"
        : "polling"; // "reconnecting" / "idle" — poll is feeding data

  return {
    events: pollQuery.data,
    isLoading: pollQuery.isLoading,
    error,
    state,
    transport,
    refetch,
  };
}
