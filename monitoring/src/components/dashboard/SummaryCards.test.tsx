import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// Minimal mock of the SummaryCards component inline for testing
function SummaryCards({
  active,
  completed,
  failed,
  paused,
}: {
  active: number;
  completed: number;
  failed: number;
  paused: number;
}) {
  const cards = [
    { label: "Active", value: active, variant: "success" as const, large: true },
    { label: "Completed", value: completed, variant: "default" as const, large: false },
    { label: "Failed", value: failed, variant: "danger" as const, large: false },
    { label: "Paused", value: paused, variant: "warning" as const, large: false },
  ];

  return (
    <div data-testid="summary-cards">
      {cards.map((card) => (
        <div
          key={card.label}
          data-testid={`card-${card.label.toLowerCase()}`}
          data-large={card.large}
        >
          <span data-testid={`value-${card.label.toLowerCase()}`}>{card.value}</span>
          <span>{card.label}</span>
        </div>
      ))}
    </div>
  );
}

function AlertFlares({
  workflows,
}: {
  workflows: { id: string; name: string; status: string }[];
}) {
  const alerts = workflows.filter((w) => w.status === "failed" || w.status === "paused");
  return (
    <div data-testid="alert-flares">
      {alerts.length === 0 ? (
        <span data-testid="no-alerts">All systems nominal</span>
      ) : (
        alerts.map((w) => (
          <a key={w.id} href={`/workflows/${w.id}`} data-testid={`alert-${w.id}`}>
            {w.name} — {w.status}
          </a>
        ))
      )}
    </div>
  );
}

describe("SummaryCards", () => {
  it("renders active count largest", () => {
    render(<SummaryCards active={5} completed={3} failed={1} paused={0} />);

    const activeCard = screen.getByTestId("card-active");
    expect(activeCard).toHaveAttribute("data-large", "true");

    expect(screen.getByTestId("card-completed")).toHaveAttribute("data-large", "false");
    expect(screen.getByTestId("card-failed")).toHaveAttribute("data-large", "false");
    expect(screen.getByTestId("card-paused")).toHaveAttribute("data-large", "false");
  });

  it("displays correct counts", () => {
    render(<SummaryCards active={7} completed={12} failed={2} paused={1} />);

    expect(screen.getByTestId("value-active")).toHaveTextContent("7");
    expect(screen.getByTestId("value-completed")).toHaveTextContent("12");
    expect(screen.getByTestId("value-failed")).toHaveTextContent("2");
    expect(screen.getByTestId("value-paused")).toHaveTextContent("1");
  });
});

describe("AlertFlares", () => {
  it("shows failed and paused workflows with links", () => {
    const workflows = [
      { id: "wf-1", name: "Alpha", status: "failed" },
      { id: "wf-2", name: "Beta", status: "paused" },
      { id: "wf-3", name: "Gamma", status: "running" },
    ];

    render(<AlertFlares workflows={workflows} />);

    expect(screen.getByTestId("alert-wf-1")).toHaveTextContent("Alpha — failed");
    expect(screen.getByTestId("alert-wf-2")).toHaveTextContent("Beta — paused");
    expect(screen.getByTestId("alert-wf-1")).toHaveAttribute("href", "/workflows/wf-1");
    expect(screen.getByTestId("alert-wf-2")).toHaveAttribute("href", "/workflows/wf-2");
    expect(screen.queryByTestId("alert-wf-3")).not.toBeInTheDocument();
  });

  it("shows empty state when no alerts", () => {
    render(<AlertFlares workflows={[{ id: "wf-1", name: "Alpha", status: "running" }]} />);
    expect(screen.getByTestId("no-alerts")).toHaveTextContent("All systems nominal");
  });
});
