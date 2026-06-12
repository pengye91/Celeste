"use client";

import { useEffect, useRef } from "react";

/**
 * Map of normalized key combo (e.g. "Ctrl+Shift+D", "j", "Enter") to the
 * handler to invoke when the combo is pressed.
 *
 * Combo grammar (same as `comboToReadable`):
 *   - Modifier tokens: Ctrl, Shift, Alt, Meta
 *   - Ctrl and Meta are treated as equivalent (Cmd on Mac)
 *   - Bare keys ("j", "k", "Enter", "Esc", "?") require no modifier
 *
 * Events are ignored when focus is inside an INPUT, TEXTAREA, SELECT, or
 * any element with `contenteditable="true"`. This is the standard
 * convention for app-level shortcuts that should not hijack text entry.
 */
export type ShortcutHandlers = Record<string, (event: KeyboardEvent) => void>;

export interface UseKeyboardShortcutsOptions {
  /** When false, the listener is not attached. Defaults to true. */
  enabled?: boolean;
  /**
   * Optional ref to a container element. When provided, keyboard events
   * that bubble up to it are filtered to the same ignore rules. By
   * default we listen on `document`.
   */
  scopeRef?: React.RefObject<HTMLElement | null>;
  /**
   * When true, calls `event.preventDefault()` on matched combos. Defaults
   * to true to avoid browser default actions (e.g. Ctrl+K opens search
   * bar in some browsers).
   */
  preventDefault?: boolean;
}

const TEXT_INPUT_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

function isInTextField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (TEXT_INPUT_TAGS.has(target.tagName)) {
    const type = (target as HTMLInputElement).type;
    // Allow shortcut on non-text inputs like checkboxes / buttons.
    const textInputTypes = new Set([
      "text",
      "search",
      "email",
      "url",
      "tel",
      "password",
      "number",
    ]);
    if (target.tagName === "TEXTAREA") return true;
    if (target.tagName === "SELECT") return false;
    if (target.tagName === "INPUT" && !textInputTypes.has(type)) return false;
    return true;
  }
  // `isContentEditable` is a getter that some test environments
  // (notably jsdom) don't reflect from the attribute — fall back to
  // checking the attribute and the `contentEditable` IDL property.
  if (target.isContentEditable) return true;
  const ce = target.contentEditable;
  if (ce === "true" || ce === "plaintext-only" || ce === "") {
    // The empty string is what the IDL property returns when the
    // attribute is set without a value, or when the property is set
    // with the legacy boolean form.
    return true;
  }
  const attr = target.getAttribute("contenteditable");
  if (attr === "true" || attr === "plaintext-only") return true;
  return false;
}

function comboForEvent(event: KeyboardEvent): string {
  const parts: string[] = [];
  if (event.shiftKey) parts.push("Shift");
  if (event.altKey) parts.push("Alt");
  if (event.ctrlKey || event.metaKey) parts.push("Ctrl");
  // Treat the actual key. Normalize to Title case for letter keys.
  const key = event.key;
  if (key === "Escape") parts.push("Esc");
  else if (key === " " || key === "Spacebar") parts.push("Space");
  else parts.push(key);
  return parts.join("+");
}

/**
 * Register a listener that maps keyboard combos to handlers.
 *
 * The hook normalizes combos to a canonical form: modifiers first
 * (Shift, Alt, Ctrl/Meta) followed by the key. Ctrl and Meta are
 * equivalent so `Ctrl+Shift+D` and `Meta+Shift+D` both fire the same
 * handler.
 */
export function useKeyboardShortcuts(
  handlers: ShortcutHandlers,
  opts: UseKeyboardShortcutsOptions = {}
): void {
  const { enabled = true, scopeRef, preventDefault = true } = opts;
  // Keep handlers in a ref so the listener effect can be set up once.
  // The ref is updated in an effect (not during render) to satisfy
  // react-hooks/refs.
  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  }, [handlers]);

  useEffect(() => {
    if (!enabled) return;
    if (typeof document === "undefined") return;

    const target: EventTarget = scopeRef?.current ?? document;

    const onKeyDown = (event: Event) => {
      const keyEvent = event as KeyboardEvent;
      if (isInTextField(keyEvent.target)) return;

      const combo = comboForEvent(keyEvent);

      // For single-key combos (no modifier), require that the combo key
      // is one of the bare keys we explicitly support, so we don't
      // hijack arbitrary keypresses like "b" or "x".
      const matched = matchCombo(combo, handlersRef.current);
      if (!matched) return;

      if (preventDefault) keyEvent.preventDefault();
      const handler = handlersRef.current[matched];
      if (handler) handler(keyEvent);
    };

    target.addEventListener("keydown", onKeyDown as EventListener);
    return () => {
      target.removeEventListener("keydown", onKeyDown as EventListener);
    };
  }, [enabled, scopeRef, preventDefault]);
}

/**
 * Look up a matching combo. Returns the exact key in `handlers` if any
 * (so the caller can mark preventDefault). When the event has a
 * modifier, we accept either Ctrl or Meta to satisfy the "Cmd/Ctrl are
 * equivalent" rule.
 *
 * Both the event combo and every registered combo are normalized into
 * canonical form (Shift, Alt, Ctrl, key) so the order the user wrote
 * them in does not matter.
 */
function matchCombo(eventCombo: string, handlers: ShortcutHandlers): string | null {
  // Try the raw combo first (covers cases where the user wrote the
  // combo in the exact modifier order the runtime produced).
  if (handlers[eventCombo]) return eventCombo;

  const eventCanonical = canonicalize(eventCombo);

  for (const key of Object.keys(handlers)) {
    if (canonicalize(key) === eventCanonical) return key;
  }

  return null;
}

/**
 * Re-order a combo so modifiers appear in Shift, Alt, Ctrl, key order.
 * This makes matching robust to differences in writing style
 * (e.g. "Ctrl+Shift+D" vs "Shift+Ctrl+D").
 */
function canonicalize(combo: string): string {
  const tokens = combo.split("+").map((t) => t.trim()).filter(Boolean);
  const hasShift = tokens.includes("Shift");
  const hasAlt = tokens.includes("Alt");
  const hasCtrl = tokens.includes("Ctrl") || tokens.includes("Meta");
  const key = tokens.find(
    (t) => t !== "Shift" && t !== "Alt" && t !== "Ctrl" && t !== "Meta"
  );
  const parts: string[] = [];
  if (hasShift) parts.push("Shift");
  if (hasAlt) parts.push("Alt");
  if (hasCtrl) parts.push("Ctrl");
  if (key) parts.push(key);
  return parts.join("+");
}
