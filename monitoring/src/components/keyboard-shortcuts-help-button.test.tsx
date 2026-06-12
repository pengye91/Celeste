import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { KeyboardShortcutsHelpButton } from "@/components/keyboard-shortcuts-help-button";

describe("KeyboardShortcutsHelpButton", () => {
  it("renders a button with the Show keyboard shortcuts label", () => {
    render(<KeyboardShortcutsHelpButton onClick={() => {}} />);
    const button = screen.getByTestId("kshortcut-help-button");
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-label", "Show keyboard shortcuts");
  });

  it("calls onClick when clicked", () => {
    const onClick = vi.fn();
    render(<KeyboardShortcutsHelpButton onClick={onClick} />);
    fireEvent.click(screen.getByTestId("kshortcut-help-button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("includes the keyboard shortcut hint in the title attribute", () => {
    render(<KeyboardShortcutsHelpButton onClick={() => {}} />);
    const button = screen.getByTestId("kshortcut-help-button");
    expect(button.getAttribute("title") ?? "").toMatch(/Ctrl\+\//);
  });
});
