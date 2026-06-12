import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import GlobalError from "./error";

// ------------------------------------------------------------------
// Mocks
// ------------------------------------------------------------------

vi.mock("@/components/shell/shell", () => ({
  Shell: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="shell">{children}</div>
  ),
}));

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

// ------------------------------------------------------------------
// Tests — Lane 2: top-level error boundary
// ------------------------------------------------------------------

describe("GlobalError (app/error.tsx)", () => {
  beforeEach(() => {
    // Silence the console.error from useEffect — we deliberately log
    // the error to the console for visibility.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("renders the design-system error orb with the spec label", () => {
    render(
      <GlobalError
        error={new Error("boom")}
        unstable_retry={() => undefined}
      />
    );
    const orb = screen.getByRole("img", { name: "Something went wrong" });
    expect(orb).toBeInTheDocument();
  });

  it("renders a Try again button that calls unstable_retry", () => {
    const unstable_retry = vi.fn();
    render(
      <GlobalError error={new Error("boom")} unstable_retry={unstable_retry} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(unstable_retry).toHaveBeenCalledTimes(1);
  });

  it("renders a back link to the dashboard", () => {
    render(
      <GlobalError
        error={new Error("boom")}
        unstable_retry={() => undefined}
      />
    );
    const link = screen.getByRole("link", { name: /back to dashboard/i });
    expect(link).toHaveAttribute("href", "/");
  });

  it("surfaces the error digest as a reference when provided", () => {
    const error = new Error("boom") as Error & { digest?: string };
    error.digest = "abc123";
    render(
      <GlobalError error={error} unstable_retry={() => undefined} />
    );
    expect(screen.getByText(/ref: abc123/)).toBeInTheDocument();
  });

  it("omits the digest reference when not provided", () => {
    render(
      <GlobalError
        error={new Error("boom")}
        unstable_retry={() => undefined}
      />
    );
    expect(screen.queryByText(/ref:/)).toBeNull();
  });
});
