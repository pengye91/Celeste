"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Minimal Server-Sent Events hook.
 *
 * - Uses native `EventSource` with auto-reconnect (exponential backoff
 *   1s -> 2s -> 4s -> 8s -> 16s -> 30s ceiling).
 * - No-op when `url` is null, when `enabled` is false, or when
 *   `EventSource` is undefined (jsdom).
 * - Cleans up on unmount and when `url` / `enabled` change.
 * - Re-exposes a `reconnect()` function for manual resets.
 *
 * Returned `data` is the last parsed event payload. Parsing is best-effort
 * JSON: text frames starting with `{`, `[`, or `"` are parsed; otherwise
 * the raw `data` string is returned.
 */

export interface UseSSEOptions {
  /** Set to false to skip opening a connection. Defaults to true. */
  enabled?: boolean;
  /**
   * Custom event name to subscribe to. Defaults to "message", which fires
   * for unnamed events.
   */
  eventName?: string;
  /**
   * Called once on every parsed event. Useful for side effects without
   * forcing the parent to track the `data` value.
   */
  onEvent?: (payload: SSEPayload) => void;
  /**
   * Called when the underlying connection errors. Receives the raw Event.
   */
  onError?: (err: Event) => void;
}

export type SSEPayload = unknown;

export interface UseSSEResult {
  data: SSEPayload | null;
  isConnected: boolean;
  error: Event | null;
  /** Manual reset signal — bump the value to force a fresh connection. */
  reconnect: () => void;
}

const MIN_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30_000;

function parsePayload(raw: string): SSEPayload {
  if (raw.length === 0) return null;
  const first = raw[0];
  if (first !== "{" && first !== "[" && first !== '"') return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function getEventSourceCtor(): typeof EventSource | undefined {
  if (typeof window === "undefined") return undefined;
  return window.EventSource;
}

export function useSSE(url: string | null, opts: UseSSEOptions = {}): UseSSEResult {
  const { enabled = true, eventName = "message", onEvent, onError } = opts;
  const [data, setData] = useState<SSEPayload | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Event | null>(null);
  // Bump this to force a fresh connection from the parent.
  const [resetCounter, setResetCounter] = useState(0);

  // Refs hold the latest callbacks so the connection effect doesn't
  // have to re-run when the parent passes new function identities.
  const handlersRef = useRef({ onEvent, onError });
  useEffect(() => {
    handlersRef.current = { onEvent, onError };
  }, [onEvent, onError]);

  useEffect(() => {
    const EventSourceCtor = getEventSourceCtor();
    if (!url) return;
    if (!enabled) return;
    if (!EventSourceCtor) return; // jsdom / SSR

    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let backoff = MIN_BACKOFF_MS;
    let cancelled = false;

    const open = () => {
      if (cancelled) return;
      try {
        source = new EventSourceCtor(url);
      } catch (err) {
        // Construction failures (invalid URL, etc.) are not recoverable
        // by reconnect. Surface the error and stop.
        setError(err as Event);
        setIsConnected(false);
        return;
      }

      source.onopen = () => {
        if (cancelled) return;
        setIsConnected(true);
        setError(null);
        backoff = MIN_BACKOFF_MS;
      };

      const handleMessage = (event: MessageEvent) => {
        if (cancelled) return;
        const payload = parsePayload(event.data);
        setData(payload);
        const handlers = handlersRef.current;
        if (handlers.onEvent) handlers.onEvent(payload);
      };

      if (eventName === "message") {
        // Cast: the EventSource `onmessage` typing uses `this: EventSource`,
        // but our handler is a plain function. Suppress the variance issue.
        (source as unknown as { onmessage: ((ev: Event) => void) | null }).onmessage =
          handleMessage as unknown as (ev: Event) => void;
      } else {
        source.addEventListener(eventName, handleMessage as EventListener);
      }

      source.onerror = (event: Event) => {
        if (cancelled) return;
        setIsConnected(false);
        setError(event);
        const handlers = handlersRef.current;
        if (handlers.onError) handlers.onError(event);

        if (source && source.readyState === EventSourceCtor.CLOSED) {
          // Schedule a reconnect with exponential backoff.
          const delay = Math.min(backoff, MAX_BACKOFF_MS);
          backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
          reconnectTimer = setTimeout(() => {
            if (cancelled) return;
            open();
          }, delay);
        }
      };
    };

    open();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (source) {
        try {
          source.close();
        } catch {
          // EventSource.close can throw if the source is already closed;
          // ignore.
        }
        source = null;
      }
      setIsConnected(false);
    };
  }, [url, enabled, eventName, resetCounter]);

  const reconnect = useCallback(() => {
    setResetCounter((n) => n + 1);
  }, []);

  return { data, isConnected, error, reconnect };
}
