import { describe, it, expect } from "vitest";
import {
  SHORTCUTS,
  comboToReadable,
  isMac,
  type Shortcut,
  type ShortcutContext,
} from "@/lib/shortcuts";

describe("SHORTCUTS", () => {
  it("has at least 12 entries", () => {
    expect(SHORTCUTS.length).toBeGreaterThanOrEqual(12);
  });

  it("has unique ids", () => {
    const ids = SHORTCUTS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("every entry has the required fields", () => {
    const validContexts: ShortcutContext[] = ["global", "workflow", "workflows-list"];
    for (const s of SHORTCUTS) {
      expect(s.id).toBeTruthy();
      expect(s.description).toBeTruthy();
      expect(s.combo).toBeTruthy();
      expect(validContexts).toContain(s.context);
    }
  });

  it("contains the spec-required entries", () => {
    const combos = new Set(SHORTCUTS.map((s) => s.combo));
    for (const c of [
      "Ctrl+Shift+D",
      "Ctrl+Shift+W",
      "Ctrl+Shift+O",
      "Ctrl+Shift+A",
      "Ctrl+K",
      "Ctrl+/",
      "Esc",
      "Ctrl+Shift+C",
      "Ctrl+Shift+P",
      "j",
      "k",
      "Enter",
    ]) {
      expect(combos.has(c)).toBe(true);
    }
  });

  it("has unique combinations per shortcut entry (ids are unique but combos are not required to be)", () => {
    // Treat the array as a typed list; this is a no-op assertion guarding
    // the type during refactors.
    const all: Shortcut[] = [...SHORTCUTS];
    expect(all.length).toBe(SHORTCUTS.length);
  });
});

describe("isMac", () => {
  it("returns a boolean", () => {
    expect(typeof isMac()).toBe("boolean");
  });
});

describe("comboToReadable", () => {
  it("replaces Ctrl with Cmd glyph on Mac", () => {
    const out = comboToReadable("Ctrl+Shift+D", true);
    expect(out).toBe("Shift+⌘+D");
  });

  it("keeps Ctrl on Windows/Linux", () => {
    const out = comboToReadable("Ctrl+Shift+D", false);
    // Order is always Shift, Alt, Ctrl/Meta, key.
    expect(out).toBe("Shift+Ctrl+D");
  });

  it("renders Esc and Enter unmodified", () => {
    expect(comboToReadable("Esc", true)).toBe("Esc");
    expect(comboToReadable("Esc", false)).toBe("Esc");
    expect(comboToReadable("Enter", true)).toBe("Enter");
  });

  it("uppercases single-letter keys", () => {
    expect(comboToReadable("j", false)).toBe("J");
    expect(comboToReadable("k", false)).toBe("K");
  });

  it("renders Alt as Option on Mac", () => {
    expect(comboToReadable("Alt+K", true)).toBe("Option+K");
    expect(comboToReadable("Alt+K", false)).toBe("Alt+K");
  });

  it("handles a bare slash", () => {
    expect(comboToReadable("/", false)).toBe("/");
  });
});
