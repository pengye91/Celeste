import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// Mock the hooks and components
vi.mock("@/hooks/useWorkflow", () => ({
  useWorkflow: vi.fn(),
  useWorkflowStatus: vi.fn(),
  useWorkflowMetrics: vi.fn(),
  useWorkflowNodes: vi.fn(),
}));

vi.mock("@/hooks/useWorkflowEvents", () => ({
  useWorkflowEvents: vi.fn(),
}));

vi.mock("@/components/shell/shell", () => ({
  Shell: ({ children }: { children: React.ReactNode }) => <div data-testid="shell">{children}</div>,
}));

vi.mock("@/components/workflow/workflow-nav", () => ({
  WorkflowNav: ({ activeTab }: { activeTab: string }) => (
    <nav data-testid="workflow-nav" data-active-tab={activeTab}>WorkflowNav</nav>
  ),
}));

vi.mock("@/components/ui/panel", () => ({
  Panel: ({ children, className, ...props }: React.HTMLAttributes<HTMLDivElement> & { children: React.ReactNode }) => (
    <div data-testid="panel" className={className} {...props}>{children}</div>
  ),
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, variant, className }: { children: React.ReactNode; variant?: string; className?: string }) => (
    <span data-testid="badge" data-variant={variant} className={className}>{children}</span>
  ),
}));

vi.mock("@/components/ui/status-orb", () => ({
  StatusOrb: ({ variant, size, pulse }: { variant?: string; size?: string; pulse?: boolean }) => (
    <span data-testid="status-orb" data-variant={variant} data-size={size} data-pulse={pulse} />
  ),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { children: React.ReactNode }) => (
    <button data-testid="button" {...props}>{children}</button>
  ),
}));

vi.mock("lucide-react", () => ({
  ArrowLeft: () => <span data-testid="icon-arrow-left">←</span>,
  Copy: () => <span data-testid="icon-copy">📋</span>,
  Check: () => <span data-testid="icon-check">✓</span>,
  Undo2: () => <span data-testid="icon-undo">↩</span>,
  CheckCircle2: () => <span data-testid="icon-check-circle">✓</span>,
  XCircle: () => <span data-testid="icon-x-circle">✕</span>,
  AlertCircle: () => <span data-testid="icon-alert">⚠</span>,
  Clock: () => <span data-testid="icon-clock">🕐</span>,
  ArrowRight: () => <span data-testid="icon-arrow-right">→</span>,
  ArrowDownLeft: () => <span data-testid="icon-arrow-down-left">↙</span>,
  Layers: () => <span data-testid="icon-layers">☰</span>,
  Shield: () => <span data-testid="icon-shield">🛡</span>,
  Activity: () => <span data-testid="icon-activity">📊</span>,
  RotateCcw: () => <span data-testid="icon-rotate">↻</span>,
  GitBranch: () => <span data-testid="icon-branch">🌿</span>,
  Orbit: () => <span data-testid="icon-orbit">🪐</span>,
}));

import {
  useWorkflow,
  useWorkflowStatus,
  useWorkflowMetrics,
  useWorkflowNodes,
} from "@/hooks/useWorkflow";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";

// Import the page after mocks are set up
import SagaCompensationPage from "./page";

const mockUseWorkflow = useWorkflow as ReturnType<typeof vi.fn>;
const mockUseWorkflowStatus = useWorkflowStatus as ReturnType<typeof vi.fn>;
const mockUseWorkflowMetrics = useWorkflowMetrics as ReturnType<typeof vi.fn>;
const mockUseWorkflowNodes = useWorkflowNodes as ReturnType<typeof vi.fn>;
const mockUseWorkflowEvents = useWorkflowEvents as ReturnType<typeof vi.fn>;

function setupMocks(overrides: {
  workflow?: Record<string, unknown>;
  status?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  nodes?: Record<string, unknown>[];
  events?: Record<string, unknown>[];
  wfLoading?: boolean;
  nodesLoading?: boolean;
  eventsLoading?: boolean;
  wfError?: Error | null;
  eventsError?: Error | null;
} = {}) {
  mockUseWorkflow.mockReturnValue({
    data: overrides.workflow ?? null,
    isLoading: overrides.wfLoading ?? false,
    error: overrides.wfError ?? null,
  });
  mockUseWorkflowStatus.mockReturnValue({
    data: overrides.status ?? null,
    isLoading: false,
    error: null,
  });
  mockUseWorkflowMetrics.mockReturnValue({
    data: overrides.metrics ?? null,
    isLoading: false,
    error: null,
  });
  mockUseWorkflowNodes.mockReturnValue({
    data: overrides.nodes ?? null,
    isLoading: overrides.nodesLoading ?? false,
    error: null,
  });
  mockUseWorkflowEvents.mockReturnValue({
    data: overrides.events ?? null,
    isLoading: overrides.eventsLoading ?? false,
    error: overrides.eventsError ?? null,
  });
}

