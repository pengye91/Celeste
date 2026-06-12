import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  ConstellationView,
  type ConstellationNode,
} from "./constellation-view";

const sampleNodes: ConstellationNode[] = [
  { name: "root-a", status: "completed", dependencies: [] },
  { name: "root-b", status: "completed", dependencies: [] },
  { name: "child-1", status: "running", dependencies: ["root-a"], task_type: "tool" },
  { name: "child-2", status: "pending", dependencies: ["root-a", "root-b"], task_type: "llm" },
  { name: "grandchild", status: "failed", dependencies: ["child-1"], task_type: "tool" },
];

describe("ConstellationView", () => {
  beforeEach(() => {
    // Default to desktop viewport
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 1200,
    });
    window.dispatchEvent(new Event("resize"));
  });

  it("renders deterministic layout: same input produces same SVG positions", () => {
    const { container: c1 } = render(
      <ConstellationView nodes={sampleNodes} />
    );
    const { container: c2 } = render(
      <ConstellationView nodes={sampleNodes} />
    );

    const getPositions = (container: HTMLElement) => {
      const gs = container.querySelectorAll("g[role='button']");
      return Array.from(gs).map((g) => g.getAttribute("transform"));
    };

    const pos1 = getPositions(c1);
    const pos2 = getPositions(c2);

    expect(pos1).toHaveLength(5);
    expect(pos2).toHaveLength(5);
    expect(pos1).toEqual(pos2);
  });

  it("running node pulses (has animation class or pulse indicator)", () => {
    const { container } = render(<ConstellationView nodes={sampleNodes} />);

    // The running node is child-1
    const circles = container.querySelectorAll("circle");
    let foundPulse = false;
    circles.forEach((circle) => {
      const classList = circle.getAttribute("class") ?? "";
      if (classList.includes("animate-pulse-glow")) {
        foundPulse = true;
      }
    });
    expect(foundPulse).toBe(true);
  });

  it("mobile fallback renders a list when viewport is narrow", () => {
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 500,
    });
    window.dispatchEvent(new Event("resize"));

    render(<ConstellationView nodes={sampleNodes} />);

    // Should not show SVG
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    // Should show list items
    expect(screen.getByText("root-a")).toBeInTheDocument();
    expect(screen.getByText("root-b")).toBeInTheDocument();
    expect(screen.getByText("child-1")).toBeInTheDocument();
  });

  it("node click calls onNodeSelect with the full node", () => {
    const onSelect = vi.fn();

    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 500,
    });
    window.dispatchEvent(new Event("resize"));

    render(<ConstellationView nodes={sampleNodes} onNodeSelect={onSelect} />);

    const child1Btn = screen.getByRole("button", { name: /child-1/ });
    fireEvent.click(child1Btn);

    expect(onSelect).toHaveBeenCalledTimes(1);
    const selected = onSelect.mock.calls[0][0] as ConstellationNode;
    expect(selected.name).toBe("child-1");
    expect(selected.status).toBe("running");
    expect(selected.task_type).toBe("tool");
  });

  it("renders empty state when no nodes provided", () => {
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 500,
    });
    window.dispatchEvent(new Event("resize"));

    render(<ConstellationView nodes={[]} />);
    expect(screen.getByText("No nodes in this workflow")).toBeInTheDocument();
  });

  it("respects reducedMotion and does not animate pulse on running nodes", () => {
    const { container } = render(
      <ConstellationView nodes={sampleNodes} reducedMotion />
    );

    const circles = container.querySelectorAll("circle");
    let foundPulse = false;
    circles.forEach((circle) => {
      const classList = circle.getAttribute("class") ?? "";
      if (classList.includes("animate-pulse-glow")) {
        foundPulse = true;
      }
    });
    expect(foundPulse).toBe(false);
  });

  it("active node is pinned to top in mobile list", () => {
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 500,
    });
    window.dispatchEvent(new Event("resize"));

    render(
      <ConstellationView nodes={sampleNodes} activeNodeName="grandchild" />
    );

    const buttons = screen.getAllByRole("button");
    // First button should be grandchild (failed node, active)
    expect(buttons[0].textContent).toContain("grandchild");
  });

  it("aria-live region announces selected node", () => {
    const onSelect = vi.fn();
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 500,
    });
    window.dispatchEvent(new Event("resize"));

    const { rerender } = render(
      <ConstellationView
        nodes={sampleNodes}
        onNodeSelect={onSelect}
        selectedNode={null}
      />
    );

    const liveRegion = screen.getByText("No node selected");
    expect(liveRegion).toBeInTheDocument();

    rerender(
      <ConstellationView
        nodes={sampleNodes}
        onNodeSelect={onSelect}
        selectedNode={sampleNodes[2]}
      />
    );

    expect(screen.getByText(/Selected node child-1, status running/)).toBeInTheDocument();
  });

  it("SVG view has reset view button", () => {
    render(<ConstellationView nodes={sampleNodes} />);
    expect(screen.getByRole("button", { name: /Reset view/ })).toBeInTheDocument();
  });

  it("renders edge particles for running-source dependencies", () => {
    const { container } = render(<ConstellationView nodes={sampleNodes} />);
    const animateMotions = container.querySelectorAll("animateMotion");
    // child-1 depends on root-a; root-a is completed so no particle
    // Actually root-a is completed, not running. Let's check: child-1 is running, so edges FROM child-1 should have particles.
    // grandchild depends on child-1 (running), so there should be a particle on that edge.
    expect(animateMotions.length).toBeGreaterThan(0);
  });

  it("does not render edge particles when reducedMotion is true", () => {
    const { container } = render(
      <ConstellationView nodes={sampleNodes} reducedMotion />
    );
    const animateMotions = container.querySelectorAll("animateMotion");
    expect(animateMotions.length).toBe(0);
  });
});
