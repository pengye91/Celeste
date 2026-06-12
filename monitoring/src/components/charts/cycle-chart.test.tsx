import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { CycleChart, type CycleData } from "./cycle-chart";

describe("CycleChart", () => {
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
    render(<CycleChart data={[]} />);

    expect(screen.getByText("No OPA cycles recorded")).toBeInTheDocument();
    expect(
      screen.getByText(/Cycles will appear here once the OPA loop begins/)
    ).toBeInTheDocument();
  });

  it("renders area chart when hasTokenData is true and tokens exist", () => {
    const data: CycleData[] = [
      { cycleNumber: 1, tokenCount: 100, durationMs: 500, nodeCount: 3, timestamp: "2024-01-01T00:00:00Z" },
      { cycleNumber: 2, tokenCount: 250, durationMs: 600, nodeCount: 4, timestamp: "2024-01-01T00:01:00Z" },
    ];

    const { container } = render(<CycleChart data={data} hasTokenData budget={500} />);

    expect(screen.getByText("Tokens per cycle")).toBeInTheDocument();
    expect(container.querySelector("figure")).toHaveAttribute("aria-label", "Accumulated tokens per OPA cycle");
  });

  it("renders fallback bar/line chart when hasTokenData is false", () => {
    const data: CycleData[] = [
      { cycleNumber: 1, durationMs: 500, nodeCount: 3, timestamp: "2024-01-01T00:00:00Z" },
      { cycleNumber: 2, durationMs: 600, nodeCount: 4, timestamp: "2024-01-01T00:01:00Z" },
    ];

    const { container } = render(<CycleChart data={data} />);

    expect(screen.getByText("Cycle metrics")).toBeInTheDocument();
    expect(container.querySelector("figure")).toHaveAttribute("aria-label", "Cycle duration and node count per OPA cycle");
  });

  it("renders fallback bar/line chart when hasTokenData is true but no tokens present", () => {
    const data: CycleData[] = [
      { cycleNumber: 1, durationMs: 500, nodeCount: 3, timestamp: "2024-01-01T00:00:00Z" },
      { cycleNumber: 2, durationMs: 600, nodeCount: 4, timestamp: "2024-01-01T00:01:00Z" },
    ];

    const { container } = render(<CycleChart data={data} hasTokenData />);

    expect(screen.getByText("Cycle metrics")).toBeInTheDocument();
    expect(container.querySelector("figure")).toHaveAttribute("aria-label", "Cycle duration and node count per OPA cycle");
  });
});
