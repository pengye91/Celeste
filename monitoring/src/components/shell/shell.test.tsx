import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { Shell } from "@/components/shell/shell";

// ------------------------------------------------------------------
// Mocks
// ------------------------------------------------------------------

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/",
}));

vi.mock("@/components/shell/top-bar", () => ({
  TopBar: ({
    onOpenHelp,
  }: {
    onOpenHelp?: () => void;
  }) => (
    <div data-testid="top-bar">
      {onOpenHelp && (
        <button data-testid="open-help" onClick={onOpenHelp} type="button">
          Open help
        </button>
      )}
    </div>
  ),
}));

vi.mock("@/components/shell/side-rail", () => ({
  SideRail: () => <nav data-testid="side-rail">Side rail</nav>,
}));

vi.mock("@/components/shell/main-stage", () => ({
  MainStage: ({ children }: { children: React.ReactNode }) => (
    <main data-testid="main-stage">{children}</main>
  ),
}));

vi.mock("@/components/keyboard-shortcuts-help", () => ({
  KeyboardShortcutsHelp: ({
    open,
    onClose,
  }: {
    open: boolean;
    onClose: () => void;
  }) =>
    open ? (
      <div data-testid="kshortcut-dialog-mount">
        <button data-testid="kshortcut-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

// Track the handlers passed to useKeyboardShortcuts so we can
// invoke them from the tests.
let lastHandlers: Record<string, (e: KeyboardEvent) => void> = {};

vi.mock("@/hooks/useKeyboardShortcuts", () => ({
  useKeyboardShortcuts: (handlers: Record<string, (e: KeyboardEvent) => void>) => {
    lastHandlers = handlers;
  },
}));

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

describe("Shell", () => {
  beforeEach(() => {
    pushMock.mockClear();
    lastHandlers = {};
  });

  it("renders the nav (side rail, top bar, main stage)", () => {
    render(
      <Shell>
        <div>child</div>
      </Shell>
    );
    expect(screen.getByTestId("side-rail")).toBeInTheDocument();
    expect(screen.getByTestId("top-bar")).toBeInTheDocument();
    expect(screen.getByTestId("main-stage")).toBeInTheDocument();
    expect(screen.getByText("child")).toBeInTheDocument();
  });

  it("registers the global navigation shortcuts", () => {
    render(<Shell>child</Shell>);
    expect(typeof lastHandlers["Ctrl+Shift+D"]).toBe("function");
    expect(typeof lastHandlers["Ctrl+Shift+W"]).toBe("function");
    expect(typeof lastHandlers["Ctrl+Shift+O"]).toBe("function");
    expect(typeof lastHandlers["Ctrl+Shift+A"]).toBe("function");
    expect(typeof lastHandlers["Ctrl+/"]).toBe("function");
    expect(typeof lastHandlers.Esc).toBe("function");
  });

  it("Ctrl+Shift+D navigates to /", () => {
    render(<Shell>child</Shell>);
    lastHandlers["Ctrl+Shift+D"](new KeyboardEvent("keydown"));
    expect(pushMock).toHaveBeenCalledWith("/");
  });

  it("Ctrl+Shift+W navigates to /workflows", () => {
    render(<Shell>child</Shell>);
    lastHandlers["Ctrl+Shift+W"](new KeyboardEvent("keydown"));
    expect(pushMock).toHaveBeenCalledWith("/workflows");
  });

  it("Ctrl+Shift+O navigates to /observatory", () => {
    render(<Shell>child</Shell>);
    lastHandlers["Ctrl+Shift+O"](new KeyboardEvent("keydown"));
    expect(pushMock).toHaveBeenCalledWith("/observatory");
  });

  it("Ctrl+Shift+A navigates to /agents", () => {
    render(<Shell>child</Shell>);
    lastHandlers["Ctrl+Shift+A"](new KeyboardEvent("keydown"));
    expect(pushMock).toHaveBeenCalledWith("/agents");
  });

  it("Ctrl+K focuses an element with data-search-input", () => {
    const input = document.createElement("input");
    input.setAttribute("data-search-input", "");
    const focusSpy = vi.spyOn(input, "focus");
    document.body.appendChild(input);
    render(<Shell>child</Shell>);
    lastHandlers["Ctrl+K"](new KeyboardEvent("keydown"));
    expect(focusSpy).toHaveBeenCalled();
    document.body.removeChild(input);
  });

  it("Ctrl+/ opens the keyboard shortcuts dialog", () => {
    render(<Shell>child</Shell>);
    expect(screen.queryByTestId("kshortcut-dialog-mount")).toBeNull();
    act(() => {
      lastHandlers["Ctrl+/"](new KeyboardEvent("keydown"));
    });
    expect(screen.getByTestId("kshortcut-dialog-mount")).toBeInTheDocument();
  });

  it("Esc closes the keyboard shortcuts dialog", () => {
    render(<Shell>child</Shell>);
    // Open first via the top-bar button
    fireEvent.click(screen.getByTestId("open-help"));
    expect(screen.getByTestId("kshortcut-dialog-mount")).toBeInTheDocument();
    act(() => {
      lastHandlers.Esc(new KeyboardEvent("keydown"));
    });
    expect(screen.queryByTestId("kshortcut-dialog-mount")).toBeNull();
  });

  it("top-bar open-help button opens the dialog", () => {
    render(<Shell>child</Shell>);
    fireEvent.click(screen.getByTestId("open-help"));
    expect(screen.getByTestId("kshortcut-dialog-mount")).toBeInTheDocument();
  });
});
