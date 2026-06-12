import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import WorkflowsPage from "./page";
import * as useWorkflowModule from "@/hooks/useWorkflow";
import type { WorkflowListItem, WorkflowListResponse } from "@/lib/types";

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

  it("renders the page with default filter (all) and empty search", () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    expect(screen.getByTestId("shell")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Workflows", level: 1 })).toBeInTheDocument();
    // Default 'All' chip is active
    const allButton = getStatusChip("All");
    expect(allButton).toHaveAttribute("aria-pressed", "true");
  });

  it("reads ?status=running from the URL on initial render", () => {
    urlState.status = "running";
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    // The 'Running' chip is the active one. Filter chips render as
    // buttons with a `StatusOrb` child (role="img") and visible text,
    // so the accessible name is e.g. "Running status indicator
    // Running". We select by aria-pressed to be unambiguous.
    const running = getStatusChip("Running");
    expect(running).toHaveAttribute("aria-pressed", "true");
    const all = getStatusChip("All");
    expect(all).toHaveAttribute("aria-pressed", "false");
  });

  it("writes ?status=paused to the URL state when a filter chip is clicked", () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const paused = getStatusChip("Paused");
    fireEvent.click(paused);
    expect(urlState.status).toBe("paused");
  });

  it("toggles a status filter off (back to 'all') when clicked twice", () => {
    urlState.status = "running";
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const running = getStatusChip("Running");
    fireEvent.click(running);
    expect(urlState.status).toBeUndefined();
  });

  it("falls back to 'all' when the URL status is not in the allow list", () => {
    urlState.status = "garbage";
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const all = getStatusChip("All");
    expect(all).toHaveAttribute("aria-pressed", "true");
  });

  it("writes ?search=alpha when the search input is changed", () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const input = screen.getByLabelText(/search workflows by name/i);
    fireEvent.change(input, { target: { value: "alpha" } });
    expect(urlState.search).toBe("alpha");
  });

  it("clears ?search when the clear-search button is clicked", () => {
    urlState.search = "alpha";
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const clear = screen.getByRole("button", { name: /clear search/i });
    fireEvent.click(clear);
    expect(urlState.search).toBeUndefined();
  });

  it("filters the workflow list client-side by the search query", async () => {
    urlState.search = "alpha";
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getByText("Alpha deploy")).toBeInTheDocument();
    });
    // Beta is filtered out by the search
    expect(screen.queryByText("Beta rollout")).not.toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Accessibility
  // ------------------------------------------------------------------

  it("associates the search input with a sr-only label", () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const input = screen.getByLabelText(/search workflows by name/i);
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute("id", "workflow-search");
  });

  it("groups the status filter chips in a labelled role=group", () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const group = screen.getByRole("group", { name: /filter workflows by status/i });
    expect(group).toBeInTheDocument();
  });

  it("pairs every status filter chip with a StatusOrb that has a label", () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    // The page renders 6 status chips (Running, Completed, Failed,
    // Paused, Pending, Cancelled), each with a StatusOrb.
    const orbs = screen.getAllByRole("img");
    expect(orbs.length).toBeGreaterThanOrEqual(6);
  });

  it("renders a status badge with text content for each workflow card", async () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getByText("Alpha deploy")).toBeInTheDocument();
    });
    // Each card shows a status badge whose text is the workflow's status
    expect(screen.getAllByText("running").length).toBeGreaterThan(0);
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
  });

  it("renders the page in a focus-trap-safe way: no positive tabindex traps", () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    // No element should carry a positive tabindex, which would break
    // the natural tab order.
    const positive = document.querySelectorAll('[tabindex]:not([tabindex="-1"]):not([tabindex="0"])');
    expect(positive.length).toBe(0);
  });

  // ------------------------------------------------------------------
  // Keyboard shortcuts (j/k/Enter)
  // ------------------------------------------------------------------

  it("renders the workflow grid as a listbox with options", () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const listbox = screen.getByRole("listbox", { name: /workflows/i });
    expect(listbox).toBeInTheDocument();
    const options = screen.getAllByRole("option");
    expect(options.length).toBe(2);
  });

  it("marks the first workflow as selected by default", () => {
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(options[1]).toHaveAttribute("aria-selected", "false");
  });

  it("captures the j/k/Enter handler map from useKeyboardShortcuts", async () => {
    const mod = await import("@/hooks/useKeyboardShortcuts");
    const spy = mod.useKeyboardShortcuts as unknown as ReturnType<typeof vi.fn>;
    mockWorkflowsQuery({ data: workflowsResponse });
    render(<WorkflowsPage />);
    const calls = spy.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const last = calls[calls.length - 1][0] as Record<string, unknown>;
    expect(typeof last.j).toBe("function");
    expect(typeof last.k).toBe("function");
    expect(typeof last.Enter).toBe("function");
  });
});
