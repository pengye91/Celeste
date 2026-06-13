import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WorkspacesPage from "./page";

// ------------------------------------------------------------------
// Mocks
// ------------------------------------------------------------------

vi.mock("@/components/shell/shell", () => ({
  Shell: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="shell">{children}</div>
  ),
}));

vi.mock("@/components/workflow/workflow-nav", () => ({
  WorkflowNav: ({ activeTab }: { activeTab: string }) => (
    <nav data-testid="workflow-nav" data-active-tab={activeTab} />
  ),
}));

vi.mock("@/components/charts/workspace-chart", () => ({
  WorkspaceChart: ({ data, peakConcurrency }: { data: unknown[]; peakConcurrency?: number | null }) => (
    <div data-testid="workspace-chart" data-points={data.length} data-peak={peakConcurrency ?? "null"} />
  ),
}));

vi.mock("@/hooks/useWorkflow", () => ({
  useWorkflow: vi.fn(),
  useWorkflowMetrics: vi.fn(),
}));

vi.mock("@/hooks/useWorkflowEvents", () => ({
  useWorkflowEvents: vi.fn(),
}));

import { useWorkflow, useWorkflowMetrics } from "@/hooks/useWorkflow";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";

const mockUseWorkflow = useWorkflow as ReturnType<typeof vi.fn>;
const mockUseWorkflowMetrics = useWorkflowMetrics as ReturnType<typeof vi.fn>;
const mockUseWorkflowEvents = useWorkflowEvents as ReturnType<typeof vi.fn>;

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function mockEvents(
  spawns: { id: string; timestamp: string; event_data?: Record<string, unknown> | null }[] = [],
  destroys: { id: string; timestamp: string; event_data?: Record<string, unknown> | null }[] = []
) {
  mockUseWorkflowEvents.mockImplementation((id: string, opts?: { event_type?: string }) => {
    if (opts?.event_type === "WORKSPACE_SPAWN") {
      return {
        data: spawns.map((s) => ({
          id: s.id,
          event_type: "WORKSPACE_SPAWN",
          event_data: s.event_data ?? null,
          timestamp: s.timestamp,
        })),
        isLoading: false,
        error: null,
      };
    }
    if (opts?.event_type === "WORKSPACE_DESTROY") {
      return {
        data: destroys.map((d) => ({
          id: d.id,
          event_type: "WORKSPACE_DESTROY",
          event_data: d.event_data ?? null,
          timestamp: d.timestamp,
        })),
        isLoading: false,
        error: null,
      };
    }
    return { data: [], isLoading: false, error: null };
  });
}

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

async function renderPage(id = "wf-1") {
  const queryClient = createQueryClient();
  let result: ReturnType<typeof render> | undefined;
  await act(async () => {
    result = render(
      <QueryClientProvider client={queryClient}>
        <WorkspacesPage params={Promise.resolve({ id })} />
      </QueryClientProvider>
    );
  });
  return result!;
}

