import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import EscalationPage from "./page";
import * as useWorkflowHooks from "@/hooks/useWorkflow";
import * as useWorkflowEventsHooks from "@/hooks/useWorkflowEvents";
import type { WorkflowDetail, WorkflowWorkflowEvent } from "@/lib/types";

// ------------------------------------------------------------------
// Mocks
// ------------------------------------------------------------------

const mockToast = vi.fn();
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: mockToast }),
}));

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

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

const pausedWorkflow: WorkflowDetail = {
  id: "wf-123",
  name: "Test Workflow",
  description: "A test workflow",
  status: "paused",
  dag_definition: {},
  created_at: "2026-06-12T10:00:00Z",
  updated_at: "2026-06-12T10:05:00Z",
  pause_reason: "Needs human approval for tool call",
  pause_duration: 300,
  pause_cycles: 4,
  pause_tokens: 1250,
};

const runningWorkflow: WorkflowDetail = {
  id: "wf-123",
  name: "Test Workflow",
  description: "A test workflow",
  status: "running",
  dag_definition: {},
  created_at: "2026-06-12T10:00:00Z",
  updated_at: "2026-06-12T10:05:00Z",
};

const failedWorkflow: WorkflowDetail = {
  id: "wf-123",
  name: "Test Workflow",
  description: "A test workflow",
  status: "failed",
  dag_definition: {},
  created_at: "2026-06-12T10:00:00Z",
  updated_at: "2026-06-12T10:05:00Z",
  pause_reason: "Previous pause before failure",
};

// Escalated is a terminal, needs-attention status distinct from paused
// (resumable) and failed (node-level crash). The engine persists it when
// a workflow exhausts a safety limit (cycles/tokens/planner timeout).
const escalatedWorkflow: WorkflowDetail = {
  id: "wf-123",
  name: "Test Workflow",
  description: "A test workflow",
  status: "escalated",
  dag_definition: {},
  created_at: "2026-06-12T10:00:00Z",
  updated_at: "2026-06-12T10:05:00Z",
};

const sampleEscalationEvents: WorkflowWorkflowEvent[] = [
  {
    id: "evt-1",
    event_type: "ESCALATE",
    event_data: { reason: "High risk tool call" },
    sequence_number: 1,
    timestamp: "2026-06-12T10:01:00Z",
  },
  {
    id: "evt-2",
    event_type: "WORKFLOW_PAUSED",
    event_data: null,
    sequence_number: 2,
    timestamp: "2026-06-12T10:01:05Z",
  },
  {
    id: "evt-3",
    event_type: "HUMAN_INPUT_RECEIVED",
    event_data: { human_input: "Approved, proceed with caution" },
    sequence_number: 3,
    timestamp: "2026-06-12T10:02:00Z",
  },
  {
    id: "evt-4",
    event_type: "WORKFLOW_RESUMED",
    event_data: null,
    sequence_number: 4,
    timestamp: "2026-06-12T10:02:01Z",
  },
];

const nonEscalationEvents: WorkflowWorkflowEvent[] = [
  {
    id: "evt-5",
    event_type: "PLAN_GENERATED",
    event_data: null,
    sequence_number: 5,
    timestamp: "2026-06-12T10:00:00Z",
  },
];

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

