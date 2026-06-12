import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWorkflowStatus } from "@/hooks/useWorkflow";
import React from "react";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(
      QueryClientProvider,
      { client: queryClient },
      children
    );
  };
}

describe("useWorkflowStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          workflow_id: "wf-1",
          status: "running",
          nodes: [],
          progress: 0.5,
        }),
      })
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("polls while workflow is running", async () => {
    const { result } = renderHook(() => useWorkflowStatus("wf-1"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.data?.status).toBe("running"));

    // Advance 1500ms — should trigger another fetch
    vi.advanceTimersByTime(1500);
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("stops polling when workflow is completed", async () => {
    let status = "running";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            workflow_id: "wf-1",
            status,
            nodes: [],
            progress: status === "running" ? 0.5 : 1,
          }),
        })
      )
    );

    const { result } = renderHook(() => useWorkflowStatus("wf-1"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.data?.status).toBe("running"));

    // Change status to completed
    status = "completed";

    // Advance past a polling cycle
    vi.advanceTimersByTime(2000);
    await waitFor(() => expect(result.current.data?.status).toBe("completed"));

    const callCount = vi.mocked(fetch).mock.calls.length;

    // Advance another 3s — should NOT trigger more fetches because refetchInterval returns false
    vi.advanceTimersByTime(3000);
    await waitFor(() =>
      expect(vi.mocked(fetch).mock.calls.length).toBe(callCount)
    );
  });
});
