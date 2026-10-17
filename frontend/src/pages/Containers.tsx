import { ArrowUpCircle, Circle, RefreshCw, ShieldCheck, SquareTerminal, Trash2 } from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import HealthBadge from "../components/HealthBadge";
import ImageName from "../components/ImageName";
import JobList from "../components/JobList";
import { useConfirm } from "../components/ConfirmDialog";
import Meter from "../components/Meter";
import ScanBadge from "../components/ScanBadge";
import UpdateAction from "../components/UpdateAction";
import { useContainerStats } from "../hooks/useContainerStats";
import {
  CONTAINER_ACTION_ICONS,
  CONTAINER_ACTION_LABELS,
  ContainerConsole,
  containerActionsFor,
  containerStateLabel,
} from "../containerActions";
import { formatBytes, formatDate, formatPorts } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import { useT } from "../i18n";
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
  const t = useT();

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
        title: t("Delete container {name}?", { name: container.name }),
        message: t("Its named volumes are kept."),
        confirmLabel: t("Delete"),
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
    [refresh, confirm, t],
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

  if (error && !containers) return <div className="error">{t("Failed: {error}", { error })}</div>;
  if (!containers) return <div>{t("Loading…")}</div>;

  return (
    <div>
      <div className="row-between">
        <h1>{t("Containers")}</h1>
        <div className="button-row inline">
          <button
            type="button"
            className="secondary"
            disabled={jobsRunning}
            title={t("Run a Trivy CVE scan on every running image")}
            onClick={() => start(api.scanRunning)}
          >
            <ShieldCheck size={15} /> {t("Scan all for CVEs")}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={jobsRunning}
            title={t("Compare every image digest against its registry")}
            onClick={() => start(() => api.checkUpdates())}
          >
            <ArrowUpCircle size={15} /> {t("Check updates")}
          </button>
          <button type="button" className="secondary" onClick={refresh}>
            <RefreshCw size={15} /> {t("Refresh")}
          </button>
        </div>
      </div>

      <JobList jobs={jobs} onDismiss={dismiss} />
      {error && <div className="error">{error}</div>}

      {containers.length === 0 ? (
        <div className="empty">{t("No containers running.")}</div>
      ) : (
        <table className="projects-table compact">
          <thead>
            <tr>
              <th>{t("Name")}</th>
              <th>{t("Image")}</th>
              <th>{t("CVEs")}</th>
              <th>{t("Status")}</th>
              <th>CPU</th>
              <th>{t("Memory")}</th>
              <th>{t("Ports")}</th>
              <th>{t("Compose")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {containers.map((container) => (
              <tr key={container.id}>
                <td>
                  <Link
                    to={`/containers/${container.id}`}
                    title={t("Details, logs, CVEs and updates\nCreated {date}", {
                      date: formatDate(container.created_at),
                    })}
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
                    title={t("Restart policy: {policy}", {
                      policy: container.restart_policy || "no",
                    })}
                  >
                    <Circle size={8} fill="currentColor" /> {t(containerStateLabel(container.state))}
                  </span>{" "}
                  <HealthBadge health={container.health} />
                  {container.restart_count > 0 && (
                    <div className="muted" title={t("Restarts since the container was created")}>
                      {container.restart_count === 1
                        ? t("1 restart")
                        : t("{count} restarts", { count: container.restart_count })}
                    </div>
                  )}
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
                          title={t(CONTAINER_ACTION_LABELS[action])}
                          aria-label={t(CONTAINER_ACTION_LABELS[action])}
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
                        title={t("Open a shell in this container")}
                        aria-label={t("console")}
                        onClick={() => setConsoleFor(container)}
                      >
                        <SquareTerminal size={14} />
                      </button>
                    )}
                    {["exited", "created", "dead"].includes(container.state) && (
                      <button
                        type="button"
                        className="secondary small icon-only"
                        title={t("Delete this container")}
                        aria-label={t("delete")}
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
  const t = useT();
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
        title={t("PIDs: {pids} · disk read {read} / write {write}", {
          pids: stats.pids ?? "?",
          read: formatBytes(stats.block_read),
          write: formatBytes(stats.block_write),
        })}
      >
        {stats.cpu_percent.toFixed(1)}%
        <Meter percent={stats.cpu_percent} />
      </td>
      <td
        title={t("Network rx {rx} / tx {tx}", {
          rx: formatBytes(stats.network_rx),
          tx: formatBytes(stats.network_tx),
        })}
      >
        {formatBytes(stats.memory_usage)}
        <span className="muted"> / {formatBytes(stats.memory_limit)}</span>
        <Meter percent={stats.memory_percent} />
      </td>
    </>
  );
}