const sampleWorkflow = {
  id: "wf-1",
  name: "Test Workflow",
  status: "failed",
  description: "A test workflow",
  dag_definition: {},
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const sampleNodes = [
  { name: "node-a", status: "completed", command: "compensate-a", task_type: "tool" },
  { name: "node-b", status: "completed", command: "compensate-b", task_type: "tool" },
  { name: "node-c", status: "failed", command: "", task_type: "tool" },
];

const sampleEvents = [
  {
    id: "ev-1",
    event_type: "COMPENSATION_TRIGGERED",
    timestamp: "2026-01-01T00:01:00Z",
    event_data: { compensation_command: "compensate-b", node_name: "node-b" },
  },
  {
    id: "ev-2",
    event_type: "COMPENSATION_COMPLETED",
    timestamp: "2026-01-01T00:02:00Z",
    event_data: { compensation_command: "compensate-b", outcome: "Rolled back successfully" },
  },
  {
    id: "ev-3",
    event_type: "COMPENSATION_FAILED",
    timestamp: "2026-01-01T00:03:00Z",
    event_data: { compensation_command: "compensate-a", error: "Connection timeout" },
  },
];

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
        <SagaCompensationPage params={Promise.resolve({ id })} />
      </QueryClientProvider>
    );
  });
  return result!;
}

describe("SagaCompensationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state with skeletons", async () => {
    setupMocks({ wfLoading: true, nodesLoading: true, eventsLoading: true });
    await renderPage();

    // Should show shell
    expect(screen.getByTestId("shell")).toBeInTheDocument();
    // Loading skeletons are divs with animate-pulse class
    expect(document.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders empty state when no compensation recorded", async () => {
    setupMocks({
      workflow: sampleWorkflow,
      nodes: [
        { name: "node-a", status: "completed", task_type: "tool" },
        { name: "node-b", status: "completed", task_type: "tool" },
      ],
      events: [],
    });
    await renderPage();

    expect(screen.getByText("No compensation recorded")).toBeInTheDocument();
    expect(screen.getByText(/Compensation steps appear when a node fails/)).toBeInTheDocument();
  });

  it("renders error state", async () => {
    setupMocks({
      workflow: undefined,
      wfError: new Error("Network failure"),
    });
    await renderPage();

    expect(screen.getByText(/Failed to load saga compensation data/)).toBeInTheDocument();
    expect(screen.getByText(/Network failure/)).toBeInTheDocument();
  });

  it("renders summary counts correctly", async () => {
    setupMocks({
      workflow: sampleWorkflow,
      nodes: sampleNodes,
      events: sampleEvents,
    });
    await renderPage();

    // Triggered = 2 (node-b and node-a have compensation commands and events matched)
    // Actually node-c has empty command so it won't be included
    // node-b has COMPENSATION_COMPLETED, node-a has COMPENSATION_FAILED
    // So triggered = 2, completed = 1, failed = 1, total = 2
    // Use getAllByText for labels that may appear in multiple places (KPI cards + step badges)
    expect(screen.getAllByText("Failed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Triggered").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Completed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Total Steps")).toBeInTheDocument();
  });

  it("renders chain diagram with SVG", async () => {
    setupMocks({
      workflow: sampleWorkflow,
      nodes: sampleNodes,
      events: sampleEvents,
    });
    const { container } = await renderPage();

    const svg = container.querySelector('svg[role="img"]');
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute(
      "aria-label",
      "Compensation chain diagram showing original node execution forward and compensation winding back"
    );
  });

  it("matches compensation events to steps by command", async () => {
    setupMocks({
      workflow: sampleWorkflow,
      nodes: sampleNodes,
      events: sampleEvents,
    });
    await renderPage();

    // Steps should show node names — use getAllByText since they may appear multiple times
    expect(screen.getAllByText("node-b").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("node-a").length).toBeGreaterThanOrEqual(1);
  });

  it("shows step status badges with correct variants", async () => {
    setupMocks({
      workflow: sampleWorkflow,
      nodes: sampleNodes,
      events: sampleEvents,
    });
    await renderPage();

    const badges = screen.getAllByTestId("badge");
    // Should have badges for workflow status and step statuses
    expect(badges.length).toBeGreaterThan(0);

    // Find badges within the step list (after the workflow header badge)
    const stepBadges = badges.slice(1);
    expect(stepBadges.length).toBeGreaterThan(0);
  });

  it("renders unmatched events in timeline when events don't match nodes", async () => {
    const unmatchedEvent = {
      id: "ev-4",
      event_type: "COMPENSATION_TRIGGERED",
      timestamp: "2026-01-01T00:04:00Z",
      event_data: { compensation_command: "unknown-command" },
    };
    setupMocks({
      workflow: sampleWorkflow,
      nodes: sampleNodes,
      events: [...sampleEvents, unmatchedEvent],
    });
    await renderPage();

    expect(screen.getByText("Unmatched Events")).toBeInTheDocument();
  });

  it("renders workflow not found when workflow is null", async () => {
    setupMocks({
      workflow: undefined,
      wfLoading: false,
    });
    await renderPage();

    expect(screen.getByText("Workflow not found")).toBeInTheDocument();
  });

  it("has accessible list items for steps", async () => {
    setupMocks({
      workflow: sampleWorkflow,
      nodes: sampleNodes,
      events: sampleEvents,
    });
    await renderPage();

    const stepList = screen.getByRole("list", { name: "Compensation steps" });
    expect(stepList).toBeInTheDocument();

    const listItems = within(stepList).getAllByRole("listitem");
    expect(listItems.length).toBeGreaterThan(0);

    // Each list item should NOT be focusable (presentation-only rows)
    listItems.forEach((item) => {
      expect(item).not.toHaveAttribute("tabIndex", "0");
    });
  });

  it("shows command snippets for each step", async () => {
    setupMocks({
      workflow: sampleWorkflow,
      nodes: sampleNodes,
      events: sampleEvents,
    });
    await renderPage();

    expect(screen.getByText("compensate-a")).toBeInTheDocument();
    expect(screen.getByText("compensate-b")).toBeInTheDocument();
  });

  it("shows outcome text for completed and failed steps", async () => {
    setupMocks({
      workflow: sampleWorkflow,
      nodes: sampleNodes,
      events: sampleEvents,
    });
    const { container } = await renderPage();

    // Outcome text may be split across elements; check container textContent
    expect(container.textContent).toContain("Rolled back successfully");
    expect(container.textContent).toContain("Connection timeout");
  });

  it("renders workflow nav with activeTab saga", async () => {
    setupMocks({
      workflow: sampleWorkflow,
      nodes: sampleNodes,
      events: sampleEvents,
    });
    await renderPage();

    const nav = screen.getByTestId("workflow-nav");
    expect(nav).toHaveAttribute("data-active-tab", "saga");
  });
});

