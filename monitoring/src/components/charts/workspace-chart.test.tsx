import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { WorkspaceChart, type ConcurrencyPoint } from "./workspace-chart";

describe("WorkspaceChart", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it("shows empty state when no data", () => {
    render(<WorkspaceChart data={[]} />);

    expect(screen.getByText("No workspace concurrency data")).toBeInTheDocument();
    expect(
      screen.getByText(/Workspaces will appear here once the workflow begins spawning/)
    ).toBeInTheDocument();
  });

  it("renders area chart with concurrency data", () => {
    const data: ConcurrencyPoint[] = [
      { timestamp: "2024-01-01T00:00:00Z", concurrency: 1 },
      { timestamp: "2024-01-01T00:01:00Z", concurrency: 2 },
      { timestamp: "2024-01-01T00:02:00Z", concurrency: 1 },
    ];

    const { container } = render(<WorkspaceChart data={data} peakConcurrency={2} />);

    expect(screen.getByText("Running workspaces over time")).toBeInTheDocument();
    expect(container.querySelector("figure")).toHaveAttribute("aria-label", "Workspace concurrency over time");
  });

  it("renders without peak line when peakConcurrency is null", () => {
    const data: ConcurrencyPoint[] = [
      { timestamp: "2024-01-01T00:00:00Z", concurrency: 1 },
    ];

    const { container } = render(<WorkspaceChart data={data} peakConcurrency={null} />);

    expect(screen.getByText("Running workspaces over time")).toBeInTheDocument();
    expect(container.querySelector("figure")).toBeInTheDocument();
  });
});
