import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Job } from "../types";

const POLL_MS = 1500;

/** Fired when a job is started from any page, so the topbar refreshes at once. */
export const JOBS_CHANGED_EVENT = "drydock:jobs-changed";

/** Still pending or running. */
export function isActive(job: Job): boolean {
  return job.status === "pending" || job.status === "running";
}

/**
 * Tracks background jobs (scans, update checks) started from this page.
 *
 * Scans routinely take minutes, so the API hands back a job instead of blocking
 * the request; this polls the ones we started and calls `onSettled` once each
 * finishes so the page can reload whatever the job produced. `start` queues a
 * job and reports a failed request through `onError` (cleared with null first).
 */
export function useJobs(onSettled?: () => void, onError?: (message: string | null) => void) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const settled = useRef(onSettled);
  settled.current = onSettled;
  const failed = useRef(onError);
  failed.current = onError;

  const track = useCallback((job: Job) => {
    setJobs((prev) =>
      prev.some((j) => j.id === job.id) ? prev : [...prev, job],
    );
    window.dispatchEvent(new Event(JOBS_CHANGED_EVENT));
  }, []);

  const start = useCallback(
    async (fn: () => Promise<Job>) => {
      failed.current?.(null);
      try {
        track(await fn());
      } catch (e) {
        failed.current?.((e as Error).message);
      }
    },
    [track],
  );

  // Re-attach to jobs still running server-side (started before navigating
  // away, or by the scheduler), so progress and busy state survive page changes.
  useEffect(() => {
    let cancelled = false;
    api
      .listActiveJobs()
      .then((list) => {
        if (cancelled || list.length === 0) return;
        setJobs((prev) => [...prev, ...list.filter((j) => !prev.some((p) => p.id === j.id))]);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const dismiss = useCallback((id: string) => {
    setJobs((prev) => prev.filter((j) => j.id !== id));
  }, []);

  const active = jobs.filter(isActive);

  useEffect(() => {
    if (active.length === 0) return;
    let cancelled = false;

    const timer = window.setInterval(async () => {
      const updated = await Promise.all(
        active.map((j) => api.getJob(j.id).catch(() => j)),
      );
      if (cancelled) return;
      setJobs((prev) =>
        prev.map((j) => updated.find((u) => u.id === j.id) ?? j),
      );
      if (updated.some((j) => !isActive(j))) settled.current?.();
    }, POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // Re-arm whenever the set of unfinished jobs changes.
  }, [active.map((j) => j.id).join(",")]);

  return { jobs, track, start, dismiss, busy: active.length > 0 };
}
