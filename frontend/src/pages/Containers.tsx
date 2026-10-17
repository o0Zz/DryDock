import {
  ArrowUpCircle,
  Circle,
  Play,
  RefreshCw,
  RotateCw,
  ShieldCheck,
  Square,
  SquareTerminal,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import JobList from "../components/JobList";
import Meter, { formatBytes } from "../components/Meter";
import ScanBadge from "../components/ScanBadge";
import UpdateAction from "../components/UpdateAction";
import { useContainerStats } from "../hooks/useContainerStats";
import { useJobs } from "../hooks/useJobs";
import type {
  Container,
  ContainerStats,
  Job,
  Project,
  ScanSummary,
  UpdateSummary,
} from "../types";

type Action = "start" | "stop" | "restart";
const ACTIONS: Action[] = ["start", "stop", "restart"];
const ACTION_ICONS: Record<Action, LucideIcon> = {
  start: Play,
  stop: Square,
  restart: RotateCw,
};

// xterm.js is heavy; only load it when a console is opened.
const ContainerConsole = lazy(() => import("../components/ContainerConsole"));

export default function Containers() {
  const [containers, setContainers] = useState<Container[] | null>(null);
  const [scans, setScans] = useState<Record<string, ScanSummary>>({});
  const [error, setError] = useState<string | null>(null);
  const [updates, setUpdates] = useState<Record<string, UpdateSummary>>({});
  // Owning Compose project per container id, for the "edit tag" shortcut.
  const [projects, setProjects] = useState<Record<string, Project>>({});
  const [consoleFor, setConsoleFor] = useState<Container | null>(null);
  const { user } = useAuth();
  const stats = useContainerStats();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api
      .listContainers()
      .then(setContainers)
      .catch((e: Error) => setError(e.message));
  }, []);

  const loadScans = useCallback(() => {
    // Scans and update checks are best-effort context for the CVE / image
    // columns; a failure here shouldn't take down the whole container list.
    api
      .listScans()
      .then((list) => setScans(Object.fromEntries(list.map((s) => [s.image, s]))))
      .catch(() => undefined);
    api
      .listUpdates()
      .then((list) => setUpdates(Object.fromEntries(list.map((u) => [u.image, u]))))
      .catch(() => undefined);
    api
      .listProjects()
      .then((list) =>
        setProjects(
          Object.fromEntries(list.flatMap((p) => p.containers.map((c) => [c.id, p]))),
        ),
      )
      .catch(() => undefined);
  }, []);

  // An update job recreates the container, so its id changes: reload both.
  const onJobSettled = useCallback(() => {
    loadScans();
    refresh();
  }, [loadScans, refresh]);

  const { jobs, track, dismiss, busy: jobsRunning } = useJobs(onJobSettled);

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

  const remove = useCallback(
    async (c: Container) => {
      if (!window.confirm(`Delete container "${c.name}"? Its named volumes are kept.`)) return;
      setBusy(`${c.id}:delete`);
      try {
        await api.deleteContainer(c.id);
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
        <table className="projects-table compact">
          <thead>
            <tr>
              <th>Name</th>
              <th>Image</th>
              <th>CVEs</th>
              <th>Status</th>
              <th>CPU</th>
              <th>Memory</th>
              <th>Ports</th>
              <th>Compose</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {containers.map((c) => (
              <tr key={c.id}>
                <td>
                  <Link
                    to={`/containers/${c.id}`}
                    title={`Details, logs, CVEs and updates\nCreated ${new Date(c.created_at).toLocaleString()}`}
                  >
                    {c.name}
                  </Link>
                </td>
                <td>
                  {c.image}
{" "}
                  <UpdateAction
                    container={c}
                    update={updates[c.image]}
                    project={projects[c.id]}
                    pending={jobs.some(
                      (j) => j.label === `Update ${c.name}` && !["success", "error"].includes(j.status),
                    )}
                    onJob={track}
                    onError={setError}
                  />
                </td>
                <td>
                  <ScanBadge
                    scan={scans[c.image]}
                    pending={pendingImages.has(c.image)}
                    onScan={() => start(() => api.scanImage(c.image))}
                    onOpen={() => navigate(`/containers/${c.id}?tab=cves`)}
                  />
                </td>
                <td>
                  <span
                    className={`badge ${c.state}`}
                    title={`Restart policy: ${c.restart_policy || "no"}`}
                  >
                    <Circle size={8} fill="currentColor" /> {c.state}
                  </span>
                </td>
                <StatsCells stats={stats[c.id]} />
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
                          className="secondary small icon-only"
                          title={a}
                          aria-label={a}
                          disabled={busy === `${c.id}:${a}`}
                          onClick={() => runAction(c.id, a)}
                        >
                          <Icon size={14} />
                        </button>
                      );
                    })}
                    {user?.is_admin && c.state === "running" && (
                      <button
                        type="button"
                        className="secondary small icon-only"
                        title="Open a shell in this container"
                        aria-label="console"
                        onClick={() => setConsoleFor(c)}
                      >
                        <SquareTerminal size={14} />
                      </button>
                    )}
                    {["exited", "created", "dead"].includes(c.state) && (
                      <button
                        type="button"
                        className="secondary small icon-only"
                        title="Delete this container"
                        aria-label="delete"
                        disabled={busy === `${c.id}:delete`}
                        onClick={() => remove(c)}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {consoleFor && (
        <Suspense fallback={null}>
          <ContainerConsole
            key={consoleFor.id}
            containerId={consoleFor.id}
            title={consoleFor.name}
            onClose={() => setConsoleFor(null)}
          />
        </Suspense>
      )}
    </div>
  );
}

function StatsCells({ stats }: { stats?: ContainerStats }) {
  if (!stats) {
    return (
      <>
        <td className="muted">—</td>
        <td className="muted">—</td>
      </>
    );
  }
  return (
    <>
      <td
        title={`PIDs: ${stats.pids ?? "?"} · disk read ${formatBytes(stats.block_read)} / write ${formatBytes(stats.block_write)}`}
      >
        {stats.cpu_percent.toFixed(1)}%
        <Meter percent={stats.cpu_percent} />
      </td>
      <td
        title={`Network rx ${formatBytes(stats.network_rx)} / tx ${formatBytes(stats.network_tx)}`}
      >
        {formatBytes(stats.memory_usage)}
        <span className="muted"> / {formatBytes(stats.memory_limit)}</span>
        <Meter percent={stats.memory_percent} />
      </td>
    </>
  );
}
