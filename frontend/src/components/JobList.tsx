import { AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";
import type { Job } from "../types";

/** Progress strip for background jobs started from the current page. */
export default function JobList({
  jobs,
  onDismiss,
}: {
  jobs: Job[];
  onDismiss: (id: string) => void;
}) {
  if (jobs.length === 0) return null;

  return (
    <div className="job-list">
      {jobs.map((job) => {
        const running = job.status === "pending" || job.status === "running";
        const pct = job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;
        return (
          <div key={job.id} className={`job job-${job.status}`}>
            <span className="job-icon">
              {running ? (
                <Loader2 size={15} className="spin" />
              ) : job.status === "success" ? (
                <CheckCircle2 size={15} />
              ) : (
                <AlertCircle size={15} />
              )}
            </span>
            <div className="job-body">
              <div className="job-label">
                {job.label}
                {job.total > 0 && running && (
                  <span className="muted">
                    {" "}
                    {job.done}/{job.total}
                  </span>
                )}
              </div>
              <div className="muted">{job.error ?? job.message ?? job.status}</div>
              {running && job.total > 0 && (
                <div className="job-bar">
                  <div className="job-bar-fill" style={{ width: `${pct}%` }} />
                </div>
              )}
            </div>
            {!running && (
              <button
                type="button"
                className="secondary small"
                title="Dismiss"
                onClick={() => onDismiss(job.id)}
              >
                <X size={14} />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
