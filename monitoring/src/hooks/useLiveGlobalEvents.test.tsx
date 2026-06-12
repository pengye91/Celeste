import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import React from "react";
import { useLiveGlobalEvents } from "./useLiveGlobalEvents";
import { useSSE } from "./useSSE";
import * as apiModule from "@/lib/api";
import type { GlobalEvent } from "@/lib/types";

// ------------------------------------------------------------------
// Mocks
// ------------------------------------------------------------------

// Mock the SSE hook so we can control connection outcomes without
// touching the real EventSource.
vi.mock("./useSSE", () => ({
  useSSE: vi.fn(),
}));

// Mock the api module. The polling branch calls getGlobalEvents; the
// SSE branch calls streamGlobalEvents. We mock both to keep this
// self-contained.
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof apiModule>("@/lib/api");
  return {
    ...actual,
    getGlobalEvents: vi.fn(),
    streamGlobalEvents: vi.fn().mockReturnValue("/api/events/stream?limit=50"),
  };
});

class MockEventSource {
  static instances: MockEventSource[] = [];
  static OPEN = 1;
  static CLOSED = 2;
  url: string;
  readyState: number;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    this.readyState = MockEventSource.OPEN;
    MockEventSource.instances.push(this);
  }
  addEventListener() {
    // no-op for the "message" default
  }
  removeEventListener() {
    // no-op
  }
  close() {
    this.closed = true;
    this.readyState = MockEventSource.CLOSED;
  }
  emitOpen() {
    if (this.onopen) this.onopen(new Event("open"));
  }
  emitError() {
    if (this.onerror) this.onerror(new Event("error"));
  }
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

const sampleEvent: GlobalEvent = {
  id: "evt-1",
  event_source: "task",
  workflow_id: "wf-alpha",
  event_type: "NODE_COMPLETED",
  event_data: { node: "n1" },
  timestamp: "2026-06-12T10:00:00Z",
};

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

describe("useLiveGlobalEvents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    MockEventSource.instances = [];
    (globalThis as unknown as Record<string, unknown>).EventSource =
      MockEventSource as unknown as typeof EventSource;
    (window as unknown as Record<string, unknown>).EventSource =
      MockEventSource as unknown as typeof EventSource;
    (apiModule.getGlobalEvents as ReturnType<typeof vi.fn>).mockResolvedValue([
      sampleEvent,
    ]);
  });

  afterEach(() => {
    delete (globalThis as unknown as Record<string, unknown>).EventSource;
    delete (window as unknown as Record<string, unknown>).EventSource;
    vi.useRealTimers();
  });

  it("returns polling data and state='fallback' when SSE is not connected within 5s", async () => {
    // Simulate a never-connecting SSE: isConnected stays false.
    (useSSE as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      data: null,
      isConnected: false,
      error: null,
      reconnect: vi.fn(),
    });

    vi.useFakeTimers();

    const { result } = renderHook(
      () => useLiveGlobalEvents({ limit: 50, connectTimeoutMs: 5000 }),
      { wrapper: makeWrapper() }
    );

    // While the 5s timer is still pending, we are "reconnecting".
    expect(result.current.state).toBe("reconnecting");
    expect(result.current.transport).toBe("polling");

    // Fire the 5s timer → flip to fallback.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(result.current.state).toBe("fallback");
    expect(result.current.transport).toBe("polling");
  });

  it("transitions to state='connected' when SSE opens before the timeout", async () => {
    let sseState = {
      data: null,
      isConnected: false,
      error: null,
      reconnect: vi.fn(),
    };
    const useSSEMock = useSSE as unknown as ReturnType<typeof vi.fn>;
    useSSEMock.mockImplementation(() => sseState);

    vi.useFakeTimers();

    const { result, rerender } = renderHook(
      () => useLiveGlobalEvents({ limit: 50, connectTimeoutMs: 5000 }),
      { wrapper: makeWrapper() }
    );

    // SSE is not yet connected.
    expect(result.current.state).toBe("reconnecting");

    // SSE connects after 1s. Update the mock and rerender so the
    // hook re-evaluates its effect with isConnected=true.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      sseState = { ...sseState, isConnected: true };
      useSSEMock.mockImplementation(() => sseState);
      rerender();
    });

    // Now state should be connected.
    expect(result.current.state).toBe("connected");
    expect(result.current.transport).toBe("sse");

    // Advance past the original 5s window — should still be connected.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(result.current.state).toBe("connected");
  });

  it("returns state='idle' and no events when enabled=false", () => {
    (useSSE as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      data: null,
      isConnected: false,
      error: null,
      reconnect: vi.fn(),
    });

    const { result } = renderHook(
      () => useLiveGlobalEvents({ enabled: false }),
      { wrapper: makeWrapper() }
    );

    expect(result.current.state).toBe("idle");
    expect(result.current.transport).toBe("none");
    expect(result.current.events).toBeUndefined();
  });

  it("surfaces the polling query's resolved data via the events field", async () => {
    (useSSE as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      data: null,
      isConnected: false,
      error: null,
      reconnect: vi.fn(),
    });
    (apiModule.getGlobalEvents as ReturnType<typeof vi.fn>).mockResolvedValue([
      sampleEvent,
    ]);

    const { result } = renderHook(
      () => useLiveGlobalEvents({ limit: 50 }),
      { wrapper: makeWrapper() }
    );

    // Drain microtasks until the query resolves. The refetchInterval
    // is gated by TanStack Query, so a single refetch() call won't
    // always update the local result.current synchronously.
    let data = result.current.events;
    for (let i = 0; i < 20 && data === undefined; i += 1) {
      await act(async () => {
        await result.current.refetch();
        await Promise.resolve();
      });
      data = result.current.events;
    }
    expect(data).toEqual([sampleEvent]);
  });

  it("uses a shorter connectTimeoutMs when configured (e.g. for tests)", async () => {
    (useSSE as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      data: null,
      isConnected: false,
      error: null,
      reconnect: vi.fn(),
    });

    vi.useFakeTimers();
    const { result } = renderHook(
      () => useLiveGlobalEvents({ connectTimeoutMs: 100 }),
      { wrapper: makeWrapper() }
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });

    expect(result.current.state).toBe("fallback");
  });
});
