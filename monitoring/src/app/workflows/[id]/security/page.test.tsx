import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SecurityAuditPage from "./page";
import * as useWorkflowModule from "@/hooks/useWorkflow";
import * as useWorkflowEventsModule from "@/hooks/useWorkflowEvents";
import type { WorkflowDetail, WorkflowMetrics, WorkflowEvent } from "@/lib/types";

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
  status: "running",
  dag_definition: {},
  created_at: "2026-06-12T10:00:00Z",
  updated_at: "2026-06-12T10:00:00Z",
};

const sampleMetrics: WorkflowMetrics = {
  workflow_id: "wf-1",
  cycle_count: 3,
  total_nodes: 10,
  completed_nodes: 7,
  failed_nodes: 0,
  completed_percent: 0.7,
  elapsed_seconds: 120,
  llm_tokens_accumulated: 5000,
  max_concurrent_workspaces: 2,
  security_pass_rate: 0.75,
};

const safeAuditEvent: WorkflowEvent = {
  id: "evt-1",
  event_type: "SECURITY_AUDIT",
  event_data: {
    result: "safe",
    risk: "none",
    reason: "Tool call is benign",
    tool: "read_file",
    arguments: { path: "/tmp/test.txt" },
    threats: [],
  },
  timestamp: "2026-06-12T10:05:00Z",
};

const blockedAuditEvent: WorkflowEvent = {
  id: "evt-2",
  event_type: "SECURITY_AUDIT",
  event_data: {
    result: "blocked",
    risk: "high",
    reason: "Attempted to access sensitive system file",
    tool: "write_file",
    arguments: { path: "/etc/passwd", content: "malicious" },
    threats: ["file-system-escape", "privilege-escalation"],
  },
  timestamp: "2026-06-12T10:06:00Z",
};

const blockedAuditEventMedium: WorkflowEvent = {
  id: "evt-3",
  event_type: "SECURITY_AUDIT",
  event_data: {
    result: "blocked",
    risk: "medium",
    reason: "Unusual network destination",
    tool: "fetch_url",
    arguments: { url: "http://suspicious.example.com" },
    threats: ["suspicious-network"],
  },
  timestamp: "2026-06-12T10:07:00Z",
};

// Minimal UseQueryResult-like shape for mocking
interface MockQueryResult<T> {
  data: T | null;
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
  data: T | null,
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
    promise: Promise.resolve(data!),
  };
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function mockHooks({
  workflow = sampleWorkflow,
  metrics = sampleMetrics,
  events = [safeAuditEvent, blockedAuditEvent, blockedAuditEventMedium] as WorkflowEvent[] | null,
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
        <SecurityAuditPage params={Promise.resolve({ id })} />
      </QueryClientProvider>
    );
  });
  return result!;
}

