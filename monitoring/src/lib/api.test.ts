import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  listWorkflows,
  getWorkflowEvents,
  cancelWorkflow,
} from "@/lib/api";

describe("listWorkflows", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("paginates with limit and offset", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        items: [{ id: "1", name: "wf1", status: "running", created_at: "2024-01-01T00:00:00Z" }],
        total: 1,
        limit: 10,
        offset: 0,
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await listWorkflows({ limit: 10, offset: 0 });
    expect(result.limit).toBe(10);
    expect(result.offset).toBe(0);
    expect(result.items).toHaveLength(1);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("limit=10"),
      expect.any(Object)
    );
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("offset=0"),
      expect.any(Object)
    );
  });

  it("filters by status", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await listWorkflows({ status: "running" });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("status=running"),
      expect.any(Object)
    );
  });
});

describe("getWorkflowEvents", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("polls with since_id for live tail", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [
        { id: "evt-2", event_type: "NODE_STARTED", event_data: null, timestamp: "2024-01-01T00:01:00Z" },
      ],
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await getWorkflowEvents("wf-1", { since_id: "evt-1", limit: 50 });
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("evt-2");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("since_id=evt-1"),
      expect.any(Object)
    );
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("limit=50"),
      expect.any(Object)
    );
  });
});

describe("cancelWorkflow", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("succeeds on 200", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ workflow_id: "wf-1", status: "cancelled" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await cancelWorkflow("wf-1");
    expect(result.status).toBe("cancelled");
  });

  it("throws conflict message on 409", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      text: async () => "Conflict",
    });
    vi.stubGlobal("fetch", mockFetch);

    await expect(cancelWorkflow("wf-1")).rejects.toThrow(
      "Workflow is already in a terminal state and cannot be cancelled."
    );
  });

  it("throws 'CMC lost contact' on 5xx", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => "Service Unavailable",
    });
    vi.stubGlobal("fetch", mockFetch);

    await expect(cancelWorkflow("wf-1")).rejects.toThrow(
      "CMC lost contact with Celeste"
    );
  });

  it("throws 'CMC lost contact' on network error", async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error("Network failure"));
    vi.stubGlobal("fetch", mockFetch);

    await expect(cancelWorkflow("wf-1")).rejects.toThrow(
      "CMC lost contact with Celeste"
    );
  });
});
