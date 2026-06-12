"use client";

import { useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";

/**
 * Read and write a single URL search parameter, with optional allow-list
 * validation. Writes use `router.replace` with `scroll: false` so the
 * page position is preserved.
 *
 * - `defaultValue` is returned when the param is missing or invalid.
 * - `allowed`, when provided, constrains the value; out-of-set values
 *   fall back to `defaultValue`.
 */
export function useUrlState(
  key: string,
  defaultValue: string,
  allowed?: readonly string[]
): [string, (next: string) => void] {
  const router = useRouter();
  const searchParams = useSearchParams();

  const raw = searchParams?.get(key) ?? null;
  const value = useMemo(() => {
    if (raw === null || raw === "") return defaultValue;
    if (allowed && !allowed.includes(raw)) return defaultValue;
    return raw;
  }, [raw, defaultValue, allowed]);

  const setValue = useCallback(
    (next: string) => {
      if (typeof window === "undefined") return;
      const params = new URLSearchParams(searchParams?.toString() ?? "");
      if (next === defaultValue || next === "") {
        params.delete(key);
      } else {
        params.set(key, next);
      }
      const qs = params.toString();
      const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
      router.replace(url, { scroll: false });
    },
    [router, searchParams, key, defaultValue]
  );

  return [value, setValue];
}