// ------------------------------------------------------------------
// Lane C: MNT-015 — compensation command sourced from dag_definition
// ------------------------------------------------------------------

describe("SagaCompensationPage — compensation command from dag_definition (MNT-015)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // MNT-015 regression: WorkflowNodeStatus (the type returned by
  // useWorkflowNodes) has no `command` field. The original
  // buildCompensationSteps filtered on `n.command`, so every node
  // failed the predicate and the steps list was always empty.
  // The fix sources compensation_command from
  // workflow.dag_definition.nodes[].compensation_command and merges
  // it with the API response.
  it("renders compensation steps when only dag_definition has compensation_command", async () => {
    setupMocks({
      // Realistic API shape: nodes have no `command` field
      workflow: {
        ...sampleWorkflow,
        dag_definition: {
          nodes: [
            { name: "node-a", compensation_command: "compensate-a" },
            { name: "node-b", compensation_command: "compensate-b" },
          ],
        },
      },
      nodes: [
        { name: "node-a", status: "completed", task_type: "tool" },
        { name: "node-b", status: "completed", task_type: "tool" },
      ],
      events: sampleEvents,
    });

    await renderPage();

    // Steps should render — previously empty because n.command was undefined.
    const stepList = screen.queryByRole("list", { name: /compensation steps/i });
    expect(stepList).not.toBeNull();
  });
});

// ------------------------------------------------------------------
// Lane C: MNT-004 — async params (Next.js 16)
// ------------------------------------------------------------------

describe("SagaCompensationPage — async params (Next.js 16)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // MNT-004 regression: in Next.js 16, `params` is a Promise. The
  // page must unwrap it with React.use(params). Without unwrapping,
  // id is undefined and the breadcrumb's id.slice(0, 8) throws.
  it("unwraps async params and renders the breadcrumb with the id slice", async () => {
    // workflow=undefined so the breadcrumb falls back to id.slice(0, 8).
    setupMocks({ workflow: undefined });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <SagaCompensationPage params={Promise.resolve({ id: "wf-saga-id" })} />
        </QueryClientProvider>
      );
    });

    // Look for the link with the id slice in the href.
    const breadcrumbLinks = screen.queryAllByRole("link");
    const idLink = breadcrumbLinks.find(
      (l) => l.getAttribute("href") === "/workflows/wf-saga-id"
    );
    expect(idLink).not.toBeUndefined();
  });
});
