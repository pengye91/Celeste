import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSSE } from "@/hooks/useSSE";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  readyState: number;
  static OPEN = 1;
  static CLOSED = 2;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  private listeners: Record<string, EventListener> = {};
  closed = false;

  constructor(url: string) {
    this.url = url;
    this.readyState = MockEventSource.OPEN;
    MockEventSource.instances.push(this);
  }

  addEventListener(name: string, handler: EventListener) {
    this.listeners[name] = handler;
  }
  removeEventListener(name: string) {
    delete this.listeners[name];
  }
  close() {
    this.closed = true;
    this.readyState = MockEventSource.CLOSED;
  }

  // Test helpers
  emitMessage(data: string) {
    const event = { data } as MessageEvent;
    if (this.onmessage) (this.onmessage as unknown as (e: Event) => void)(event as unknown as Event);
    const handler = this.listeners["message"];
    if (handler) handler(event as unknown as Event);
  }
  emitOpen() {
    if (this.onopen) this.onopen(new Event("open"));
  }
  emitError() {
    if (this.onerror) this.onerror(new Event("error"));
  }
}

describe("useSSE", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    // Replace the global EventSource. Our hook reads `window.EventSource`
    // inside `getEventSourceCtor`, so we set both for safety.
    (globalThis as unknown as Record<string, unknown>).EventSource =
      MockEventSource as unknown as typeof EventSource;
    (window as unknown as Record<string, unknown>).EventSource =
      MockEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    delete (globalThis as unknown as Record<string, unknown>).EventSource;
    delete (window as unknown as Record<string, unknown>).EventSource;
  });

  it("does not open a connection when url is null", () => {
    renderHook(() => useSSE(null));
    expect(MockEventSource.instances).toHaveLength(0);
  });

  it("does not open a connection when enabled is false", () => {
    renderHook(() => useSSE("/api/sse", { enabled: false }));
    expect(MockEventSource.instances).toHaveLength(0);
  });

  it("opens a connection when url is provided", () => {
    renderHook(() => useSSE("/api/events"));
    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0].url).toBe("/api/events");
  });

  it("cleans up on unmount", () => {
    const { unmount } = renderHook(() => useSSE("/api/events"));
    expect(MockEventSource.instances).toHaveLength(1);
    const source = MockEventSource.instances[0];
    unmount();
    expect(source.closed).toBe(true);
  });

  it("parses JSON payloads and surfaces them as data", () => {
    const { result } = renderHook(() => useSSE("/api/events"));
    act(() => {
      MockEventSource.instances[0].emitOpen();
      MockEventSource.instances[0].emitMessage(JSON.stringify({ id: 1, name: "evt" }));
    });
    expect(result.current.data).toEqual({ id: 1, name: "evt" });
    expect(result.current.isConnected).toBe(true);
  });

  it("leaves raw text payloads alone", () => {
    const { result } = renderHook(() => useSSE("/api/events"));
    act(() => {
      MockEventSource.instances[0].emitMessage("plain text");
    });
    expect(result.current.data).toBe("plain text");
  });

  it("cleans up when the URL changes", () => {
    const { rerender } = renderHook(
      ({ url }: { url: string | null }) => useSSE(url),
      { initialProps: { url: "/api/events" } }
    );
    expect(MockEventSource.instances).toHaveLength(1);
    const first = MockEventSource.instances[0];
    rerender({ url: "/api/events-other" });
    expect(first.closed).toBe(true);
    expect(MockEventSource.instances).toHaveLength(2);
  });
});
