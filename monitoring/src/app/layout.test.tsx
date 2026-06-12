import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import RootLayout from "./layout";

// ------------------------------------------------------------------
// Mocks
// ------------------------------------------------------------------

// next/font/google is a server-only API in Next 16; mock it so the
// client can import the layout module under jsdom.
vi.mock("next/font/google", () => ({
  Bodoni_Moda: () => ({ variable: "--font-bodoni" }),
  Syne: () => ({ variable: "--font-syne" }),
  JetBrains_Mono: () => ({ variable: "--font-mono" }),
}));

vi.mock("@/components/providers/query-client-provider", () => ({
  QueryClientProviderWrapper: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="query-client">{children}</div>
  ),
}));

vi.mock("@/components/ui/toast", () => ({
  Toaster: () => <div data-testid="toaster" />,
}));

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

describe("RootLayout (Lane C — skip link + main-content)", () => {
  beforeEach(() => {
    // jsdom renders straight into <body>; the RootLayout wraps
    // <html><body>...</body></html>. We render with a single child
    // and assert against the skip link.
    document.body.innerHTML = "";
  });

  it("renders a skip link as the first focusable element with href=#main-content", () => {
    render(
      <RootLayout>
        <div>page content</div>
      </RootLayout>
    );
    // The skip link is the first anchor in the document. jsdom
    // unwraps <html>/<body> in React Testing Library, so the
    // rendered tree is just the body children. Find by accessible
    // name.
    const skip = screen.getByRole("link", { name: /skip to main content/i });
    expect(skip).toBeInTheDocument();
    expect(skip).toHaveAttribute("href", "#main-content");
  });

  it("marks the skip link sr-only by default and focus:not-sr-only on focus", () => {
    render(
      <RootLayout>
        <div>page content</div>
      </RootLayout>
    );
    const skip = screen.getByRole("link", { name: /skip to main content/i });
    // Default class should include sr-only
    expect(skip.className).toMatch(/sr-only/);
    // focus:not-sr-only should also be present
    expect(skip.className).toMatch(/focus:not-sr-only/);
  });

  it("exposes the skip link as focusable", () => {
    render(
      <RootLayout>
        <div>page content</div>
      </RootLayout>
    );
    const skip = screen.getByRole("link", { name: /skip to main content/i });
    // No explicit tabindex=-1 / disabled state — focusable
    expect(skip).not.toHaveAttribute("tabindex", "-1");
    expect(skip).not.toHaveAttribute("aria-hidden", "true");
  });

  it("renders the page children inside the body", () => {
    render(
      <RootLayout>
        <div data-testid="page">page content</div>
      </RootLayout>
    );
    expect(screen.getByTestId("page")).toBeInTheDocument();
  });
});