describe("WorkspacesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state", async () => {
    mockUseWorkflow.mockReturnValue({ data: null, isLoading: true, error: null });
    mockUseWorkflowMetrics.mockReturnValue({ data: null, isLoading: false, error: null });
    mockUseWorkflowEvents.mockReturnValue({ data: null, isLoading: true, error: null });

    await renderPage();

    expect(screen.getByTestId("shell")).toBeInTheDocument();
    expect(screen.getByText("Workflows")).toBeInTheDocument();
  });

  it("renders error state", async () => {
    mockUseWorkflow.mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error("Network error"),
    });
    mockUseWorkflowMetrics.mockReturnValue({ data: null, isLoading: false, error: null });
    mockUseWorkflowEvents.mockReturnValue({ data: null, isLoading: false, error: null });

    await renderPage();

    expect(screen.getByText(/Failed to load workspace data/)).toBeInTheDocument();
    expect(screen.getByText(/Network error/)).toBeInTheDocument();
  });

  it("renders empty state when no workspaces spawned", async () => {
    mockUseWorkflow.mockReturnValue({
      data: { id: "wf-1", name: "Test Workflow", status: "running" },
      isLoading: false,
      error: null,
    });
    mockUseWorkflowMetrics.mockReturnValue({
      data: { max_concurrent_workspaces: 0 },
      isLoading: false,
      error: null,
    });
    mockEvents([], []);

    await renderPage();

    expect(screen.getByText("No workspaces spawned")).toBeInTheDocument();
    expect(
      screen.getByText(/Workspaces will appear here once the workflow begins spawning them/)
    ).toBeInTheDocument();
    expect(screen.getByTestId("workflow-nav")).toHaveAttribute("data-active-tab", "workspaces");
  });

  it("shows leak alert when spawns != destroys", async () => {
    mockUseWorkflow.mockReturnValue({
      data: { id: "wf-1", name: "Test Workflow", status: "running" },
      isLoading: false,
      error: null,
    });
    mockUseWorkflowMetrics.mockReturnValue({
      data: { max_concurrent_workspaces: 2 },
      isLoading: false,
      error: null,
    });
    mockEvents(
      [
        { id: "s1", timestamp: "2024-01-01T00:00:00Z" },
        { id: "s2", timestamp: "2024-01-01T00:01:00Z" },
      ],
      [{ id: "d1", timestamp: "2024-01-01T00:02:00Z" }]
    );

    await renderPage();

    expect(screen.getByText("Workspace leak detected")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/2 workspaces spawned but only 1 destroyed/)).toBeInTheDocument();
  });

  it("does not show leak alert when spawns == destroys", async () => {
    mockUseWorkflow.mockReturnValue({
      data: { id: "wf-1", name: "Test Workflow", status: "completed" },
      isLoading: false,
      error: null,
    });
    mockUseWorkflowMetrics.mockReturnValue({
      data: { max_concurrent_workspaces: 1 },
      isLoading: false,
      error: null,
    });
    mockEvents(
      [{ id: "s1", timestamp: "2024-01-01T00:00:00Z" }],
      [{ id: "d1", timestamp: "2024-01-01T00:01:00Z" }]
    );

    await renderPage();

    expect(screen.queryByText("Workspace leak detected")).not.toBeInTheDocument();
  });

  it("renders lifecycle table with spawn and destroy rows", async () => {
    mockUseWorkflow.mockReturnValue({
      data: { id: "wf-1", name: "Test Workflow", status: "completed" },
      isLoading: false,
      error: null,
    });
    mockUseWorkflowMetrics.mockReturnValue({
      data: { max_concurrent_workspaces: 1 },
      isLoading: false,
      error: null,
    });
    mockEvents(
      [
        {
          id: "s1",
          timestamp: "2024-01-01T00:00:00Z",
          event_data: { node_name: "node-a" },
        },
      ],
      [
        {
          id: "d1",
          timestamp: "2024-01-01T00:01:00Z",
          event_data: { node_name: "node-a" },
        },
      ]
    );

    await renderPage();

    expect(screen.getByText("Spawn")).toBeInTheDocument();
    expect(screen.getByText("Destroy")).toBeInTheDocument();
    // node-a appears in both spawn and destroy rows
    expect(screen.getAllByText("node-a")).toHaveLength(2);
  });

  it("renders workspace chart with concurrency data", async () => {
    mockUseWorkflow.mockReturnValue({
      data: { id: "wf-1", name: "Test Workflow", status: "completed" },
      isLoading: false,
      error: null,
    });
    mockUseWorkflowMetrics.mockReturnValue({
      data: { max_concurrent_workspaces: 1 },
      isLoading: false,
      error: null,
    });
    mockEvents(
      [{ id: "s1", timestamp: "2024-01-01T00:00:00Z" }],
      [{ id: "d1", timestamp: "2024-01-01T00:01:00Z" }]
    );

    await renderPage();

    const chart = screen.getByTestId("workspace-chart");
    expect(chart).toBeInTheDocument();
    expect(chart).toHaveAttribute("data-points", "2");
    expect(chart).toHaveAttribute("data-peak", "1");
  });

  it("shows KPI strip with correct values", async () => {
    mockUseWorkflow.mockReturnValue({
      data: { id: "wf-1", name: "Test Workflow", status: "running" },
      isLoading: false,
      error: null,
    });
    mockUseWorkflowMetrics.mockReturnValue({
      data: { max_concurrent_workspaces: 3 },
      isLoading: false,
      error: null,
    });
    mockEvents(
      [
        { id: "s1", timestamp: "2024-01-01T00:00:00Z" },
        { id: "s2", timestamp: "2024-01-01T00:01:00Z" },
        { id: "s3", timestamp: "2024-01-01T00:02:00Z" },
      ],
      [{ id: "d1", timestamp: "2024-01-01T00:03:00Z" }]
    );

    await renderPage();

    expect(screen.getByText("Peak Concurrency")).toBeInTheDocument();
    expect(screen.getByText("Active Workspaces")).toBeInTheDocument();
    expect(screen.getByText("Total Spawns")).toBeInTheDocument();
    expect(screen.getByText("Total Destroys")).toBeInTheDocument();
    // Peak is 3 (from metrics), Active is 2 (3-1), spawns=3, destroys=1
    // Use getAllByText for "3" since it appears in multiple places (peak, spawns count)
    expect(screen.getAllByText("3")).toHaveLength(2);
    expect(screen.getByText("2")).toBeInTheDocument(); // Active (3-1)
  });
});

// ------------------------------------------------------------------
// Lane C: MNT-003 — async params (Next.js 16)
// ------------------------------------------------------------------

describe("WorkspacesPage — async params (Next.js 16)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // MNT-003 regression: in Next.js 16, `params` is a Promise. The
  // page must unwrap it with React.use(params). Without unwrapping,
  // id is undefined and the breadcrumb's id.slice(0, 8) throws.
  it("unwraps async params and renders the breadcrumb with the id slice", async () => {
    // workflow=null so the breadcrumb falls back to id.slice(0, 8).
    mockUseWorkflow.mockReturnValue({ data: null, isLoading: false, error: null });
    mockUseWorkflowMetrics.mockReturnValue({ data: null, isLoading: false, error: null });
    mockUseWorkflowEvents.mockReturnValue({ data: null, isLoading: false, error: null });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <WorkspacesPage params={Promise.resolve({ id: "wf-workspace-id" })} />
        </QueryClientProvider>
      );
    });

    // The breadcrumb renders id.slice(0, 8) when workflow is null.
    // With the bug, id is undefined and slice throws.
    // Look for the link with the id slice OR the full id in the href.
    const breadcrumbLinks = screen.queryAllByRole("link");
    const idLink = breadcrumbLinks.find(
      (l) => l.getAttribute("href") === "/workflows/wf-workspace-id"
    );
    expect(idLink).not.toBeUndefined();
  });
});
