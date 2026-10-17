import { useEffect, useState } from "react";
import { api } from "../api";
import type { ContainerStats } from "../types";

const STATS_INTERVAL_MS = 5000;

/** Polls /api/containers/stats while mounted; each call takes ~1s server-side,
 * so the next poll is scheduled only after the previous one returns. */
export function useContainerStats(): Record<string, ContainerStats> {
  const [stats, setStats] = useState<Record<string, ContainerStats>>({});
  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    const poll = () => {
      api
        .containerStats()
        .then((list) => {
          if (!cancelled) setStats(Object.fromEntries(list.map((s) => [s.id, s])));
        })
        .catch(() => undefined) // stats are best-effort; pages still work without them
        .finally(() => {
          if (!cancelled) timer = window.setTimeout(poll, STATS_INTERVAL_MS);
        });
    };
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);
  return stats;
}
