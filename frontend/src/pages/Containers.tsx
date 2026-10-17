import { ArrowUpCircle, Circle, RefreshCw, ShieldCheck, SquareTerminal, Trash2 } from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import ImageName from "../components/ImageName";
import JobList from "../components/JobList";
import { useConfirm } from "../components/ConfirmDialog";
import Meter from "../components/Meter";
import ScanBadge from "../components/ScanBadge";
import UpdateAction from "../components/UpdateAction";
import { useContainerStats } from "../hooks/useContainerStats";
import { CONTAINER_ACTION_ICONS, ContainerConsole, containerActionsFor } from "../containerActions";
import { formatBytes, formatDate, formatPorts } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import type {
  Container,
  ContainerAction,
  ContainerStats,
  Project,
  ScanSummary,
  UpdateSummary,
} from "../types";

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
  const confirm = useConfirm();

  const refresh = useCallback((): void => {
    api
      .listContainers()
      .then(setContainers)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  const loadScans = useCallback((): void => {
    // Scans and update checks are best-effort context for the CVE / image
    // columns; a failure here shouldn't take down the whole container list.
    api
      .listScans()
      .then((scanList) => setScans(Object.fromEntries(scanList.map((scan) => [scan.image, scan]))))
      .catch(() => undefined);
    api
      .listUpdates()
      .then((updateList) =>
        setUpdates(Object.fromEntries(updateList.map((update) => [update.image, update]))),
      )
      .catch(() => undefined);
    api
      .listProjects()
      .then((projectList) =>
        setProjects(
          Object.fromEntries(
            projectList.flatMap((project) =>
              project.containers.map((container) => [container.id, project]),
            ),
          ),
        ),
      )
      .catch(() => undefined);
  }, []);

  // An update job recreates the container, so its id changes: reload both.
  const onJobSettled = useCallback((): void => {
    loadScans();
    refresh();
  }, [loadScans, refresh]);

  const { jobs, track, start, dismiss, busy: jobsRunning } = useJobs(onJobSettled, setError);

  useEffect(() => {
    refresh();
    loadScans();
  }, [refresh, loadScans]);

  const runAction = useCallback(
    async (id: string, action: ContainerAction): Promise<void> => {
      setBusy(`${id}:${action}`);
      try {
        await api.containerAction(id, action);
        refresh();
      } catch (actionError) {
        setError((actionError as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (container: Container): Promise<void> => {
      const confirmed = await confirm({
        title: `Delete container ${container.name}?`,
        message: "Its named volumes are kept.",
        confirmLabel: "Delete",
        tone: "danger",
      });
      if (!confirmed) return;
      setBusy(`${container.id}:delete`);
      try {
        await api.deleteContainer(container.id);
        refresh();
      } catch (deleteError) {
        setError((deleteError as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [refresh, confirm],
  );

  // An image counts as "pending" while a job that names it is still in flight,
  // so its CVE cell shows progress instead of a stale result.
  const pendingImages = useMemo(() => {
    const images = new Set<string>();
    for (const job of jobs) {
      if (!isActive(job)) continue;
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
            {containers.map((container) => (
              <tr key={container.id}>
                <td>
                  <Link
                    to={`/containers/${container.id}`}
                    title={`Details, logs, CVEs and updates\nCreated ${formatDate(container.created_at)}`}
                  >
                    {container.name}
                  </Link>
                </td>
                <td>
                  <ImageName image={container.image} version={container.image_version} />{" "}
                  <UpdateAction
                    container={container}
                    update={updates[container.image]}
                    project={projects[container.id]}
                    pending={jobs.some(
                      (job) => job.label === `Update ${container.name}` && isActive(job),
                    )}
                    onJob={track}
                    onError={setError}
                  />
                </td>
                <td>
                  <ScanBadge
                    scan={scans[container.image]}
                    pending={pendingImages.has(container.image)}
                    onScan={() => start(() => api.scanImage(container.image))}
                    onOpen={() => navigate(`/containers/${container.id}?tab=cves`)}
                  />
                </td>
                <td>
                  <span
                    className={`badge ${container.state}`}
                    title={`Restart policy: ${container.restart_policy || "no"}`}
                  >
                    <Circle size={8} fill="currentColor" /> {container.state}
                  </span>
                </td>
                <StatsCells stats={stats[container.id]} />
                <td>
                  {formatPorts(container.ports)}
                </td>
                <td>
                  {container.compose_project
                    ? `${container.compose_project} / ${container.compose_service ?? ""}`
                    : "—"}
                </td>
                <td>
                  <div className="button-row inline">
                    {containerActionsFor(container.state).map((action) => {
                      const Icon = CONTAINER_ACTION_ICONS[action];
                      return (
                        <button
                          key={action}
                          type="button"
                          className="secondary small icon-only"
                          title={action}
                          aria-label={action}
                          disabled={busy === `${container.id}:${action}`}
                          onClick={() => runAction(container.id, action)}
                        >
                          <Icon size={14} />
                        </button>
                      );
                    })}
                    {user?.is_admin && container.state === "running" && (
                      <button
                        type="button"
                        className="secondary small icon-only"
                        title="Open a shell in this container"
                        aria-label="console"
                        onClick={() => setConsoleFor(container)}
                      >
                        <SquareTerminal size={14} />
                      </button>
                    )}
                    {["exited", "created", "dead"].includes(container.state) && (
                      <button
                        type="button"
                        className="secondary small icon-only"
                        title="Delete this container"
                        aria-label="delete"
                        disabled={busy === `${container.id}:delete`}
                        onClick={() => remove(container)}
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
