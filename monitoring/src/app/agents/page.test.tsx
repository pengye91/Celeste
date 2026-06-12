import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AgentsPage from "./page";
import * as useAgentsModule from "@/hooks/useAgents";
import * as useToastModule from "@/hooks/useToast";
import type {
  AgentListItem,
  RegisterAgentRequest,
  RegisterAgentResponse,
} from "@/lib/types";

// ------------------------------------------------------------------
// Mocks
// ------------------------------------------------------------------

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

// ------------------------------------------------------------------
// Fixtures
// ------------------------------------------------------------------

const sampleAgents: AgentListItem[] = [
  {
    agent_id: "agent-1",
    url: "https://agent-1.example.com",
    status: "connected",
    metadata: { region: "us-east-1", tier: "gold" },
    registered_at: "2026-06-12T10:00:00Z",
  },
  {
    agent_id: "agent-2",
    url: "https://agent-2.example.com",
    status: "disconnected",
    metadata: { region: "eu-west-1" },
    registered_at: "2026-06-12T09:00:00Z",
  },
  {
    agent_id: "agent-3",
    url: "https://agent-3.example.com",
    status: "connecting",
    metadata: {},
    registered_at: "2026-06-12T08:00:00Z",
  },
];

// Minimal UseQueryResult-like shape for mocking
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
  error: Error | null,
  isFetching: boolean = false,
): MockQueryResult<T> {
  return {
    data,
    isLoading,
    error,
    isPending: isLoading,
    isError: !!error,
    isSuccess: !!data && !error,
    status: isLoading ? "pending" : error ? "error" : "success",
    fetchStatus: isFetching ? "fetching" : "idle",
    isFetching,
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

interface MockMutationResult<V, E, I> {
  mutate: ReturnType<typeof vi.fn>;
  mutateAsync: ReturnType<typeof vi.fn>;
  data: V | undefined;
  error: E | null;
  isError: boolean;
  isIdle: boolean;
  isPending: boolean;
  isSuccess: boolean;
  status: string;
  variables: I | undefined;
  reset: ReturnType<typeof vi.fn>;
  context: unknown;
  failureCount: number;
  failureReason: unknown;
  isPaused: boolean;
  submittedAt: number;
}

function makeMockMutationResult<V, E, I>(
  mutate: ReturnType<typeof vi.fn>,
  isPending: boolean = false,
  error: E | null = null,
): MockMutationResult<V, E, I> {
  return {
    mutate,
    mutateAsync: vi.fn(),
    data: undefined,
    error,
    isError: !!error,
    isIdle: !isPending && !error,
    isPending,
    isSuccess: false,
    status: isPending ? "pending" : error ? "error" : "idle",
    variables: undefined,
    reset: vi.fn(),
    context: null,
    failureCount: 0,
    failureReason: null,
    isPaused: false,
    submittedAt: 0,
  };
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function mockAgentsQuery({
  data = undefined as AgentListItem[] | undefined,
  isLoading = false,
  error = null as Error | null,
  isFetching = false,
  refetch = vi.fn(),
}: {
  data?: AgentListItem[] | undefined;
  isLoading?: boolean;
  error?: Error | null;
  isFetching?: boolean;
  refetch?: ReturnType<typeof vi.fn>;
} = {}) {
  const result = makeMockQueryResult<AgentListItem[]>(
    data,
    isLoading,
    error,
    isFetching,
  );
  result.refetch = refetch;
  vi.spyOn(useAgentsModule, "useAgents").mockReturnValue(
    result as unknown as ReturnType<typeof useAgentsModule.useAgents>,
  );
  return refetch;
}

function mockRegisterMutation(
  mutate: ReturnType<typeof vi.fn>,
  isPending: boolean = false,
  error: Error | null = null,
) {
  vi.spyOn(useAgentsModule, "useRegisterAgent").mockReturnValue(
    makeMockMutationResult<RegisterAgentResponse, Error, RegisterAgentRequest>(
      mutate,
      isPending,
      error,
    ) as unknown as ReturnType<typeof useAgentsModule.useRegisterAgent>,
  );
}

function mockToast() {
  const toast = vi.fn();
  vi.spyOn(useToastModule, "useToast").mockReturnValue({ toast });
  return toast;
}

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

describe("AgentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ----------------------------------------------------------------
  // LOADING
  // ----------------------------------------------------------------
  it("renders loading state with 6 skeleton cards", () => {
    mockAgentsQuery({ isLoading: true });
    mockRegisterMutation(vi.fn());
    mockToast();
    render(<AgentsPage />);
    expect(screen.getByTestId("shell")).toBeInTheDocument();
    const skeletons = screen.getAllByTestId("agent-skeleton");
    expect(skeletons).toHaveLength(6);
  });

  // ----------------------------------------------------------------
  // EMPTY
  // ----------------------------------------------------------------
  it("renders empty state with illustration and expanded register form", () => {
    mockAgentsQuery({ data: [] });
    mockRegisterMutation(vi.fn());
    mockToast();
    render(<AgentsPage />);
    expect(screen.getByTestId("agents-empty-state")).toBeInTheDocument();
    // The empty-state illustration is rendered as an inline SVG with role=img
    expect(screen.getByRole("img", { name: /docking port/i })).toBeInTheDocument();
    // The register form is expanded by default in the empty state
    const urlInput = screen.getByLabelText(/agent url/i);
    expect(urlInput).toBeInTheDocument();
  });

  // ----------------------------------------------------------------
  // ERROR
  // ----------------------------------------------------------------
  it("renders error banner with retry button while still showing the register form", () => {
    const refetch = mockAgentsQuery({
      data: undefined,
      error: new Error("Network error"),
    });
    mockRegisterMutation(vi.fn());
    mockToast();
    render(<AgentsPage />);
    expect(screen.getByTestId("agents-error-banner")).toBeInTheDocument();
    expect(
      screen.getByText(/could not reach the agents endpoint/i),
    ).toBeInTheDocument();

    // The form is still rendered (so the operator can register a new agent)
    // but it's collapsed by default in the error state.
    const form = screen.getByTestId("register-agent-form");
    expect(form).toBeInTheDocument();

    // Click retry
    const retryButton = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retryButton);
    expect(refetch).toHaveBeenCalled();
  });

  // ----------------------------------------------------------------
  // SUCCESS
  // ----------------------------------------------------------------
  it("renders agent grid with status, URL, last seen, and metadata tags", () => {
    mockAgentsQuery({ data: sampleAgents });
    mockRegisterMutation(vi.fn());
    mockToast();
    render(<AgentsPage />);
    const grid = screen.getByTestId("agent-grid");
    expect(grid).toBeInTheDocument();

    // 3 agent cards
    const cards = screen.getAllByTestId("agent-card");
    expect(cards).toHaveLength(3);

    // URLs are visible
    expect(screen.getByText("https://agent-1.example.com")).toBeInTheDocument();
    expect(screen.getByText("https://agent-2.example.com")).toBeInTheDocument();

    // Status labels are rendered as text + icon
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
    expect(screen.getByText("Connecting")).toBeInTheDocument();

    // Metadata tags (use getAllByText where multiple agents share a key)
    expect(screen.getByText("us-east-1")).toBeInTheDocument();
    expect(screen.getByText("eu-west-1")).toBeInTheDocument();
    expect(screen.getAllByText("region:").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("tier:")).toBeInTheDocument();

    // Agent count in the header
    expect(screen.getByTestId("agent-count")).toHaveTextContent(
      "3 registered",
    );
  });

  // ----------------------------------------------------------------
  // PARTIAL
  // ----------------------------------------------------------------
  it("renders partial state: shows static grid + refreshing hint when heartbeats are refetching", () => {
    mockAgentsQuery({ data: sampleAgents, isFetching: true });
    mockRegisterMutation(vi.fn());
    mockToast();
    render(<AgentsPage />);

    // Grid still visible
    expect(screen.getByTestId("agent-grid")).toBeInTheDocument();
    expect(screen.getAllByTestId("agent-card")).toHaveLength(3);

    // Refreshing hint is announced
    expect(screen.getByText(/refreshing agent heartbeats/i)).toBeInTheDocument();
  });

  // ----------------------------------------------------------------
  // Form interactions
  // ----------------------------------------------------------------
  it("renders a URL validation error when submitting an invalid URL", async () => {
    mockAgentsQuery({ data: [] });
    const mutate = vi.fn();
    mockRegisterMutation(mutate);
    mockToast();
    render(<AgentsPage />);

    const urlInput = screen.getByLabelText(/agent url/i) as HTMLInputElement;
    fireEvent.change(urlInput, { target: { value: "not-a-url" } });

    const submitButton = screen.getByRole("button", { name: /register agent/i });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(
        screen.getByText(/enter a valid url starting with/i),
      ).toBeInTheDocument();
    });
    expect(mutate).not.toHaveBeenCalled();
  });

  it("calls mutate with the expected payload on valid submit", async () => {
    mockAgentsQuery({ data: [] });
    const mutate = vi.fn();
    mockRegisterMutation(mutate);
    const toast = mockToast();
    render(<AgentsPage />);

    const urlInput = screen.getByLabelText(/agent url/i);
    fireEvent.change(urlInput, {
      target: { value: "https://new.example.com" },
    });

    const submitButton = screen.getByRole("button", { name: /register agent/i });
    fireEvent.click(submitButton);

    expect(mutate).toHaveBeenCalledTimes(1);
    const [body, opts] = mutate.mock.calls[0] as [
      RegisterAgentRequest,
      { onSuccess?: () => void; onError?: (e: Error) => void },
    ];
    expect(body).toEqual({ url: "https://new.example.com" });

    // Simulate the mutation succeeding
    opts.onSuccess?.();
    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ message: "Agent registered" }),
      );
    });
  });

  it("surfaces a 4xx error inline below the form", async () => {
    mockAgentsQuery({ data: [] });
    const mutate = vi.fn();
    mockRegisterMutation(mutate);
    mockToast();
    render(<AgentsPage />);

    const urlInput = screen.getByLabelText(/agent url/i);
    fireEvent.change(urlInput, {
      target: { value: "https://bad.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /register agent/i }));

    const [, opts] = mutate.mock.calls[0] as [
      RegisterAgentRequest,
      { onError?: (e: Error) => void },
    ];
    opts.onError?.(new Error("API 400: invalid metadata"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("invalid metadata");
    });
  });

  it("toggles the auth token visibility", () => {
    mockAgentsQuery({ data: [] });
    mockRegisterMutation(vi.fn());
    mockToast();
    render(<AgentsPage />);

    const tokenInput = document.getElementById(
      "agent-auth-token",
    ) as HTMLInputElement;
    expect(tokenInput.type).toBe("password");

    const toggle = screen.getByRole("button", { name: /show auth token/i });
    fireEvent.click(toggle);
    expect(tokenInput.type).toBe("text");

    fireEvent.click(screen.getByRole("button", { name: /hide auth token/i }));
    expect(tokenInput.type).toBe("password");
  });

  it("adds and removes metadata rows; only trims non-empty keys on submit", async () => {
    mockAgentsQuery({ data: [] });
    const mutate = vi.fn();
    mockRegisterMutation(mutate);
    mockToast();
    render(<AgentsPage />);

    fireEvent.click(screen.getByRole("button", { name: /add pair/i }));

    const keyInputs = screen.getAllByLabelText(/^metadata key /i);
    const valueInputs = screen.getAllByLabelText(/^metadata value /i);
    expect(keyInputs).toHaveLength(1);
    expect(valueInputs).toHaveLength(1);

    fireEvent.change(keyInputs[0], { target: { value: "region" } });
    fireEvent.change(valueInputs[0], { target: { value: "us-east-1" } });

    // Add a second pair and leave the key blank (should be filtered)
    fireEvent.click(screen.getByRole("button", { name: /add pair/i }));
    const valueInputs2 = screen.getAllByLabelText(/^metadata value /i);
    fireEvent.change(valueInputs2[1], { target: { value: "ignored" } });

    // Remove the second pair
    const removeButtons = screen.getAllByRole("button", { name: /remove metadata pair/i });
    fireEvent.click(removeButtons[1]);

    // Fill url + submit
    fireEvent.change(screen.getByLabelText(/agent url/i), {
      target: { value: "https://x.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /register agent/i }));

    const [body] = mutate.mock.calls[0] as [RegisterAgentRequest];
    expect(body.metadata).toEqual({ region: "us-east-1" });
  });

  // ----------------------------------------------------------------
  // Accessibility
  // ----------------------------------------------------------------
  it("renders the aria-live region for status announcements", () => {
    mockAgentsQuery({ data: sampleAgents });
    mockRegisterMutation(vi.fn());
    mockToast();
    render(<AgentsPage />);
    const liveRegion = screen.getByTestId("agents-aria-live");
    expect(liveRegion).toHaveAttribute("aria-live", "polite");
    expect(liveRegion).toHaveAttribute("role", "status");
  });

  it("renders the page title and subtitle", () => {
    mockAgentsQuery({ data: sampleAgents });
    mockRegisterMutation(vi.fn());
    mockToast();
    render(<AgentsPage />);
    expect(
      screen.getByRole("heading", { name: "Agents", level: 1 }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/environment agents celeste can reach/i),
    ).toBeInTheDocument();
  });
});
