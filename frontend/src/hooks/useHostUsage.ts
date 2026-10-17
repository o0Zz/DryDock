import { useEffect, useState } from "react";
import { api } from "../api";
import type { HostUsage } from "../types";

const HOST_INTERVAL_MS = 5000;

/** Polls /api/dashboard/host while mounted. Same pacing as useContainerStats:
 * the next poll is scheduled only after the previous one returns. */
export function useHostUsage(): HostUsage | null {
  const [usage, setUsage] = useState<HostUsage | null>(null);
  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    const poll = (): void => {
      api
        .hostUsage()
        .then((next) => {
          if (!cancelled) setUsage(next);
        })
        .catch(() => undefined) // best-effort; the rest of the dashboard still works
        .finally(() => {
          if (!cancelled) timer = window.setTimeout(poll, HOST_INTERVAL_MS);
        });
    };
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);
  return usage;
}
