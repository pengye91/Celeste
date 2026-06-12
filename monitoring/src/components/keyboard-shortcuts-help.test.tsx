import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { KeyboardShortcutsHelp } from "@/components/keyboard-shortcuts-help";
import { SHORTCUTS } from "@/lib/shortcuts";

describe("KeyboardShortcutsHelp", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the dialog title when open", () => {
    render(<KeyboardShortcutsHelp open={true} onClose={() => {}} />);
    expect(screen.getByText("Keyboard Shortcuts")).toBeInTheDocument();
  });

  it("renders every shortcut from SHORTCUTS", () => {
    render(<KeyboardShortcutsHelp open={true} onClose={() => {}} />);
    for (const s of SHORTCUTS) {
      expect(screen.getByTestId(`kshortcut-combo-${s.id}`)).toBeInTheDocument();
      expect(screen.getByTestId(`kshortcut-combo-${s.id}`).textContent).toBeTruthy();
    }
  });

  it("groups shortcuts by context", () => {
    render(<KeyboardShortcutsHelp open={true} onClose={() => {}} />);
    expect(screen.getByTestId("kshortcut-group-global")).toBeInTheDocument();
    expect(screen.getByTestId("kshortcut-group-workflow")).toBeInTheDocument();
    expect(screen.getByTestId("kshortcut-group-workflows-list")).toBeInTheDocument();
  });

  it("calls onClose when Esc is pressed (Radix handles close)", () => {
    const onClose = vi.fn();
    render(<KeyboardShortcutsHelp open={true} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("renders no dialog content when closed", () => {
    const { container } = render(
      <KeyboardShortcutsHelp open={false} onClose={() => {}} />
    );
    // The Portal is not mounted when open is false; no title should be present.
    expect(container.querySelector("[data-testid='kshortcut-dialog']")).toBeNull();
  });
});
