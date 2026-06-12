"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * Accessibility utilities for CMC.
 *
 * - `announcePolite` / `announceAssertive` write to singleton aria-live
 *   regions in the document so screen readers pick up status changes
 *   without screen-reader users having to move focus.
 * - `useFocusTrap` traps Tab focus inside a container while active and
 *   restores focus to the previously focused element on cleanup.
 * - `useSkipLink` returns a ref to attach to a "Skip to main content"
 *   anchor at the top of the page.
 */

const POLITE_ID = "cmc-aria-live-polite";
const ASSERTIVE_ID = "cmc-aria-live-assertive";

function ensureRegion(id: string, politeness: "polite" | "assertive"): HTMLElement | null {
  if (typeof document === "undefined") return null;
  let region = document.getElementById(id);
  if (!region) {
    region = document.createElement("div");
    region.id = id;
    region.setAttribute("aria-live", politeness);
    region.setAttribute("aria-atomic", "true");
    // Visually hidden but still announced.
    region.style.position = "absolute";
    region.style.width = "1px";
    region.style.height = "1px";
    region.style.padding = "0";
    region.style.margin = "-1px";
    region.style.overflow = "hidden";
    region.style.clip = "rect(0,0,0,0)";
    region.style.whiteSpace = "nowrap";
    region.style.border = "0";
    document.body.appendChild(region);
  }
  return region;
}

/**
 * Announce a message politely (does not interrupt the current announcement).
 * Safe to call when `document` is undefined (SSR / jsdom edge cases): it
 * becomes a no-op.
 */
export function announcePolite(message: string): void {
  const region = ensureRegion(POLITE_ID, "polite");
  if (!region) return;
  // Re-set the textContent to trigger SR re-announcement even if the
  // value is the same as the previous message.
  region.textContent = "";
  // Use a microtask so consecutive updates still register.
  queueMicrotask(() => {
    region.textContent = message;
  });
}

/**
 * Announce a message assertively (interrupts the current announcement).
 */
export function announceAssertive(message: string): void {
  const region = ensureRegion(ASSERTIVE_ID, "assertive");
  if (!region) return;
  region.textContent = "";
  queueMicrotask(() => {
    region.textContent = message;
  });
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
  "audio[controls]",
  "video[controls]",
  "details > summary",
].join(",");

/**
 * Trap Tab focus inside `ref` while `isActive` is true. On activation,
 * focus the first focusable child. On cleanup, restore focus to the
 * element that had focus before activation.
 */
export function useFocusTrap<T extends HTMLElement>(
  ref: React.RefObject<T | null>,
  isActive: boolean
): void {
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isActive) return;
    if (typeof document === "undefined") return;

    const container = ref.current;
    if (!container) return;

    previouslyFocused.current = (document.activeElement as HTMLElement | null) ?? null;

    const focusFirst = () => {
      const focusables = container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
      const first = focusables[0] ?? container;
      first.focus();
    };
    focusFirst();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusables = Array.from(
        container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      ).filter((el) => !el.hasAttribute("disabled"));
      if (focusables.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (event.shiftKey) {
        if (active === first || !container.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else {
        if (active === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      const previous = previouslyFocused.current;
      if (previous && typeof previous.focus === "function") {
        previous.focus();
      }
    };
  }, [isActive, ref]);
}

/**
 * Returns a ref to attach to a "Skip to main content" anchor. The target
 * element is expected to expose `id="cmc-main"` and `tabIndex={-1}`.
 */
export function useSkipLink<T extends HTMLAnchorElement>(): React.RefObject<T | null> {
  const ref = useRef<T | null>(null);
  const onClick = useCallback((event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    if (typeof document === "undefined") return;
    const target = document.getElementById("cmc-main");
    if (target) {
      target.focus();
      target.scrollIntoView();
    }
  }, []);
  // Attach the click handler via a ref callback so the caller doesn't
  // need to wire it up.
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    node.addEventListener("click", onClick as unknown as EventListener);
    return () => node.removeEventListener("click", onClick as unknown as EventListener);
  }, [onClick]);
  return ref;
}
