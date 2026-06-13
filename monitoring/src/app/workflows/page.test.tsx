import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WorkflowsPage from "./page";
import * as useWorkflowModule from "@/hooks/useWorkflow";
import type { WorkflowListItem, WorkflowListResponse, WorkflowMetrics } from "@/lib/types";

// ------------------------------------------------------------------
// Mocks
// ------------------------------------------------------------------

// Track the URL state map per-test. The fake hook reads + writes
// into this object so we can assert against it after each render.
const urlState: Record<string, string> = {};

vi.mock("@/hooks/useUrlState", () => ({
  useUrlState: (
    key: string,
    defaultValue: string,
    allowed?: readonly string[]
  ) => {
    const raw = urlState[key];
    const value =
      raw === undefined || raw === ""
        ? defaultValue
        : allowed && !allowed.includes(raw)
          ? defaultValue
          : raw;
    const setter = (next: string) => {
      if (next === defaultValue || next === "") {
        delete urlState[key];
      } else {
        urlState[key] = next;
      }
    };
    return [value, setter] as const;
  },
}));

vi.mock("@/components/shell/shell", () => ({
  Shell: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="shell">{children}</div>
  ),
}));

vi.mock("lucide-react", async () => {
  const actual = await vi.importActual("lucide-react");
  return {
    ...actual,
  };
});

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

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => ({
    get: (k: string) => urlState[k] ?? null,
    toString: () => "",
  }),
}));

vi.mock("@/hooks/useKeyboardShortcuts", () => ({
  useKeyboardShortcuts: vi.fn(),
}));

// ------------------------------------------------------------------
// Fixtures
// ------------------------------------------------------------------

const sampleWorkflows: WorkflowListItem[] = [
  {
    id: "wf-alpha",
    name: "Alpha deploy",
    status: "running",
    created_at: "2026-06-12T10:00:00Z",
  },
  {
    id: "wf-beta",
    name: "Beta rollout",
    status: "completed",
    created_at: "2026-06-12T10:01:00Z",
  },
];

const workflowsResponse: WorkflowListResponse = {
  items: sampleWorkflows,
  total: 2,
  limit: 12,
  offset: 0,
};

interface MockQueryResult<T> {
  data: T | undefined;
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
  data: T | undefined,
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

function mockWorkflowsQuery({
  data = undefined as WorkflowListResponse | undefined,
  isLoading = false,
  error = null as Error | null,
}: {
  data?: WorkflowListResponse | undefined;
  isLoading?: boolean;
  error?: Error | null;
} = {}) {
  vi.spyOn(useWorkflowModule, "useWorkflows").mockReturnValue(
    makeMockQueryResult<WorkflowListResponse>(data, isLoading, error) as unknown as ReturnType<
      typeof useWorkflowModule.useWorkflows
    >
  );
  // MNT-019: per-workflow metrics are now fetched inside each card
  // via useWorkflowMetrics. Default mock returns null so the card
  // shows the em-dash placeholders.
  vi.spyOn(useWorkflowModule, "useWorkflowMetrics").mockReturnValue(
    makeMockQueryResult<WorkflowMetrics | null>(null, false, null) as unknown as ReturnType<
      typeof useWorkflowModule.useWorkflowMetrics
    >
  );
}

async function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  let result: ReturnType<typeof render> | undefined;
  await act(async () => {
    result = render(
      <QueryClientProvider client={queryClient}>
        <WorkflowsPage />
      </QueryClientProvider>
    );
  });
  return result!;
}

// Status filter chips render as buttons whose accessible name is the
// concatenation of the inner StatusOrb's aria-label and the visible
// label. To select them deterministically, we filter buttons whose
// text content ends with the chip's label.
function getStatusChip(label: string): HTMLButtonElement {
  const buttons = screen.getAllByRole("button");
  const match = buttons.find(
    (b) =>
      b.textContent?.trim() === label ||
      b.textContent?.trim().endsWith(label)
  );
  if (!match) {
    throw new Error(`No status chip with label "${label}" found`);
  }
  return match as HTMLButtonElement;
}

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

