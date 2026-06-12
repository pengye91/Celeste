import { useEffect, useRef, useCallback } from "react";

export function usePolling<T>(
  fetchFn: () => Promise<T>,
  intervalMs: number,
  enabled: boolean = true
) {
  const savedCallback = useRef(fetchFn);

  useEffect(() => {
    savedCallback.current = fetchFn;
  }, [fetchFn]);

  const tick = useCallback(() => {
    savedCallback.current();
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled, tick]);
}
