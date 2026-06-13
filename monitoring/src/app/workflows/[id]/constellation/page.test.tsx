import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ConstellationPage from "./page";
import * as useWorkflowModule from "@/hooks/useWorkflow";
import * as useWorkflowEventsModule from "@/hooks/useWorkflowEvents";
import type {
  WorkflowDetail,
  WorkflowMetrics,
  WorkflowEvent,
} from "@/lib/types";

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

vi.mock("@/components/constellation/constellation-view", () => ({
  ConstellationView: () => <div data-testid="constellation-view" />,
}));

vi.mock("@/components/workflow/node-inspector", () => ({
  NodeInspector: () => <div data-testid="node-inspector" />,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("lucide-react", async () => {
  const actual = await vi.importActual("lucide-react");
  return {
    ...actual,
  };
});

// ------------------------------------------------------------------
// Fixtures
// ------------------------------------------------------------------

const sampleWorkflow: WorkflowDetail = {
  id: "wf-const",
  name: "Constellation Test",
  description: "",
  status: "running",
  dag_definition: {},
  created_at: "2026-06-12T10:00:00Z",
  updated_at: "2026-06-12T10:05:00Z",
};

const sampleMetrics: WorkflowMetrics = {
  workflow_id: "wf-const",
  cycle_count: 1,
  total_nodes: 2,
  completed_nodes: 1,
  failed_nodes: 0,
  completed_percent: 0.5,
  elapsed_seconds: 30,
  llm_tokens_accumulated: 100,
  max_concurrent_workspaces: 1,
  security_pass_rate: 1.0,
};

const sampleEvents: WorkflowEvent[] = [];

interface MockQueryResult<T> {
  data: T | null | undefined;
  isLoading: boolean;
  error: Error | null;
  isPending: boolean;
  isError: boolean;
  isSuccess: boolean;
  status: string;
  fetchStatus: string;
  isFetching: boolean;
  isStale: boolean;
  refetch: ReturnType<typeof vi.fn>;
  dataUpdatedAt: number;
  errorUpdatedAt: number;
  failureCount: number;
  failureReason: null;
  errorUpdateCount: number;
  isInitialLoading: boolean;
  isPaused: boolean;
  isPlaceholderData: boolean;
  isRefetchError: boolean;
  isLoadingError: boolean;
  isFetched: boolean;
  isFetchedAfterMount: boolean;
  isRefetching: boolean;
  isEnabled: boolean;
  promise: Promise<T>;
}

function makeMockQueryResult<T>(
  data: T | null | undefined,
  isLoading: boolean,
  error: Error | null
): MockQueryResult<T> {
  return {
    data,
    isLoading,
    error,
    isPending: isLoading,
    isError: !!error,
    isSuccess: !!data && !error,
    status: isLoading ? "pending" : error ? "error" : "success",
    fetchStatus: "idle",
    isFetching: false,
    isStale: false,
    refetch: vi.fn(),
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    errorUpdateCount: 0,
    isInitialLoading: false,
    isPaused: false,
    isPlaceholderData: false,
    isRefetchError: false,
    isLoadingError: false,
    isFetched: true,
    isFetchedAfterMount: true,
    isRefetching: false,
    isEnabled: true,
    promise: Promise.resolve(data as T),
  };
}

function mockHooks({
  workflow = sampleWorkflow,
  metrics = sampleMetrics,
  events = sampleEvents,
  status = null,
  wfLoading = false,
}: {
  workflow?: WorkflowDetail | null;
  metrics?: WorkflowMetrics | null;
  events?: WorkflowEvent[] | null;
  status?: unknown;
  wfLoading?: boolean;
} = {}) {
  vi.spyOn(useWorkflowModule, "useWorkflow").mockReturnValue(
    makeMockQueryResult(workflow, wfLoading, null) as unknown as ReturnType<
      typeof useWorkflowModule.useWorkflow
    >
  );
  vi.spyOn(useWorkflowModule, "useWorkflowStatus").mockReturnValue(
    makeMockQueryResult(status, false, null) as unknown as ReturnType<
      typeof useWorkflowModule.useWorkflowStatus
    >
  );
  vi.spyOn(useWorkflowModule, "useWorkflowMetrics").mockReturnValue(
    makeMockQueryResult(metrics, false, null) as unknown as ReturnType<
      typeof useWorkflowModule.useWorkflowMetrics
    >
  );
  vi.spyOn(useWorkflowEventsModule, "useWorkflowEvents").mockReturnValue(
    makeMockQueryResult(events, false, null) as unknown as ReturnType<
      typeof useWorkflowEventsModule.useWorkflowEvents
    >
  );
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

describe("ConstellationPage — async params (Next.js 16)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // MNT-001 regression: in Next.js 16, `params` is a Promise. The page
  // must unwrap it with React.use(params). Without unwrapping, the
  // hook chain receives `undefined` (since Promise has no .id), the
  // CopyButton's `text.slice(0, 8)` call throws, and the page never
  // renders the breadcrumb.
  it("unwraps the async params and renders the breadcrumb with the id", async () => {
    mockHooks();
    const queryClient = createQueryClient();
    const paramsPromise = Promise.resolve({ id: "wf-constellation-id" });

    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <ConstellationPage params={paramsPromise} />
        </QueryClientProvider>
      );
    });

    // The breadcrumb contains a button rendering text.slice(0, 8) of
    // the id from params. With the bug, id is undefined and the
    // CopyButton's text.slice(0, 8) throws synchronously during
    // render, so React unmounts the breadcrumb.
    const breadcrumbButtons = screen.queryAllByRole("button", {
      name: "wf-const",
    });
    expect(breadcrumbButtons.length).toBeGreaterThanOrEqual(1);
  });
});
