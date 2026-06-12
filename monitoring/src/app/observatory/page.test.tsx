import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import ObservatoryPage from "./page";
import * as useLiveEventsModule from "@/hooks/useLiveGlobalEvents";
import * as useWorkflowModule from "@/hooks/useWorkflow";
import * as featureVerificationModule from "@/lib/featureVerification";
import type { GlobalEvent, WorkflowListItem, WorkflowListResponse } from "@/lib/types";
import type { FeatureCheck } from "@/lib/types";

// ------------------------------------------------------------------
// Mocks
// ------------------------------------------------------------------

vi.mock("@/components/shell/shell", () => ({
  Shell: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="shell">{children}</div>
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

// Lane C wires useUrlState into this page; mock it so we don't
// require a full Next router context here. We expose a single
// mutable `urlState` map so the URL-state-specific tests can poke
// values into the component synchronously.
const obsUrlState: Record<string, string> = {};
vi.mock("@/hooks/useUrlState", () => ({
  useUrlState: (key: string, defaultValue: string) => {
    const raw = obsUrlState[key];
    const value = raw === undefined || raw === "" ? defaultValue : raw;
    const setter = (next: string) => {
      if (next === defaultValue || next === "") {
        delete obsUrlState[key];
      } else {
        obsUrlState[key] = next;
      }
    };
    return [value, setter] as const;
  },
}));

vi.mock("@/lib/api", () => ({
  getWorkflowWorkflowEvents: vi.fn().mockResolvedValue([]),
  getGlobalEvents: vi.fn().mockResolvedValue([]),
  listWorkflows: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 0, offset: 0 }),
  getWorkflow: vi.fn().mockResolvedValue(null),
  getWorkflowStatus: vi.fn().mockResolvedValue(null),
  getWorkflowEvents: vi.fn().mockResolvedValue([]),
  getWorkflowMetrics: vi.fn().mockResolvedValue(null),
  getWorkflowNodes: vi.fn().mockResolvedValue([]),
  cancelWorkflow: vi.fn().mockResolvedValue({ workflow_id: "", status: "" }),
  resumeWorkflow: vi.fn().mockResolvedValue({ workflow_id: "", status: "" }),
  registerAgent: vi.fn().mockResolvedValue({ agent_id: "", status: "" }),
  listAgents: vi.fn().mockResolvedValue([]),
}));

// ------------------------------------------------------------------
// Fixtures
// ------------------------------------------------------------------

const sampleEvent1: GlobalEvent = {
  id: "evt-1",
  event_source: "task",
  workflow_id: "wf-alpha",
  event_type: "NODE_COMPLETED",
  event_data: { node: "n1", status: "ok" },
  timestamp: new Date(Date.now() - 5_000).toISOString(),
};

const sampleEvent2: GlobalEvent = {
  id: "evt-2",
  event_source: "workflow",
  workflow_id: "wf-beta",
  event_type: "SECURITY_AUDIT",
  event_data: { result: "safe", tool: "read_file" },
  timestamp: new Date(Date.now() - 30_000).toISOString(),
};

const sampleEvent3: GlobalEvent = {
  id: "evt-3",
  event_source: "task",
  workflow_id: "wf-gamma",
  event_type: "WORKFLOW_FAILED",
  event_data: { reason: "timeout" },
  timestamp: new Date(Date.now() - 90_000).toISOString(),
};

const sampleWorkflows: WorkflowListItem[] = [
  {
    id: "wf-alpha",
    name: "Alpha",
    status: "running",
    created_at: "2026-06-12T10:00:00Z",
  },
  {
    id: "wf-beta",
    name: "Beta",
    status: "completed",
    created_at: "2026-06-12T10:01:00Z",
  },
];

const workflowsResponse: WorkflowListResponse = {
  items: sampleWorkflows,
  total: 2,
  limit: 100,
  offset: 0,
};

const fleetSummary = {
  total: 6,
  pass: 4,
  fail: 1,
  not_exercised: 1,
};

const fleetChecks: FeatureCheck[] = [
  { name: "Security audit pipeline", status: "pass", detail: "audits recorded" },
  { name: "Saga compensation", status: "fail", detail: "1 failure" },
  { name: "Multi-workspace concurrency", status: "not_exercised" },
  { name: "Human escalation", status: "pass" },
  { name: "OPA replanning", status: "not_exercised" },
  { name: "Checkpoint lineage", status: "pass" },
];

// Minimal UseQueryResult-like shape
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

// useLiveGlobalEvents shape. We keep it close to the real return
// type so the observatory page can be exercised end-to-end.
interface MockLiveEventsResult {
  events: GlobalEvent[] | null | undefined;
  isLoading: boolean;
  error: Error | null;
  state: "connected" | "reconnecting" | "fallback" | "idle";
  transport: "sse" | "polling" | "none";
  refetch: ReturnType<typeof vi.fn>;
}

function makeMockLiveEvents(
  events: GlobalEvent[] | null | undefined,
  isLoading: boolean,
  error: Error | null,
  state: MockLiveEventsResult["state"] = "fallback"
): MockLiveEventsResult {
  return {
    events,
    isLoading,
    error,
    state,
    transport: state === "connected" ? "sse" : "polling",
    refetch: vi.fn(),
  };
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function mockHooks({
  events = null as GlobalEvent[] | null,
  eventsLoading = false,
  eventsError = null as Error | null,
  workflows = null as WorkflowListResponse | null,
  workflowsLoading = false,
  workflowsError = null as Error | null,
}: {
  events?: GlobalEvent[] | null;
  eventsLoading?: boolean;
  eventsError?: Error | null;
  workflows?: WorkflowListResponse | null;
  workflowsLoading?: boolean;
  workflowsError?: Error | null;
} = {}) {
  vi.spyOn(useLiveEventsModule, "useLiveGlobalEvents").mockReturnValue(
    makeMockLiveEvents(events, eventsLoading, eventsError) as unknown as ReturnType<
      typeof useLiveEventsModule.useLiveGlobalEvents
    >
  );

  vi.spyOn(useWorkflowModule, "useWorkflows").mockReturnValue(
    makeMockQueryResult(workflows, workflowsLoading, workflowsError) as unknown as ReturnType<
      typeof useWorkflowModule.useWorkflows
    >
  );
}

function mockFleetSummary() {
  vi.spyOn(featureVerificationModule, "summarizeFleetFromWorkflows").mockResolvedValue(
    fleetSummary
  );
  // The page calls aggregateFeatureChecks with the per-workflow
  // events. The tests for the helper itself live in
  // featureVerification.test.ts; here we always return the same
  // fixture list so the drill-down is stable.
  vi.spyOn(featureVerificationModule, "aggregateFeatureChecks").mockReturnValue(
    fleetChecks
  );
}

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

describe("ObservatoryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders LOADING state when both fetches are pending", () => {
    mockHooks({ eventsLoading: true, workflowsLoading: true });
    render(<ObservatoryPage />);
    expect(screen.getByTestId("shell")).toBeInTheDocument();
    expect(screen.getByText(/Connecting to event stream/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("event-skeleton").length).toBeGreaterThan(0);
  });

  it("renders EMPTY state when there are no events and no workflows", async () => {
    mockHooks({ events: [], workflows: { items: [], total: 0, limit: 100, offset: 0 } });
    mockFleetSummary();
    render(<ObservatoryPage />);
    expect(screen.getByText(/No events in the last hour/i)).toBeInTheDocument();
    expect(screen.getByText(/No workflows in the fleet yet/i)).toBeInTheDocument();
    // Provider telemetry absent
    expect(screen.getByText(/Provider telemetry not yet emitted/i)).toBeInTheDocument();
  });

  it("renders ERROR state when the global event stream fails", () => {
    mockHooks({
      eventsError: new Error("CMC lost contact with Celeste"),
      workflows: workflowsResponse,
    });
    mockFleetSummary();
    render(<ObservatoryPage />);
    expect(screen.getByText(/Disconnected from event stream/i)).toBeInTheDocument();
    expect(screen.getByText(/CMC lost contact with Celeste/i)).toBeInTheDocument();
  });

  it("calls refetch when the Reconnect button is clicked", () => {
    const refetch = vi.fn();
    vi.spyOn(useLiveEventsModule, "useLiveGlobalEvents").mockReturnValue({
      ...makeMockLiveEvents(null, false, new Error("boom")),
      refetch,
    } as unknown as ReturnType<typeof useLiveEventsModule.useLiveGlobalEvents>);
    vi.spyOn(useWorkflowModule, "useWorkflows").mockReturnValue(
      makeMockQueryResult(workflowsResponse, false, null) as unknown as ReturnType<
        typeof useWorkflowModule.useWorkflows
      >
    );
    mockFleetSummary();
    render(<ObservatoryPage />);
    const button = screen.getByRole("button", { name: /reconnect/i });
    fireEvent.click(button);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders SUCCESS state with events, summary, and provider mix", async () => {
    mockHooks({
      events: [sampleEvent1, sampleEvent2, sampleEvent3],
      workflows: workflowsResponse,
    });
    mockFleetSummary();
    render(<ObservatoryPage />);

    // Ticker rows present
    await waitFor(() => {
      expect(screen.getByTestId("event-ticker-list")).toBeInTheDocument();
    });
    expect(screen.getByText("NODE_COMPLETED")).toBeInTheDocument();
    expect(screen.getByText("SECURITY_AUDIT")).toBeInTheDocument();
    expect(screen.getByText("WORKFLOW_FAILED")).toBeInTheDocument();

    // Summary counts
    await waitFor(() => {
      expect(screen.getByTestId("count-success")).toBeInTheDocument();
    });
    expect(screen.getByTestId("count-success")).toHaveTextContent("4");
    expect(screen.getByTestId("count-danger")).toHaveTextContent("1");
    expect(screen.getByTestId("count-muted")).toHaveTextContent("1");

    // Feature names visible
    expect(screen.getAllByText("Security audit pipeline").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Saga compensation").length).toBeGreaterThan(0);
  });

  it("renders the provider mix chart when events carry a provider/model key", () => {
    const eventsWithProviders: GlobalEvent[] = [
      { ...sampleEvent1, event_data: { provider: "anthropic", model: "claude-3" } },
      { ...sampleEvent2, event_data: { provider: "anthropic", model: "claude-3" } },
      { ...sampleEvent3, event_data: { provider: "openai", model: "gpt-4" } },
    ];
    mockHooks({
      events: eventsWithProviders,
      workflows: workflowsResponse,
    });
    mockFleetSummary();
    render(<ObservatoryPage />);
    expect(screen.getByTestId("provider-mix")).toBeInTheDocument();
    expect(screen.getByText("anthropic")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
  });

  it("renders PARTIAL state (ticker live, summary still loading)", async () => {
    mockHooks({
      events: [sampleEvent1, sampleEvent2],
      workflowsLoading: true,
    });
    mockFleetSummary();
    render(<ObservatoryPage />);
    // Ticker is live
    await waitFor(() => {
      expect(screen.getByTestId("event-ticker-list")).toBeInTheDocument();
    });
    // Summary still loading — find by aria-label rather than text content.
    expect(
      screen.getByLabelText(/Feature verification summary loading/i)
    ).toBeInTheDocument();
  });

  it("shows the page title in display font", () => {
    mockHooks({ events: [sampleEvent1] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const heading = screen.getByRole("heading", { level: 1, name: /Observatory/i });
    expect(heading).toHaveClass("font-display");
  });

  it("renders an aria-live region for new event announcements", () => {
    mockHooks({ events: [sampleEvent1] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const liveRegion = document.querySelector("[aria-live='polite']");
    expect(liveRegion).toBeInTheDocument();
  });

  it("renders event rows with relative timestamps and event-type pills", () => {
    mockHooks({ events: [sampleEvent1, sampleEvent2] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    // Event type pills
    expect(screen.getByText("NODE_COMPLETED")).toBeInTheDocument();
    // Each row has a relative-time tooltip with the absolute timestamp
    const rows = screen.getAllByTitle(/ago|Jun|Mar|Apr|May|Jul|Aug|Sep|Oct|Nov|Dec|Jan|Feb/i);
    expect(rows.length).toBeGreaterThan(0);
  });

  it("links workflow_id to the workflow page", () => {
    mockHooks({ events: [sampleEvent1] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const link = screen.getByRole("link", { name: /wf-alpha/i });
    expect(link).toHaveAttribute("href", "/workflows/wf-alpha");
  });

  it("highlights failing feature checks", async () => {
    mockHooks({
      events: [sampleEvent1],
      workflows: workflowsResponse,
    });
    mockFleetSummary();
    render(<ObservatoryPage />);
    // The fixture has Saga compensation as "fail"; wait for the
    // per-feature drill-down row to render with that status.
    await waitFor(() => {
      const rows = document.querySelectorAll("li[data-status]");
      const failRows = Array.from(rows).filter(
        (r) => r.getAttribute("data-status") === "fail"
      );
      expect(failRows.length).toBeGreaterThan(0);
    });
    const failRow = Array.from(
      document.querySelectorAll("li[data-status='fail']")
    )[0];
    expect(failRow).toBeDefined();
    expect(failRow.textContent).toMatch(/Saga compensation/);
  });

  it("renders the empty observatory SVG illustration when no events", () => {
    mockHooks({ events: [] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const svg = document.querySelector('svg[aria-label="Empty observatory illustration"]');
    expect(svg).toBeInTheDocument();
  });

  it("respects prefers-reduced-motion by not requiring animations to find content", () => {
    mockHooks({ events: [sampleEvent1, sampleEvent2, sampleEvent3] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    // Pure DOM assertions — no animation timing dependency.
    expect(screen.getByTestId("event-ticker-list")).toBeInTheDocument();
  });

  // ----------------------------------------------------------------
  // Lane C — URL state + a11y
  // ----------------------------------------------------------------
  it("clears the obsUrlState mock between tests (smoke)", () => {
    // Sentinel test that runs after the others; it just checks the
    // test-level fixtures haven't leaked.
    expect(obsUrlState.event_type).toBeUndefined();
  });
});

describe("ObservatoryPage — event_type URL filter (Lane C)", () => {
  beforeEach(() => {
    Object.keys(obsUrlState).forEach((k) => delete obsUrlState[k]);
    vi.clearAllMocks();
  });

  it("renders the filter input with an accessible label and placeholder", () => {
    mockHooks({ events: [] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const input = screen.getByTestId("observatory-event-type-input");
    expect(input).toBeInTheDocument();
    // The wrapper div has aria-label="Filter events by type" so the
    // landmark is discoverable; the input itself is labelled by a
    // sr-only <label> element.
    expect(input).toHaveAttribute("id", "observatory-event-type");
    expect(input).toHaveAttribute("placeholder", expect.stringMatching(/filter.*event type/i));
  });

  it("pre-fills the filter input from ?event_type=NODE_COMPLETED", () => {
    obsUrlState.event_type = "NODE_COMPLETED";
    mockHooks({ events: [] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const input = screen.getByTestId(
      "observatory-event-type-input"
    ) as HTMLInputElement;
    expect(input.value).toBe("NODE_COMPLETED");
  });

  it("writes ?event_type= into the URL state when the input changes", () => {
    mockHooks({ events: [] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const input = screen.getByTestId("observatory-event-type-input");
    fireEvent.change(input, { target: { value: "WORKFLOW_FAILED" } });
    expect(obsUrlState.event_type).toBe("WORKFLOW_FAILED");
  });

  it("clears the URL state when the clear-filter button is clicked", () => {
    obsUrlState.event_type = "NODE_COMPLETED";
    mockHooks({ events: [] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const clear = screen.getByRole("button", {
      name: /clear event type filter/i,
    });
    fireEvent.click(clear);
    expect(obsUrlState.event_type).toBeUndefined();
  });

  it("exposes the event_type filter to the live events hook", () => {
    obsUrlState.event_type = "SECURITY_AUDIT";
    const useLiveSpy = vi.spyOn(useLiveEventsModule, "useLiveGlobalEvents");
    mockHooks({ events: [] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    expect(useLiveSpy).toHaveBeenCalled();
    const lastCall = useLiveSpy.mock.calls[useLiveSpy.mock.calls.length - 1];
    const opts = lastCall[0] as { event_type?: string } | undefined;
    expect(opts?.event_type).toBe("SECURITY_AUDIT");
  });
});

describe("ObservatoryPage — aria-live regions (Lane C)", () => {
  beforeEach(() => {
    Object.keys(obsUrlState).forEach((k) => delete obsUrlState[k]);
    vi.clearAllMocks();
  });

  it("renders the event ticker with an aria-live=polite announcement region", () => {
    mockHooks({ events: [sampleEvent1] });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const tickerLive = document.querySelector(
      "section[aria-label='Live event ticker'] [aria-live='polite']"
    );
    expect(tickerLive).toBeInTheDocument();
  });

  it("renders the live indicator with role=status and aria-live=polite", () => {
    mockHooks({ events: [sampleEvent1], });
    mockFleetSummary();
    render(<ObservatoryPage />);
    const live = screen.getByTestId("live-indicator");
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveAttribute("role", "status");
  });
});
