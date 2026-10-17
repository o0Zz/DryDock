import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Job, JobTracker } from "../types";

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
export function useJobs(
  onSettled?: () => void,
  onError?: (message: string | null) => void,
): JobTracker {
  const [jobs, setJobs] = useState<Job[]>([]);
  const onSettledRef = useRef(onSettled);
  onSettledRef.current = onSettled;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const track = useCallback((job: Job): void => {
    setJobs((previous) =>
      previous.some((tracked) => tracked.id === job.id) ? previous : [...previous, job],
    );
    window.dispatchEvent(new Event(JOBS_CHANGED_EVENT));
  }, []);

  const start = useCallback(
    async (queueJob: () => Promise<Job>): Promise<void> => {
      onErrorRef.current?.(null);
      try {
        track(await queueJob());
      } catch (error) {
        onErrorRef.current?.((error as Error).message);
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
      .then((serverJobs) => {
        if (cancelled || serverJobs.length === 0) return;
        setJobs((previous) => [
          ...previous,
          ...serverJobs.filter((serverJob) => !previous.some((known) => known.id === serverJob.id)),
        ]);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const dismiss = useCallback((id: string): void => {
    setJobs((previous) => previous.filter((job) => job.id !== id));
  }, []);

  const activeJobs = jobs.filter(isActive);

  useEffect(() => {
    if (activeJobs.length === 0) return;
    let cancelled = false;

    const timer = window.setInterval(async () => {
      const updated = await Promise.all(
        activeJobs.map((job) => api.getJob(job.id).catch(() => job)),
      );
      if (cancelled) return;
      setJobs((previous) =>
        previous.map((job) => updated.find((fresh) => fresh.id === job.id) ?? job),
      );
      if (updated.some((job) => !isActive(job))) onSettledRef.current?.();
    }, POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // Re-arm whenever the set of unfinished jobs changes.
  }, [activeJobs.map((job) => job.id).join(",")]);

  return { jobs, track, start, dismiss, busy: activeJobs.length > 0 };
}
