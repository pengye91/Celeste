import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import OPALoopPage from "./page";
import * as useWorkflowModule from "@/hooks/useWorkflow";
import * as useWorkflowEventsModule from "@/hooks/useWorkflowEvents";
import type {
  WorkflowDetail,
  WorkflowEvent,
  WorkflowMetrics,
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

vi.mock("@/components/charts/cycle-chart", () => ({
  CycleChart: () => <div data-testid="cycle-chart" />,
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
  id: "wf-1",
  name: "Test Workflow",
  description: "A test workflow",
  status: "completed",
  dag_definition: {},
  created_at: "2026-06-12T10:00:00Z",
  updated_at: "2026-06-12T10:05:00Z",
};

const sampleMetrics: WorkflowMetrics = {
  workflow_id: "wf-1",
  cycle_count: 2,
  total_nodes: 5,
  completed_nodes: 5,
  failed_nodes: 0,
  completed_percent: 1.0,
  elapsed_seconds: 60,
  llm_tokens_accumulated: 1000,
  max_concurrent_workspaces: 1,
  security_pass_rate: 1.0,
};

const sampleEvents: WorkflowEvent[] = [
  {
    id: "evt-obs-1",
    event_type: "observation",
    event_data: { goal: "first observation" },
    timestamp: "2026-06-12T10:00:01Z",
  },
  {
    id: "evt-plan-1",
    event_type: "plan_generated",
    event_data: { plan: { nodes: [{ name: "node-a" }, { name: "node-b" }] } },
    timestamp: "2026-06-12T10:00:02Z",
  },
  {
    id: "evt-eval-1",
    event_type: "evaluation",
    event_data: { decision: "approved", tokens: 100 },
    timestamp: "2026-06-12T10:00:03Z",
  },
  {
    id: "evt-obs-2",
    event_type: "observation",
    event_data: { goal: "second observation" },
    timestamp: "2026-06-12T10:00:04Z",
  },
  {
    id: "evt-plan-2",
    event_type: "plan_generated",
    event_data: {
      plan: { nodes: [{ name: "node-a" }, { name: "node-b" }, { name: "node-c" }] },
    },
    timestamp: "2026-06-12T10:00:05Z",
  },
  {
    id: "evt-eval-2",
    event_type: "evaluation",
    event_data: { decision: "approved", tokens: 150 },
    timestamp: "2026-06-12T10:00:06Z",
  },
];

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
  wfLoading = false,
  metricsLoading = false,
  eventsLoading = false,
  wfError = null as Error | null,
  eventsError = null as Error | null,
}: {
  workflow?: WorkflowDetail | null;
  metrics?: WorkflowMetrics | null;
  events?: WorkflowEvent[] | null;
  wfLoading?: boolean;
  metricsLoading?: boolean;
  eventsLoading?: boolean;
  wfError?: Error | null;
  eventsError?: Error | null;
} = {}) {
  vi.spyOn(useWorkflowModule, "useWorkflow").mockReturnValue(
    makeMockQueryResult(workflow, wfLoading, wfError) as unknown as ReturnType<
      typeof useWorkflowModule.useWorkflow
    >
  );

  vi.spyOn(useWorkflowModule, "useWorkflowMetrics").mockReturnValue(
    makeMockQueryResult(metrics, metricsLoading, null) as unknown as ReturnType<
      typeof useWorkflowModule.useWorkflowMetrics
    >
  );

  vi.spyOn(useWorkflowEventsModule, "useWorkflowEvents").mockReturnValue(
    makeMockQueryResult(events, eventsLoading, eventsError) as unknown as ReturnType<
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

describe("OPALoopPage — async params (Next.js 16)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // Lane C regression: in Next.js 16, `params` is a Promise and the
  // page must unwrap it with React.use(params). Without unwrapping,
  // `id = params.id` reads `Promise.id` (undefined) and the page
  // throws "Cannot read properties of undefined (reading 'slice')"
  // the moment it tries to render the breadcrumb.
  it("unwraps the async params and renders the workflow breadcrumb", async () => {
    mockHooks({ workflow: null });
    const queryClient = createQueryClient();
    const paramsPromise = Promise.resolve({ id: "wf-render-test-id" });

    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <OPALoopPage params={paramsPromise} />
        </QueryClientProvider>
      );
    });

    // The breadcrumb link should fall back to the id slice(0, 8)
    // when workflow.name is undefined. With the bug, id is undefined
    // and slice throws — the link is absent.
    const breadcrumbLink = screen.queryByRole("link", {
      name: /wf-rende/i,
    });
    expect(breadcrumbLink).not.toBeNull();
  });
});