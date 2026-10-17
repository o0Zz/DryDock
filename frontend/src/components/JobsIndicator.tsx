import { ListChecks, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { JOBS_CHANGED_EVENT } from "../hooks/useJobs";
import type { Job } from "../types";
import JobList from "./JobList";

const RECENT = 10;
const ACTIVE_POLL_MS = 1500;
const IDLE_POLL_MS = 10_000;

function isActive(job: Job): boolean {
  return job.status === "pending" || job.status === "running";
}

/** Topbar pill showing background jobs (scans, update checks, scheduled runs)
 * from any page; click for the recent list with progress. */
export default function JobsIndicator() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const rootRef = useRef<HTMLDivElement | null>(null);

  const active = jobs.filter(isActive);

  // Poll fast while something runs, slowly otherwise; a job started anywhere in
  // the UI triggers an immediate refresh through JOBS_CHANGED_EVENT.
  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    // Only the newest request may schedule the next poll, so an event-triggered
    // refresh during an in-flight one does not start a second polling chain.
    let generation = 0;
    const poll = () => {
      window.clearTimeout(timer);
      const mine = ++generation;
      const current = () => !cancelled && mine === generation;
      api
        .listJobs(RECENT)
        .then((list) => {
          if (!current()) return;
          setJobs(list);
          timer = window.setTimeout(poll, list.some(isActive) ? ACTIVE_POLL_MS : IDLE_POLL_MS);
        })
        .catch(() => {
          if (current()) timer = window.setTimeout(poll, IDLE_POLL_MS);
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
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const visible = jobs.filter((j) => isActive(j) || !dismissed.has(j.id));
  const current = active[0];

  return (
    <div className="jobs-indicator" ref={rootRef}>
      <button
        type="button"
        className={active.length ? "secondary small jobs-pill active" : "secondary small jobs-pill"}
        title="Background jobs"
        onClick={() => setOpen((v) => !v)}
      >
        {active.length ? (
          <>
            <Loader2 size={14} className="spin" />
            <span className="jobs-pill-label">
              {active.length > 1 ? `${active.length} jobs running` : current.label}
              {current.total > 0 && ` · ${current.done}/${current.total}`}
            </span>
          </>
        ) : (
          <>
            <ListChecks size={14} /> Jobs
          </>
        )}
      </button>
      {open && (
        <div className="jobs-dropdown">
          {visible.length === 0 ? (
            <div className="muted">No recent jobs.</div>
          ) : (
            <JobList
              jobs={visible}
              onDismiss={(id) => setDismissed((prev) => new Set(prev).add(id))}
            />
          )}
        </div>
      )}
    </div>
  );
}
