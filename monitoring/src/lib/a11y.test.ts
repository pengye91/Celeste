import { describe, it, expect, beforeEach } from "vitest";
import { announcePolite, announceAssertive } from "@/lib/a11y";

describe("announcePolite", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("creates the polite region in jsdom and sets its textContent", () => {
    announcePolite("hello world");
    const region = document.getElementById("cmc-aria-live-polite");
    expect(region).toBeInTheDocument();
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveAttribute("aria-atomic", "true");
  });

  it("reuses the polite region across multiple calls", () => {
    announcePolite("first");
    const first = document.getElementById("cmc-aria-live-polite");
    announcePolite("second");
    const second = document.getElementById("cmc-aria-live-polite");
    expect(first).toBe(second);
  });
});

describe("announceAssertive", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("creates the assertive region in jsdom", () => {
    announceAssertive("critical error");
    const region = document.getElementById("cmc-aria-live-assertive");
    expect(region).toBeInTheDocument();
    expect(region).toHaveAttribute("aria-live", "assertive");
  });

  it("keeps the polite and assertive regions distinct", () => {
    announcePolite("p");
    announceAssertive("a");
    expect(document.getElementById("cmc-aria-live-polite")).not.toBe(
      document.getElementById("cmc-aria-live-assertive")
    );
  });
});