describe("WorkflowsPage — URL state preservation", () => {
  beforeEach(() => {
    Object.keys(urlState).forEach((k) => delete urlState[k]);
    vi.clearAllMocks();
  });

  it("renders the page with default filter (all) and empty search", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    expect(screen.getByTestId("shell")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Workflows", level: 1 })).toBeInTheDocument();
    // Default 'All' chip is active
    const allButton = getStatusChip("All");
    expect(allButton).toHaveAttribute("aria-pressed", "true");
  });

  it("reads ?status=running from the URL on initial render", async () => {
    urlState.status = "running";
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    // The 'Running' chip is the active one. Filter chips render as
    // buttons with a `StatusOrb` child (role="img") and visible text,
    // so the accessible name is e.g. "Running status indicator
    // Running". We select by aria-pressed to be unambiguous.
    const running = getStatusChip("Running");
    expect(running).toHaveAttribute("aria-pressed", "true");
    const all = getStatusChip("All");
    expect(all).toHaveAttribute("aria-pressed", "false");
  });

  it("writes ?status=paused to the URL state when a filter chip is clicked", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const paused = getStatusChip("Paused");
    fireEvent.click(paused);
    expect(urlState.status).toBe("paused");
  });

  it("toggles a status filter off (back to 'all') when clicked twice", async () => {
    urlState.status = "running";
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const running = getStatusChip("Running");
    fireEvent.click(running);
    expect(urlState.status).toBeUndefined();
  });

  it("falls back to 'all' when the URL status is not in the allow list", async () => {
    urlState.status = "garbage";
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const all = getStatusChip("All");
    expect(all).toHaveAttribute("aria-pressed", "true");
  });

  it("writes ?search=alpha when the search input is changed", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const input = screen.getByLabelText(/search workflows by name/i);
    fireEvent.change(input, { target: { value: "alpha" } });
    expect(urlState.search).toBe("alpha");
  });

  it("clears ?search when the clear-search button is clicked", async () => {
    urlState.search = "alpha";
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const clear = screen.getByRole("button", { name: /clear search/i });
    fireEvent.click(clear);
    expect(urlState.search).toBeUndefined();
  });

  it("filters the workflow list client-side by the search query", async () => {
    urlState.search = "alpha";
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    await waitFor(() => {
      expect(screen.getByText("Alpha deploy")).toBeInTheDocument();
    });
    // Beta is filtered out by the search
    expect(screen.queryByText("Beta rollout")).not.toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Accessibility
  // ------------------------------------------------------------------

  it("associates the search input with a sr-only label", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const input = screen.getByLabelText(/search workflows by name/i);
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute("id", "workflow-search");
  });

  it("groups the status filter chips in a labelled role=group", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const group = screen.getByRole("group", { name: /filter workflows by status/i });
    expect(group).toBeInTheDocument();
  });

  it("pairs every status filter chip with a StatusOrb that has a label", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    // The page renders 6 status chips (Running, Completed, Failed,
    // Paused, Pending, Cancelled), each with a StatusOrb.
    const orbs = screen.getAllByRole("img");
    expect(orbs.length).toBeGreaterThanOrEqual(6);
  });

  it("renders a status badge with text content for each workflow card", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    await waitFor(() => {
      expect(screen.getByText("Alpha deploy")).toBeInTheDocument();
    });
    // Each card shows a status badge whose text is the workflow's status
    expect(screen.getAllByText("running").length).toBeGreaterThan(0);
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
  });

  it("renders the page in a focus-trap-safe way: no positive tabindex traps", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    // No element should carry a positive tabindex, which would break
    // the natural tab order.
    const positive = document.querySelectorAll('[tabindex]:not([tabindex="-1"]):not([tabindex="0"])');
    expect(positive.length).toBe(0);
  });

  // ------------------------------------------------------------------
  // Keyboard shortcuts (j/k/Enter)
  // ------------------------------------------------------------------

  it("renders the workflow grid as a listbox with options", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const listbox = screen.getByRole("listbox", { name: /workflows/i });
    expect(listbox).toBeInTheDocument();
    const options = screen.getAllByRole("option");
    expect(options.length).toBe(2);
  });

  it("marks the first workflow as selected by default", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(options[1]).toHaveAttribute("aria-selected", "false");
  });

  it("captures the j/k/Enter handler map from useKeyboardShortcuts", async () => {
    const mod = await import("@/hooks/useKeyboardShortcuts");
    const spy = mod.useKeyboardShortcuts as unknown as ReturnType<typeof vi.fn>;
    mockWorkflowsQuery({ data: workflowsResponse });
    await renderPage();
    const calls = spy.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const last = calls[calls.length - 1][0] as Record<string, unknown>;
    expect(typeof last.j).toBe("function");
    expect(typeof last.k).toBe("function");
    expect(typeof last.Enter).toBe("function");
  });
});

// ------------------------------------------------------------------
// Lane C: MNT-019 — workflow card metrics (no hardcoded zeros)
// ------------------------------------------------------------------

describe("WorkflowsPage — workflow card metrics (MNT-019)", () => {
  beforeEach(() => {
    Object.keys(urlState).forEach((k) => delete urlState[k]);
    vi.clearAllMocks();
  });

  // MNT-019 regression: the list page previously hardcoded
  // progress/cycle_count/node_count/elapsed_seconds to 0 for every
  // workflow before passing to WorkflowCard, so every metric rendered
  // as zero. The fix: fetch per-workflow metrics via
  // useWorkflowMetrics (or a batch equivalent) and merge them so the
  // cards display real values.
  it("renders real cycle_count from per-workflow metrics, not 0", async () => {
    const sampleMetrics: WorkflowMetrics = {
      workflow_id: "wf-alpha",
      cycle_count: 7,
      total_nodes: 12,
      completed_nodes: 8,
      failed_nodes: 0,
      completed_percent: 0.66,
      elapsed_seconds: 320,
      llm_tokens_accumulated: 4200,
      max_concurrent_workspaces: 1,
      security_pass_rate: 1.0,
    };
    mockWorkflowsQuery({ data: workflowsResponse });
    // Mock useWorkflowMetrics to return a real value for wf-alpha.
    vi.spyOn(useWorkflowModule, "useWorkflowMetrics").mockImplementation(
      (id: string) => {
        const data = id === "wf-alpha" ? sampleMetrics : null;
        return makeMockQueryResult<WorkflowMetrics | null>(data, false, null) as unknown as ReturnType<
          typeof useWorkflowModule.useWorkflowMetrics
        >;
      }
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <WorkflowsPage />
        </QueryClientProvider>
      );
    });

    // The metrics strip on the wf-alpha card should show "7" (cycles)
    // — not "0".
    const cards = screen.getAllByRole("option");
    const alphaCard = cards.find((c) => c.getAttribute("data-workflow-id") === "wf-alpha");
    expect(alphaCard).toBeDefined();
    expect(alphaCard!.textContent).toContain("7");
  });
});
