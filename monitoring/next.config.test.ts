/**
 * Tests for the Next.js config: API rewrite destination must honor the
 * `NEXT_PUBLIC_CELESTE_API_URL` env var (the same one consumed by
 * `src/lib/api.ts`) and fall back to http://localhost:8000.
 *
 * Regression: previously the rewrite proxy read `NEXT_PUBLIC_API_URL`
 * while the API client read `NEXT_PUBLIC_CELESTE_API_URL`. Setting only
 * one of them caused a silent mismatch — the proxy used the default
 * localhost URL while the client pointed elsewhere.
 *
 * Strategy: extract the API_BASE_URL constant from next.config.ts and
 * evaluate it against a synthetic env object.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

function readConfig(): string {
  return readFileSync(resolve(__dirname, "next.config.ts"), "utf8");
}

/**
 * Evaluate the `const API_BASE_URL = ...` block against a synthetic env.
 * Supports the pattern `process.env.X || process.env.Y || "default"`.
 */
function evalApiBaseUrl(
  src: string,
  env: Record<string, string | undefined>,
): string {
  const match = src.match(/const\s+API_BASE_URL\s*=\s*([\s\S]+?);/);
  if (!match) {
    throw new Error(
      "Could not find `const API_BASE_URL = ...;` in next.config.ts",
    );
  }
  const rhs = match[1];
  // Split on `||` and resolve each operand left-to-right.
  const parts = rhs.split("||").map((p) => p.trim());
  for (const part of parts) {
    const envMatch = part.match(/^process\.env\.([A-Z0-9_]+)$/);
    if (envMatch) {
      const v = env[envMatch[1]];
      if (v) return v;
      continue;
    }
    const stringMatch = part.match(/^"([^"]*)"$/);
    if (stringMatch) {
      return stringMatch[1];
    }
    throw new Error(`Unrecognized operand in API_BASE_URL: ${part}`);
  }
  return "";
}

describe("next.config.ts API rewrite destination", () => {
  it("reads NEXT_PUBLIC_CELESTE_API_URL (matching src/lib/api.ts)", () => {
    const src = readConfig();
    expect(src, "next.config.ts must mention NEXT_PUBLIC_CELESTE_API_URL").toContain(
      "NEXT_PUBLIC_CELESTE_API_URL",
    );
    // NEXT_PUBLIC_CELESTE_API_URL must come BEFORE NEXT_PUBLIC_API_URL
    // so the canonical name wins precedence.
    const canonicalIdx = src.indexOf("NEXT_PUBLIC_CELESTE_API_URL");
    const legacyIdx = src.indexOf("NEXT_PUBLIC_API_URL");
    expect(
      canonicalIdx,
      "NEXT_PUBLIC_CELESTE_API_URL must appear in next.config.ts",
    ).toBeGreaterThan(-1);
    if (legacyIdx !== -1) {
      expect(
        canonicalIdx,
        "NEXT_PUBLIC_CELESTE_API_URL must precede NEXT_PUBLIC_API_URL " +
          "so it takes precedence in the || chain",
      ).toBeLessThan(legacyIdx);
    }
  });

  it("falls back to http://localhost:8000 when env var is unset", () => {
    const base = evalApiBaseUrl(readConfig(), {});
    expect(base).toBe("http://localhost:8000");
  });

  it("honors NEXT_PUBLIC_CELESTE_API_URL when set", () => {
    const base = evalApiBaseUrl(readConfig(), {
      NEXT_PUBLIC_CELESTE_API_URL: "https://celeste.example.test",
    });
    expect(base).toBe("https://celeste.example.test");
  });

  it("falls back to NEXT_PUBLIC_API_URL when NEXT_PUBLIC_CELESTE_API_URL is unset", () => {
    const base = evalApiBaseUrl(readConfig(), {
      NEXT_PUBLIC_API_URL: "https://legacy.example.test",
    });
    expect(base).toBe("https://legacy.example.test");
  });

  it("prefers NEXT_PUBLIC_CELESTE_API_URL over NEXT_PUBLIC_API_URL", () => {
    const base = evalApiBaseUrl(readConfig(), {
      NEXT_PUBLIC_CELESTE_API_URL: "https://new.example.test",
      NEXT_PUBLIC_API_URL: "https://legacy.example.test",
    });
    expect(base).toBe("https://new.example.test");
  });
});