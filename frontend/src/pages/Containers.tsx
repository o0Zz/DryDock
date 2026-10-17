import {
  ArrowUpCircle,
  Circle,
  Play,
  RefreshCw,
  RotateCw,
  ScrollText,
  ShieldCheck,
  Square,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import JobList from "../components/JobList";
import LogPanel from "../components/LogPanel";
import ScanBadge from "../components/ScanBadge";
import { useJobs } from "../hooks/useJobs";
import type { Container, Job, ScanSummary } from "../types";

type Action = "start" | "stop" | "restart";
const ACTIONS: Action[] = ["start", "stop", "restart"];
const ACTION_ICONS: Record<Action, LucideIcon> = {
  start: Play,
  stop: Square,
  restart: RotateCw,
};

export default function Containers() {
  const [containers, setContainers] = useState<Container[] | null>(null);
  const [scans, setScans] = useState<Record<string, ScanSummary>>({});
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Container | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api
      .listContainers()
      .then(setContainers)
      .catch((e: Error) => setError(e.message));
  }, []);

  const loadScans = useCallback(() => {
    // Scans are best-effort context for the CVE column; a failure here
    // shouldn't take down the whole container list.
    api
      .listScans()
      .then((list) => setScans(Object.fromEntries(list.map((s) => [s.image, s]))))
      .catch(() => undefined);
  }, []);

  const { jobs, track, dismiss, busy: jobsRunning } = useJobs(loadScans);

  useEffect(() => {
    refresh();
    loadScans();
  }, [refresh, loadScans]);

  const start = useCallback(
    async (fn: () => Promise<Job>) => {
      setError(null);
      try {
        track(await fn());
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [track],
  );

  const runAction = useCallback(
    async (id: string, action: Action) => {
      const key = `${id}:${action}`;
      setBusy(key);
      try {
        await api.containerAction(id, action);
        refresh();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  // An image counts as "pending" while a job that names it is still in flight,
  // so its CVE cell shows progress instead of a stale result.
  const pendingImages = useMemo(() => {
    const images = new Set<string>();
    for (const job of jobs) {
      if (job.status !== "pending" && job.status !== "running") continue;
      // tasks.py reports per-image progress as "Scanning <image>".
      const progress = /^Scanning (.+)$/.exec(job.message ?? "");
      if (progress) images.add(progress[1]);
      // A queued single-image job is labelled "Scan <image>".
      const queued = /^Scan (.+)$/.exec(job.label);
      if (queued) images.add(queued[1]);
    }
    return images;
  }, [jobs]);

  if (error && !containers) return <div className="error">Failed: {error}</div>;
  if (!containers) return <div>Loading…</div>;

  return (
    <div>
      <div className="row-between">
        <h1>Containers</h1>
        <div className="button-row inline">
          <button
            type="button"
            className="secondary"
            disabled={jobsRunning}
            title="Run a Trivy CVE scan on every running image"
            onClick={() => start(api.scanRunning)}
          >
            <ShieldCheck size={15} /> Scan all for CVEs
          </button>
          <button
            type="button"
            className="secondary"
            disabled={jobsRunning}
            title="Compare every image digest against its registry"
            onClick={() => start(() => api.checkUpdates())}
          >
            <ArrowUpCircle size={15} /> Check updates
          </button>
          <button type="button" className="secondary" onClick={refresh}>
            <RefreshCw size={15} /> Refresh
          </button>
        </div>
      </div>

      <JobList jobs={jobs} onDismiss={dismiss} />
      {error && <div className="error">{error}</div>}

      {containers.length === 0 ? (
        <div className="empty">No containers running.</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Image</th>
              <th>CVEs</th>
              <th>Status</th>
              <th>Ports</th>
              <th>Compose</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {containers.map((c) => (
              <tr key={c.id}>
                <td>
                  <button
                    type="button"
                    className="linklike"
                    title="View logs"
                    onClick={() => setSelected(c)}
                  >
                    <ScrollText size={14} /> {c.name}
                  </button>
                  <div className="muted">
                    created {new Date(c.created_at).toLocaleString()}
                  </div>
                </td>
                <td>{c.image}</td>
                <td>
                  <ScanBadge
                    scan={scans[c.image]}
                    pending={pendingImages.has(c.image)}
                    onScan={() => start(() => api.scanImage(c.image))}
                  />
                </td>
                <td>
                  <span className={`badge ${c.state}`}>
                    <Circle size={8} fill="currentColor" /> {c.state}
                  </span>
                  <div className="muted">restart: {c.restart_policy || "no"}</div>
                </td>
                <td>
                  {c.ports
                    .filter((p) => p.public_port)
                    .map((p) => `${p.public_port}→${p.private_port}/${p.protocol}`)
                    .join(", ") || "—"}
                </td>
                <td>
                  {c.compose_project
                    ? `${c.compose_project} / ${c.compose_service ?? ""}`
                    : "—"}
                </td>
                <td>
                  <div className="button-row inline">
                    {ACTIONS.map((a) => {
                      const Icon = ACTION_ICONS[a];
                      return (
                        <button
                          key={a}
                          type="button"
                          className="secondary small"
                          disabled={busy === `${c.id}:${a}`}
                          onClick={() => runAction(c.id, a)}
                        >
                          <Icon size={14} /> {a}
                        </button>
                      );
                    })}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <LogPanel
          title={selected.name}
          url={`/api/logs/container/${selected.id}?tail=200`}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
