import { AlertCircle, AlertTriangle, CheckCircle2, Loader2, X } from "lucide-react";
import { isActive } from "../hooks/useJobs";
import { msg, useT } from "../i18n";
import type { Job, JobStatus } from "../types";

/** Display text of a job status; translate it with `t()`. */
export const JOB_STATUS_TEXT: Record<JobStatus, string> = {
  pending: msg("pending"),
  running: msg("running"),
  success: msg("success"),
  error: msg("error"),
};

/** Jobs end "success" even when some images failed (the summary says
 * "…, 2 failed"); surface that instead of a green check. */
function failedCount(job: Job): number {
  if (job.status !== "success") return 0;
  const match = /(\d+) failed/.exec(job.message ?? "");
  return match ? Number(match[1]) : 0;
}

/** Progress strip for background jobs. */
export default function JobList({
  jobs,
  onDismiss,
}: {
  jobs: Job[];
  onDismiss: (id: string) => void;
}) {
  const t = useT();
  if (jobs.length === 0) return null;

  return (
    <div className="job-list">
      {jobs.map((job) => {
        const running = isActive(job);
        const percent = job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;
        const failedImages = failedCount(job);
        return (
          <div key={job.id} className={`job job-${failedImages ? "warning" : job.status}`}>
            <span className="job-icon">
              {running ? (
                <Loader2 size={15} className="spin" />
              ) : failedImages ? (
                <AlertTriangle size={15} />
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
              <div className="muted">
                {job.error ?? job.message ?? t(JOB_STATUS_TEXT[job.status])}
                {failedImages > 0 && ` — ${t("see Logs for details")}`}
              </div>
              {running && job.total > 0 && (
                <div className="job-bar">
                  <div className="job-bar-fill" style={{ width: `${percent}%` }} />
                </div>
              )}
            </div>
            {!running && (
              <button
                type="button"
                className="secondary small"
                title={t("Dismiss")}
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
