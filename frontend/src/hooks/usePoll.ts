import { useEffect, useRef, useState } from "react";

/** Calls `fetcher` while mounted, `intervalMs` after each answer, so slow calls never
 * overlap. Failures are skipped: the data is best-effort and the page works without it. */
export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number): T | null {
  const [value, setValue] = useState<T | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    const poll = (): void => {
      fetcherRef
        .current()
        .then((next) => {
          if (!cancelled) setValue(next);
        })
        .catch(() => undefined)
        .finally(() => {
          if (!cancelled) timer = window.setTimeout(poll, intervalMs);
        });
    };
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [intervalMs]);
  return value;
}