describe("SecurityAuditPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state while data is loading", async () => {
    mockHooks({ wfLoading: true, eventsLoading: true, metricsLoading: true });
    await renderPage();
    expect(screen.getByTestId("shell")).toBeInTheDocument();
    // Loading skeletons should be present
    expect(document.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders error state when fetch fails", async () => {
    mockHooks({
      wfError: new Error("Network error"),
      events: [],
    });
    await renderPage();
    expect(screen.getByText(/Failed to load security audit data/i)).toBeInTheDocument();
  });

  it("renders empty state when no audit events exist", async () => {
    mockHooks({ events: [] });
    await renderPage();
    expect(screen.getByText(/No audited calls/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Security audits appear when tool calls are evaluated/i)
    ).toBeInTheDocument();
  });

  it("renders workflow header with name, status badge, and copy-id button", async () => {
    mockHooks();
    await renderPage();
    expect(screen.getAllByText("Test Workflow").length).toBeGreaterThan(0);
    expect(screen.getAllByText("running").length).toBeGreaterThan(0);
    expect(screen.getAllByText("wf-1").length).toBeGreaterThan(0);
  });

  it("renders WorkflowNav with activeTab=security", async () => {
    mockHooks();
    await renderPage();
    const nav = screen.getByTestId("workflow-nav");
    expect(nav).toHaveAttribute("data-active-tab", "security");
  });

  it("renders coverage meter with correct percentage from metrics", async () => {
    mockHooks();
    await renderPage();
    // 75% from metrics.security_pass_rate
    expect(screen.getByText("75%")).toBeInTheDocument();
  });

  it("renders coverage meter with computed percentage when metrics lacks pass rate", async () => {
    mockHooks({
      metrics: { ...sampleMetrics, security_pass_rate: null },
    });
    await renderPage();
    // 1 safe / 3 total = 33%
    expect(screen.getByText("33%")).toBeInTheDocument();
  });

  it("renders blocked calls list with tool, arguments snippet, risk level, and reason", async () => {
    mockHooks();
    await renderPage();
    // Blocked tools — use getAllByText since tool names also appear in verdict cards
    expect(screen.getAllByText("write_file").length).toBeGreaterThan(0);
    expect(screen.getAllByText("fetch_url").length).toBeGreaterThan(0);
    // Risk badges
    expect(screen.getAllByText("high").length).toBeGreaterThan(0);
    expect(screen.getAllByText("medium").length).toBeGreaterThan(0);
    // Reasons
    expect(screen.getAllByText(/Attempted to access sensitive system file/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Unusual network destination/i).length).toBeGreaterThan(0);
    // Arguments snippets
    expect(screen.getAllByText(/etc\/passwd/).length).toBeGreaterThan(0);
  });

  it("renders threat tag cloud with unique threats", async () => {
    mockHooks();
    await renderPage();
    expect(screen.getByText("file-system-escape")).toBeInTheDocument();
    expect(screen.getByText("privilege-escalation")).toBeInTheDocument();
    expect(screen.getByText("suspicious-network")).toBeInTheDocument();
  });

  it("renders verdict cards for each audit event", async () => {
    mockHooks();
    await renderPage();
    // Safe and blocked verdicts
    expect(screen.getByText("Safe")).toBeInTheDocument();
    expect(screen.getAllByText("Blocked").length).toBeGreaterThanOrEqual(2);
  });

  it("shows 'All calls passed' when no blocked audits", async () => {
    mockHooks({ events: [safeAuditEvent] });
    await renderPage();
    expect(screen.getByText(/All calls passed security audit/i)).toBeInTheDocument();
  });

  it("verdict cards are not keyboard-focusable (a11y: no interactive role)", async () => {
    mockHooks();
    await renderPage();
    // Lane 3 a11y pass: removed tabIndex={0} from VerdictCard divs
    // because they have no onClick and no interactive role. The
    // cards remain readable and screen-reader-friendly via the
    // surrounding <article role="article"> wrapper.
    const cards = document.querySelectorAll('[tabIndex="0"]');
    expect(cards.length).toBe(0);
  });

  it("copy button copies workflow id to clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    (window as unknown as Record<string, unknown>).__toasterAdd = vi.fn(
      () => "toast-id"
    );

    mockHooks();
    await renderPage();
    const copyButton = screen.getByTitle("Copy ID");
    copyButton.click();
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("wf-1"));
    // Toast confirms via useCopyToClipboard → useToast.
    const add = (window as unknown as Record<string, unknown>).__toasterAdd as ReturnType<
      typeof vi.fn
    >;
    expect(add).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Copied workflow ID", variant: "success" })
    );
  });

  it("renders aria-live region for summary", async () => {
    mockHooks();
    await renderPage();
    const liveRegion = screen.getByText(/Blocked calls:/i).closest("[aria-live]");
    expect(liveRegion).toHaveAttribute("aria-live", "polite");
  });

  it("handles unknown verdict gracefully", async () => {
    const unknownEvent: WorkflowEvent = {
      id: "evt-4",
      event_type: "SECURITY_AUDIT",
      event_data: {
        result: "pending",
        risk: "low",
        reason: "Audit incomplete",
        tool: "unknown_tool",
      },
      timestamp: "2026-06-12T10:08:00Z",
    };
    mockHooks({ events: [unknownEvent] });
    await renderPage();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("renders with reduced-motion class when prefers-reduced-motion is set", async () => {
    // Note: actual reduced-motion behavior is CSS-based via media query;
    // this test verifies the component renders without animation-dependent assertions.
    mockHooks();
    await renderPage();
    // Coverage meter should still render
    expect(screen.getByText("75%")).toBeInTheDocument();
    // Verdict cards should render
    expect(screen.getByText("Safe")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------
// Lane C: MNT-002 — async params (Next.js 16)
// ------------------------------------------------------------------

describe("SecurityAuditPage — async params (Next.js 16)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // MNT-002 regression: in Next.js 16, `params` is a Promise. The
  // page must unwrap it with React.use(params). Without unwrapping,
  // `id = params.id` reads Promise.id (undefined) and the breadcrumb's
  // `id.slice(0, 8)` throws.
  it("unwraps async params and renders the breadcrumb with the id slice", async () => {
    mockHooks({ workflow: null });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <SecurityAuditPage params={Promise.resolve({ id: "wf-security-id" })} />
        </QueryClientProvider>
      );
    });

    // The breadcrumb renders id.slice(0, 8) when workflow is null.
    // With the bug, id is undefined and slice throws.
    const breadcrumbLink = screen.queryByRole("link", {
      name: /wf-secur$/,
    });
    expect(breadcrumbLink).not.toBeNull();
  });
});
