import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EmptyState } from "./empty-state";

// ------------------------------------------------------------------
// Tests — Lane 2: shared empty-state surface
// ------------------------------------------------------------------

describe("EmptyState", () => {
  it("renders the title and description", () => {
    render(
      <EmptyState
        title="Nothing here yet"
        description="Try adjusting your filters."
      />
    );
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
    expect(screen.getByText("Try adjusting your filters.")).toBeInTheDocument();
  });

  it("exposes the surface with role=status for assistive tech", () => {
    render(<EmptyState title="Hello" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the optional icon when provided", () => {
    render(
      <EmptyState
        title="Empty"
        icon={<svg data-testid="my-icon" />}
      />
    );
    expect(screen.getByTestId("my-icon")).toBeInTheDocument();
  });

  it("does not render an icon container when icon is omitted", () => {
    const { container } = render(<EmptyState title="Empty" />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("fires onClick when an action button is clicked", () => {
    const onClick = vi.fn();
    render(
      <EmptyState
        title="Empty"
        action={{ label: "Refresh", onClick }}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders the action as a link when an href is provided", () => {
    render(
      <EmptyState
        title="Empty"
        action={{ label: "Go to dashboard", href: "/" }}
      />
    );
    const link = screen.getByRole("link", { name: "Go to dashboard" });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/");
  });

  it("hides the description paragraph when description is not provided", () => {
    render(<EmptyState title="Empty" />);
    // The status container is the only top-level element; description
    // paragraph is absent.
    expect(screen.queryByText("Try adjusting your filters.")).toBeNull();
  });

  it("applies compact padding when compact is set", () => {
    const { container } = render(
      <EmptyState title="Empty" compact />
    );
    const root = container.querySelector('[role="status"]')!;
    expect(root.className).toMatch(/py-8/);
  });
});