describe("EscalationPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    mockToast.mockClear();
    vi.restoreAllMocks();
  });

  async function renderPage(params: { id: string }, workflowData?: WorkflowDetail, eventsData?: WorkflowWorkflowEvent[]) {
    vi.spyOn(useWorkflowHooks, "useWorkflow").mockReturnValue({
      data: workflowData ?? undefined,
      isLoading: workflowData === undefined && !workflowData,
      error: null,
      isError: false,
      isPending: workflowData === undefined,
      isSuccess: !!workflowData,
      status: workflowData ? "success" : "pending",
      fetchStatus: "idle",
      isLoadingError: false,
      isRefetchError: false,
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isFetched: true,
      isFetchedAfterMount: true,
      isFetching: false,
      isInitialLoading: false,
      isPaused: false,
      isPlaceholderData: false,
      isStale: false,
      refetch: vi.fn(),
      remove: vi.fn(),
    } as never);

    vi.spyOn(useWorkflowEventsHooks, "useWorkflowWorkflowEvents").mockReturnValue({
      data: eventsData ?? undefined,
      isLoading: eventsData === undefined && !eventsData,
      error: null,
      isError: false,
      isPending: eventsData === undefined,
      isSuccess: !!eventsData,
      status: eventsData ? "success" : "pending",
      fetchStatus: "idle",
      isLoadingError: false,
      isRefetchError: false,
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isFetched: true,
      isFetchedAfterMount: true,
      isFetching: false,
      isInitialLoading: false,
      isPaused: false,
      isPlaceholderData: false,
      isStale: false,
      refetch: vi.fn(),
      remove: vi.fn(),
    } as never);

    const resumeMutate = vi.fn();
    const cancelMutate = vi.fn();

    vi.spyOn(useWorkflowHooks, "useResumeWorkflow").mockReturnValue({
      mutate: resumeMutate,
      mutateAsync: vi.fn(),
      isPending: false,
      isIdle: true,
      isError: false,
      isSuccess: false,
      status: "idle",
      data: undefined,
      error: null,
      reset: vi.fn(),
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);

    vi.spyOn(useWorkflowHooks, "useCancelWorkflow").mockReturnValue({
      mutate: cancelMutate,
      mutateAsync: vi.fn(),
      isPending: false,
      isIdle: true,
      isError: false,
      isSuccess: false,
      status: "idle",
      data: undefined,
      error: null,
      reset: vi.fn(),
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);

    let result: ReturnType<typeof render> | undefined;
    await act(async () => {
      result = render(
        <QueryClientProvider client={queryClient}>
          <EscalationPage params={Promise.resolve(params)} />
        </QueryClientProvider>
      );
    });

    return { ...result!, resumeMutate, cancelMutate };
  }

  // 1. Pause panel visibility
  it("renders pause state panel when workflow is paused", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);

    expect(screen.getByText("Workflow Paused")).toBeInTheDocument();
    expect(screen.getByText("Awaiting Human Input")).toBeInTheDocument();
    expect(screen.getByText("Needs human approval for tool call")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument(); // cycles
    expect(screen.getByText("1,250")).toBeInTheDocument(); // tokens
  });

  it("shows pause reason from workflow detail", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    expect(screen.getByText("Needs human approval for tool call")).toBeInTheDocument();
  });

  it("shows cycle count, tokens used, and duration in pause panel", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("1,250")).toBeInTheDocument();
    expect(screen.getByText(/5m 0s/)).toBeInTheDocument();
  });

  it("does not render pause panel when workflow is not paused", async () => {
    await renderPage({ id: "wf-123" }, runningWorkflow, []);
    expect(screen.queryByText("Workflow Paused")).not.toBeInTheDocument();
  });

  // 2. Input editor
  it("renders human input textarea when workflow is paused", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    expect(
      screen.getByPlaceholderText("Enter your response to resume the workflow...")
    ).toBeInTheDocument();
  });

  it("does not render input editor when workflow is not paused", async () => {
    await renderPage({ id: "wf-123" }, runningWorkflow, []);
    expect(
      screen.queryByPlaceholderText("Enter your response to resume the workflow...")
    ).not.toBeInTheDocument();
  });

  it("updates textarea value on input", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    const textarea = screen.getByPlaceholderText(
      "Enter your response to resume the workflow..."
    );
    fireEvent.change(textarea, { target: { value: "Approve this step" } });
    expect(textarea).toHaveValue("Approve this step");
  });

  it("shows markdown preview when preview button is clicked", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    const textarea = screen.getByPlaceholderText(
      "Enter your response to resume the workflow..."
    );
    fireEvent.change(textarea, { target: { value: "**bold** text" } });
    fireEvent.click(screen.getByRole("button", { name: /Show preview/i }));
    expect(screen.getByLabelText("Markdown preview")).toBeInTheDocument();
  });

  // 3. Resume / Cancel button presence
  it("renders submit & resume button when paused", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    expect(screen.getByRole("button", { name: /Submit & Resume/i })).toBeInTheDocument();
  });

  it("disables submit button when textarea is empty", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    const btn = screen.getByRole("button", { name: /Submit & Resume/i });
    expect(btn).toBeDisabled();
  });

  it("enables submit button when textarea has content", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    const textarea = screen.getByPlaceholderText(
      "Enter your response to resume the workflow..."
    );
    fireEvent.change(textarea, { target: { value: "Go ahead" } });
    const btn = screen.getByRole("button", { name: /Submit & Resume/i });
    expect(btn).not.toBeDisabled();
  });

  it("renders cancel button when workflow can be cancelled", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    expect(screen.getByRole("button", { name: /Cancel Workflow/i })).toBeInTheDocument();
  });

  it("requires confirmation before cancelling", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    const cancelBtn = screen.getByRole("button", { name: /Cancel Workflow/i });
    fireEvent.click(cancelBtn);
    expect(screen.getByRole("button", { name: /Confirm Cancel/i })).toBeInTheDocument();
  });

  it("does not render cancel button for completed workflow", async () => {
    const completedWorkflow: WorkflowDetail = {
      ...runningWorkflow,
      status: "completed",
    };
    await renderPage({ id: "wf-123" }, completedWorkflow, []);
    expect(screen.queryByRole("button", { name: /Cancel Workflow/i })).not.toBeInTheDocument();
  });

  it("does not render resume-related controls for running workflow", async () => {
    await renderPage({ id: "wf-123" }, runningWorkflow, []);
    expect(screen.queryByRole("button", { name: /Submit & Resume/i })).not.toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Escalated status: terminal, needs-attention, NOT resumable.
  // Regression: escalated used to fall through to the default StatusPanel
  // ("Workflow status: escalated") and render a benign muted badge. It now
  // has an explicit StatusPanel entry and a danger badge.
  // ------------------------------------------------------------------
  it("renders the escalated StatusPanel message for an escalated workflow", async () => {
    await renderPage({ id: "wf-123" }, escalatedWorkflow, []);
    // The dedicated escalated message mentions the safety-limit escalation.
    expect(
      screen.getByText(/escalated after exhausting a safety limit/i)
    ).toBeInTheDocument();
  });

  it("renders an 'escalated' status badge for an escalated workflow", async () => {
    await renderPage({ id: "wf-123" }, escalatedWorkflow, []);
    // The header badge shows the workflow's status text.
    expect(screen.getAllByText("escalated").length).toBeGreaterThan(0);
  });

  it("does not render resume controls for an escalated (terminal) workflow", async () => {
    await renderPage({ id: "wf-123" }, escalatedWorkflow, []);
    // Escalated is terminal and out-of-band — there is nothing to resume.
    expect(
      screen.queryByRole("button", { name: /Submit & Resume/i })
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Workflow Paused")).not.toBeInTheDocument();
  });

  // 4. History rendering
  it("renders escalation history timeline", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, sampleEscalationEvents);
    expect(screen.getByText("Escalation History")).toBeInTheDocument();
    expect(screen.getByText("Escalated")).toBeInTheDocument();
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.getByText("Human Input")).toBeInTheDocument();
    expect(screen.getByText("Resumed")).toBeInTheDocument();
  });

  it("shows human input content in history", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, sampleEscalationEvents);
    expect(screen.getByText("Approved, proceed with caution")).toBeInTheDocument();
  });

  it("filters non-escalation events from history", async () => {
    await renderPage(
      { id: "wf-123" },
      pausedWorkflow,
      [...sampleEscalationEvents, ...nonEscalationEvents]
    );
    expect(screen.queryByText("PLAN_GENERATED")).not.toBeInTheDocument();
    expect(screen.getAllByText(/Escalated|Paused|Human Input|Resumed/).length).toBeGreaterThan(0);
  });

  it("shows empty state when no escalation events", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    expect(screen.getByText("No escalation events recorded")).toBeInTheDocument();
  });

  it("shows events in chronological order", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, [
      sampleEscalationEvents[3], // RESUMED (latest in data, should be last in timeline)
      sampleEscalationEvents[0], // ESCALATE (earliest, should be first)
      sampleEscalationEvents[1], // PAUSED
      sampleEscalationEvents[2], // HUMAN_INPUT
    ]);
    const list = screen.getByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(items.length).toBe(4);
    // First should be ESCALATE, last should be RESUMED
    expect(within(items[0]).getByText("Escalated")).toBeInTheDocument();
    expect(within(items[3]).getByText("Resumed")).toBeInTheDocument();
  });

  // 5. Loading state
  it("shows loading skeleton while workflow is loading", async () => {
    vi.spyOn(useWorkflowHooks, "useWorkflow").mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      isError: false,
      isPending: true,
      isSuccess: false,
      status: "pending",
      fetchStatus: "fetching",
      isLoadingError: false,
      isRefetchError: false,
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isFetched: false,
      isFetchedAfterMount: false,
      isFetching: true,
      isInitialLoading: true,
      isPaused: false,
      isPlaceholderData: false,
      isStale: false,
      refetch: vi.fn(),
      remove: vi.fn(),
    } as never);

    vi.spyOn(useWorkflowEventsHooks, "useWorkflowWorkflowEvents").mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      isError: false,
      isPending: true,
      isSuccess: false,
      status: "pending",
      fetchStatus: "fetching",
      isLoadingError: false,
      isRefetchError: false,
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isFetched: false,
      isFetchedAfterMount: false,
      isFetching: true,
      isInitialLoading: true,
      isPaused: false,
      isPlaceholderData: false,
      isStale: false,
      refetch: vi.fn(),
      remove: vi.fn(),
    } as never);

    vi.spyOn(useWorkflowHooks, "useResumeWorkflow").mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isIdle: true,
      isError: false,
      isSuccess: false,
      status: "idle",
      data: undefined,
      error: null,
      reset: vi.fn(),
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);

    vi.spyOn(useWorkflowHooks, "useCancelWorkflow").mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isIdle: true,
      isError: false,
      isSuccess: false,
      status: "idle",
      data: undefined,
      error: null,
      reset: vi.fn(),
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);

    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <EscalationPage params={Promise.resolve({ id: "wf-123" })} />
        </QueryClientProvider>
      );
    });

    // Loading skeletons should be present
    expect(document.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  // 6. Error state
  it("shows error panel when workflow fetch fails", async () => {
    vi.spyOn(useWorkflowHooks, "useWorkflow").mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("Network timeout"),
      isError: true,
      isPending: false,
      isSuccess: false,
      status: "error",
      fetchStatus: "idle",
      isLoadingError: true,
      isRefetchError: false,
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      failureCount: 1,
      failureReason: new Error("Network timeout"),
      errorUpdateCount: 1,
      isFetched: true,
      isFetchedAfterMount: true,
      isFetching: false,
      isInitialLoading: false,
      isPaused: false,
      isPlaceholderData: false,
      isStale: false,
      refetch: vi.fn(),
      remove: vi.fn(),
    } as never);

    vi.spyOn(useWorkflowEventsHooks, "useWorkflowWorkflowEvents").mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
      isError: false,
      isPending: false,
      isSuccess: true,
      status: "success",
      fetchStatus: "idle",
      isLoadingError: false,
      isRefetchError: false,
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isFetched: true,
      isFetchedAfterMount: true,
      isFetching: false,
      isInitialLoading: false,
      isPaused: false,
      isPlaceholderData: false,
      isStale: false,
      refetch: vi.fn(),
      remove: vi.fn(),
    } as never);

    vi.spyOn(useWorkflowHooks, "useResumeWorkflow").mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isIdle: true,
      isError: false,
      isSuccess: false,
      status: "idle",
      data: undefined,
      error: null,
      reset: vi.fn(),
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);

    vi.spyOn(useWorkflowHooks, "useCancelWorkflow").mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isIdle: true,
      isError: false,
      isSuccess: false,
      status: "idle",
      data: undefined,
      error: null,
      reset: vi.fn(),
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);

    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <EscalationPage params={Promise.resolve({ id: "wf-123" })} />
        </QueryClientProvider>
      );
    });

    expect(screen.getByText("Failed to load workflow details")).toBeInTheDocument();
    expect(screen.getByText("Network timeout")).toBeInTheDocument();
  });

  // 7. Accessibility
  it("has aria-live region for action outcomes", async () => {
    // Custom render: use the real onSuccess-calling mutation mock so the
    // page's setActionSuccess() fires and the role="status" element renders.
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    vi.spyOn(useWorkflowHooks, "useWorkflow").mockReturnValue({
      data: pausedWorkflow,
      isLoading: false,
      error: null,
      isError: false,
      isPending: false,
      isSuccess: true,
      status: "success",
      fetchStatus: "idle",
      isLoadingError: false,
      isRefetchError: false,
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isFetched: true,
      isFetchedAfterMount: true,
      isFetching: false,
      isInitialLoading: false,
      isPaused: false,
      isPlaceholderData: false,
      isStale: false,
      refetch: vi.fn(),
      remove: vi.fn(),
    } as never);

    vi.spyOn(useWorkflowEventsHooks, "useWorkflowWorkflowEvents").mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
      isError: false,
      isPending: false,
      isSuccess: true,
      status: "success",
      fetchStatus: "idle",
      isLoadingError: false,
      isRefetchError: false,
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isFetched: true,
      isFetchedAfterMount: true,
      isFetching: false,
      isInitialLoading: false,
      isPaused: false,
      isPlaceholderData: false,
      isStale: false,
      refetch: vi.fn(),
      remove: vi.fn(),
    } as never);

    vi.spyOn(useWorkflowHooks, "useCancelWorkflow").mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isIdle: true,
      isError: false,
      isSuccess: false,
      data: undefined,
      error: null,
      reset: vi.fn(),
      status: "idle",
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);

    // This is the key: the mutate mock invokes onSuccess so the page's
    // setActionSuccess() fires and the role="status" element renders.
    vi.spyOn(useWorkflowHooks, "useResumeWorkflow").mockReturnValue({
      mutate: (_vars: unknown, opts?: { onSuccess?: () => void }) => {
        opts?.onSuccess?.();
      },
      mutateAsync: vi.fn(),
      isPending: false,
      isIdle: true,
      isError: false,
      isSuccess: false,
      data: undefined,
      error: null,
      reset: vi.fn(),
      status: "idle",
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);

    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <EscalationPage params={Promise.resolve({ id: "wf-123" })} />
        </QueryClientProvider>
      );
    });

    const textarea = screen.getByLabelText(/Human Response/i);
    fireEvent.change(textarea, { target: { value: "Looks good, continue" } });
    const submitButton = screen.getByRole("button", { name: /Submit & Resume/i });
    fireEvent.click(submitButton);
    const liveRegion = await screen.findByRole("status", { hidden: true });
    expect(liveRegion).toHaveTextContent(/Workflow resumed successfully/i);
  });

  it("has proper label for textarea", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    const textarea = screen.getByPlaceholderText(
      "Enter your response to resume the workflow..."
    );
    expect(textarea).toHaveAttribute("id", "human-input");
    expect(textarea).toHaveAttribute("aria-describedby", "human-input-help");
  });

  // 8. Status panel for non-paused workflows
  it("shows status panel for running workflow", async () => {
    await renderPage({ id: "wf-123" }, runningWorkflow, []);
    expect(screen.getAllByText("running").length).toBeGreaterThan(0);
    expect(screen.getByText(/No human intervention required/)).toBeInTheDocument();
  });

  it("shows status panel for failed workflow with last pause reason", async () => {
    await renderPage({ id: "wf-123" }, failedWorkflow, []);
    expect(screen.getAllByText("failed").length).toBeGreaterThan(0);
    expect(screen.getByText(/Previous pause before failure/)).toBeInTheDocument();
  });

  // 9. Navigation
  it("renders workflow nav with escalation tab active", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    const nav = screen.getByTestId("workflow-nav");
    expect(nav).toHaveAttribute("data-active-tab", "escalation");
  });

  // 10. Shell wrapper
  it("is wrapped in Shell component", async () => {
    await renderPage({ id: "wf-123" }, pausedWorkflow, []);
    expect(screen.getByTestId("shell")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------
// Lane C: MNT-005 — async params (Next.js 16)
// ------------------------------------------------------------------

describe("EscalationPage — async params (Next.js 16)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // MNT-005 regression: in Next.js 16, `params` is a Promise. The
  // page must unwrap it with React.use(params). Without unwrapping,
  // id is undefined and id.slice(0, 8) throws.
  it("unwraps async params and renders the breadcrumb with the id slice", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    vi.spyOn(useWorkflowHooks, "useWorkflow").mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      isError: false,
      isPending: true,
      isSuccess: false,
      status: "pending",
      fetchStatus: "fetching",
      isFetching: true,
      isStale: false,
      refetch: vi.fn(),
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isLoadingError: false,
      isRefetchError: false,
      isFetched: false,
      isFetchedAfterMount: false,
      isRefetching: false,
      isEnabled: true,
      isInitialLoading: true,
      isPlaceholderData: false,
      promise: Promise.resolve(undefined),
    } as never);
    vi.spyOn(useWorkflowHooks, "useWorkflowStatus").mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);
    vi.spyOn(useWorkflowHooks, "useResumeWorkflow").mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isLoading: false,
      isError: false,
      isSuccess: false,
      data: undefined,
      error: null,
      reset: vi.fn(),
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);
    vi.spyOn(useWorkflowHooks, "useCancelWorkflow").mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isLoading: false,
      isError: false,
      isSuccess: false,
      data: undefined,
      error: null,
      reset: vi.fn(),
      variables: undefined,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isPaused: false,
      submittedAt: 0,
    } as never);
    vi.spyOn(useWorkflowEventsHooks, "useWorkflowWorkflowEvents").mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as never);

    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <EscalationPage params={Promise.resolve({ id: "wf-escalation-id" })} />
        </QueryClientProvider>
      );
    });

    // Look for the id slice in the rendered DOM.
    expect(screen.getAllByText("wf-escal").length).toBeGreaterThan(0);
  });
});
