import { ListChecks, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { isActive, JOBS_CHANGED_EVENT } from "../hooks/useJobs";
import { useT } from "../i18n";
import type { Job } from "../types";
import JobList from "./JobList";

const RECENT_JOB_COUNT = 10;
const ACTIVE_POLL_MS = 1500;
const IDLE_POLL_MS = 10_000;

/** Topbar pill showing background jobs (scans, update checks, scheduled runs)
 * from any page; click for the recent list with progress. */
export default function JobsIndicator() {
  const t = useT();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const rootRef = useRef<HTMLDivElement | null>(null);

  const activeJobs = jobs.filter(isActive);

  // Poll fast while something runs, slowly otherwise; a job started anywhere in
  // the UI triggers an immediate refresh through JOBS_CHANGED_EVENT.
  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    // Only the newest request may schedule the next poll, so an event-triggered
    // refresh during an in-flight one does not start a second polling chain.
    let generation = 0;
    const poll = (): void => {
      window.clearTimeout(timer);
      const requestGeneration = ++generation;
      const isLatest = (): boolean => !cancelled && requestGeneration === generation;
      api
        .listJobs(RECENT_JOB_COUNT)
        .then((recentJobs) => {
          if (!isLatest()) return;
          setJobs(recentJobs);
          timer = window.setTimeout(
            poll,
            recentJobs.some(isActive) ? ACTIVE_POLL_MS : IDLE_POLL_MS,
          );
        })
        .catch(() => {
          if (isLatest()) timer = window.setTimeout(poll, IDLE_POLL_MS);
        });
    };
    poll();
    window.addEventListener(JOBS_CHANGED_EVENT, poll);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.removeEventListener(JOBS_CHANGED_EVENT, poll);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: MouseEvent): void => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  const visibleJobs = jobs.filter((job) => isActive(job) || !dismissed.has(job.id));
  const firstActive = activeJobs[0];

  return (
    <div className="jobs-indicator" ref={rootRef}>
      <button
        type="button"
        className={
          activeJobs.length ? "secondary small jobs-pill active" : "secondary small jobs-pill"
        }
        title={t("Background jobs")}
        onClick={() => setOpen((previous) => !previous)}
      >
        {activeJobs.length ? (
          <>
            <Loader2 size={14} className="spin" />
            <span className="jobs-pill-label">
              {activeJobs.length > 1
                ? t("{count} jobs running", { count: activeJobs.length })
                : firstActive.label}
              {firstActive.total > 0 && ` · ${firstActive.done}/${firstActive.total}`}
            </span>
          </>
        ) : (
          <>
            <ListChecks size={14} /> {t("Jobs")}
          </>
        )}
      </button>
      {open && (
        <div className="jobs-dropdown">
          {visibleJobs.length === 0 ? (
            <div className="muted">{t("No recent jobs.")}</div>
          ) : (
            <JobList
              jobs={visibleJobs}
              onDismiss={(id) => setDismissed((previous) => new Set(previous).add(id))}
            />
          )}
        </div>
      )}
    </div>
  );
}
