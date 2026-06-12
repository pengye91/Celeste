import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";

function fireKey(target: EventTarget, init: KeyboardEventInit & { key: string }) {
  const event = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

describe("useKeyboardShortcuts", () => {
  it("fires a Ctrl+Shift+D handler", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts({ "Ctrl+Shift+D": handler }));
    fireKey(document, { key: "D", ctrlKey: true, shiftKey: true });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("fires a Meta+Shift+D handler when only Ctrl-key is registered (Mac equivalent)", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts({ "Ctrl+Shift+D": handler }));
    fireKey(document, { key: "D", metaKey: true, shiftKey: true });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not fire when focus is in an INPUT", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts({ "Ctrl+Shift+D": handler }));
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    fireKey(input, { key: "D", ctrlKey: true, shiftKey: true });
    document.body.removeChild(input);
    expect(handler).not.toHaveBeenCalled();
  });

  it("does not fire when focus is in a TEXTAREA", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts({ "Ctrl+Shift+D": handler }));
    const ta = document.createElement("textarea");
    document.body.appendChild(ta);
    ta.focus();
    fireKey(ta, { key: "D", ctrlKey: true, shiftKey: true });
    document.body.removeChild(ta);
    expect(handler).not.toHaveBeenCalled();
  });

  it("does not fire when focus is in a contenteditable", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts({ "Ctrl+Shift+D": handler }));
    const div = document.createElement("div");
    div.contentEditable = "true";
    document.body.appendChild(div);
    div.focus();
    fireKey(div, { key: "D", ctrlKey: true, shiftKey: true });
    document.body.removeChild(div);
    expect(handler).not.toHaveBeenCalled();
  });

  it("fires a single-key j handler", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts({ j: handler }));
    fireKey(document, { key: "j" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("fires a single-key Esc handler", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts({ Esc: handler }));
    fireKey(document, { key: "Escape" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("calls preventDefault on matched combos by default", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts({ "Ctrl+Shift+D": handler }));
    const event = fireKey(document, { key: "D", ctrlKey: true, shiftKey: true });
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not fire when disabled", () => {
    const handler = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts({ "Ctrl+Shift+D": handler }, { enabled: false })
    );
    fireKey(document, { key: "D", ctrlKey: true, shiftKey: true });
    expect(handler).not.toHaveBeenCalled();
  });

  it("does not fire on a Ctrl+letter when the registered combo is a bare key", () => {
    // Bare "j" should not match when the user pressed Ctrl+J.
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts({ j: handler }));
    fireKey(document, { key: "j", ctrlKey: true });
    expect(handler).not.toHaveBeenCalled();
  });
});
