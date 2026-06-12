/**
 * Keyboard shortcut contracts for CMC.
 *
 * Shortcuts are described once here and rendered by
 * `KeyboardShortcutsHelp` and dispatched by `useKeyboardShortcuts`. The
 * `combo` field is a normalized token string (e.g. "Ctrl+Shift+D") that the
 * hook understands; `comboToReadable` renders it for display.
 */

export type ShortcutContext = "global" | "workflow" | "workflows-list";

export interface Shortcut {
  /** Stable identifier; must be unique within SHORTCUTS. */
  id: string;
  /** Human-readable description shown in the help dialog. */
  description: string;
  /**
   * Normalized key combo using `+` as a separator. Examples:
   *   "Ctrl+Shift+D" — modifier-driven
   *   "j"            — single key, no modifier
   * Recognized modifier tokens: Ctrl, Shift, Alt, Meta. The dispatcher in
   * `useKeyboardShortcuts` treats Ctrl and Meta (Cmd) as equivalent.
   */
  combo: string;
  /** Where the shortcut is meaningful. */
  context: ShortcutContext;
}

export const SHORTCUTS: readonly Shortcut[] = [
  // Global navigation
  {
    id: "go-dashboard",
    description: "Go to Dashboard",
    combo: "Ctrl+Shift+D",
    context: "global",
  },
  {
    id: "go-workflows",
    description: "Go to Workflows",
    combo: "Ctrl+Shift+W",
    context: "global",
  },
  {
    id: "go-observatory",
    description: "Go to Observatory",
    combo: "Ctrl+Shift+O",
    context: "global",
  },
  {
    id: "go-agents",
    description: "Go to Agents",
    combo: "Ctrl+Shift+A",
    context: "global",
  },
  {
    id: "focus-search",
    description: "Focus global search",
    combo: "Ctrl+K",
    context: "global",
  },
  {
    id: "show-help",
    description: "Show keyboard shortcuts",
    combo: "Ctrl+/",
    context: "global",
  },
  {
    id: "close",
    description: "Close inspector / panel / modal",
    combo: "Esc",
    context: "global",
  },
  // Workflow page
  {
    id: "copy-workflow-id",
    description: "Copy workflow ID",
    combo: "Ctrl+Shift+C",
    context: "workflow",
  },
  {
    id: "pause-resume",
    description: "Pause or resume workflow",
    combo: "Ctrl+Shift+P",
    context: "workflow",
  },
  // Workflows list
  {
    id: "next-row",
    description: "Next workflow in list",
    combo: "j",
    context: "workflows-list",
  },
  {
    id: "prev-row",
    description: "Previous workflow in list",
    combo: "k",
    context: "workflows-list",
  },
  {
    id: "open-workflow",
    description: "Open selected workflow",
    combo: "Enter",
    context: "workflows-list",
  },
];

export const SHORTCUTS_BY_ID: Readonly<Record<string, Shortcut>> = Object.freeze(
  Object.fromEntries(SHORTCUTS.map((s) => [s.id, s]))
);

/**
 * Detect whether the current platform is macOS. Safe in jsdom / SSR — falls
 * back to `false` when `navigator` is undefined.
 */
export function isMac(): boolean {
  if (typeof navigator === "undefined") return false;
  // `platform` is the historical, simple check. The newer `userAgentData`
  // is not yet widely available; not worth the complexity here.
  const platform = navigator.platform ?? "";
  return /Mac|iPhone|iPad|iPod/i.test(platform);
}

/**
 * Convert a normalized combo string to a human-readable form.
 *
 * - On Mac, "Ctrl" becomes the Cmd glyph (⌘).
 * - Modifiers appear in the order Shift, Alt, Meta/Ctrl, then the key.
 *
 * @example
 * comboToReadable("Ctrl+Shift+D")       // "Shift+⌘+D" on Mac, "Ctrl+Shift+D" elsewhere
 * comboToReadable("Ctrl+Shift+D", true) // "Shift+⌘+D"
 */
export function comboToReadable(combo: string, mac: boolean = isMac()): string {
  const tokens = combo.split("+").map((t) => t.trim()).filter(Boolean);
  if (tokens.length === 0) return "";

  const hasShift = tokens.includes("Shift");
  const hasAlt = tokens.includes("Alt");
  const hasCtrl = tokens.includes("Ctrl");
  const hasMeta = tokens.includes("Meta");

  const key = tokens.find(
    (t) => t !== "Shift" && t !== "Alt" && t !== "Ctrl" && t !== "Meta"
  );

  const parts: string[] = [];
  if (hasShift) parts.push("Shift");
  if (hasAlt) parts.push(mac ? "Option" : "Alt");
  if (hasCtrl) parts.push(mac ? "⌘" : "Ctrl");
  if (hasMeta) parts.push(mac ? "⌘" : "Meta");
  if (key) parts.push(displayKey(key));

  return parts.join("+");
}

function displayKey(key: string): string {
  if (key === "Esc") return "Esc";
  if (key === "Enter") return "Enter";
  if (key === "?") return "?";
  if (key === "/") return "/";
  if (key.length === 1) return key.toUpperCase();
  return key;
}
