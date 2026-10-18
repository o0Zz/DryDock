import {
  ArrowUpCircle,
  ChevronLeft,
  Circle,
  Info,
  Pencil,
  RefreshCw,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  SquareTerminal,
} from "lucide-react";
import {
  Fragment,
  Suspense,
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import HealthBadge from "../components/HealthBadge";
import ImageName from "../components/ImageName";
import JobList from "../components/JobList";
import LogPanel from "../components/LogPanel";
import Meter from "../components/Meter";
import ScanFindings from "../components/ScanFindings";
import UpdateAction from "../components/UpdateAction";
import UpdateBadge, { hasUpdate } from "../components/UpdateBadge";
import {
  CONTAINER_ACTION_ICONS,
  CONTAINER_ACTION_LABELS,
  ContainerConsole,
  containerActionsFor,
  containerStateLabel,
} from "../containerActions";
import { formatBytes, formatDate } from "../format";
import { useContainerStats } from "../hooks/useContainerStats";
import { useJobs } from "../hooks/useJobs";
import { msg, useT } from "../i18n";
import type {
  ContainerAction,
  ContainerDetail as ContainerDetailData,
  Project,
  ScanDetail,
  ScanSummary,
  UpdateSummary,
} from "../types";

const TABS = [
  { key: "overview", label: msg("Overview"), icon: Info },
  { key: "logs", label: msg("Logs"), icon: ScrollText },
  { key: "cves", label: msg("CVEs"), icon: ShieldAlert },
  { key: "updates", label: msg("Updates"), icon: ArrowUpCircle },
] as const;
type Tab = (typeof TABS)[number]["key"];

/** Puts elements (<strong>, <code>) into the {placeholders} a translated sentence still has. */
function fillElements(text: string, elements: Record<string, ReactNode>): ReactNode {
  return text
    .split(/\{(\w+)\}/)
    .map((part, index) =>
      index % 2 === 1 ? <Fragment key={index}>{elements[part] ?? part}</Fragment> : part,
    );
}

export default function ContainerDetail() {
  const { id = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab: Tab = TABS.some((tabEntry) => tabEntry.key === searchParams.get("tab"))
    ? (searchParams.get("tab") as Tab)
    : "overview";
  const { user } = useAuth();
  const t = useT();
  const liveStats = useContainerStats()[id];
  const navigate = useNavigate();

  const [detail, setDetail] = useState<ContainerDetailData | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<ContainerAction | null>(null);
  const [showConsole, setShowConsole] = useState(false);
  // The new name while the rename form is open.
  const [newName, setNewName] = useState<string | null>(null);

  const load = useCallback((): void => {
    api
      .inspectContainer(id)
      .then((inspected) => {
        setDetail(inspected);
        setLoadError(null);
      })
      .catch((inspectError: Error) => setLoadError(inspectError.message));
  }, [id]);

  useEffect(() => {
    load();
    // The owning project gives a link back to the stack and its pull/redeploy actions.
    api
      .listProjects()
      .then((projectList) =>
        setProject(
          projectList.find((candidate) =>
            candidate.containers.some((container) => container.id === id),
          ) ?? null,
        ),
      )
      .catch(() => undefined);
  }, [id, load]);

  const runAction = useCallback(
    async (action: ContainerAction): Promise<void> => {
      setBusy(action);
      setError(null);
      try {
        await api.containerAction(id, action);
        load();
      } catch (actionError) {
        setError((actionError as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [id, load],
  );

  const rename = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    if (newName === null) return;
    setError(null);
    try {
      const renamed = await api.renameContainer(id, newName.trim());
      setNewName(null);
      // The page may have been opened by name, which no longer resolves.
      if (renamed.id !== id) navigate(`/containers/${renamed.id}`, { replace: true });
      else load();
    } catch (renameError) {
      setError((renameError as Error).message);
    }
  };

  if (loadError && !detail) return <div className="error">{t("Failed to load: {error}", { error: loadError })}</div>;
  if (!detail) return <div>{t("Loading…")}</div>;

  return (
    <div>
      <div className="crumb">
        <Link to="/containers">
          <ChevronLeft size={15} /> {t("Containers")}
        </Link>
      </div>
      <div className="row-between">
        <h1>
          {newName === null ? (
            <>
              {detail.name}{" "}
              <button
                type="button"
                className="secondary small icon-only"
                title={t("Rename")}
                aria-label={t("rename")}
                onClick={() => setNewName(detail.name)}
              >
                <Pencil size={14} />
              </button>
            </>
          ) : (
            <form className="button-row inline" style={{ display: "inline-flex" }} onSubmit={rename}>
              <input
                value={newName}
                autoFocus
                aria-label={t("New container name")}
                onChange={(event) => setNewName(event.target.value)}
              />
              <button type="submit" className="small" disabled={!newName.trim()}>
                {t("Rename")}
              </button>
              <button type="button" className="secondary small" onClick={() => setNewName(null)}>
                {t("Cancel")}
              </button>
              {detail.compose_service && (
                <span className="muted" style={{ fontSize: "0.8rem", fontWeight: "normal" }}>
                  {t("Compose restores its own name when it recreates the container.")}
                </span>
              )}
            </form>
          )}{" "}
          <span className={`badge ${detail.state}`}>
            <Circle size={8} fill="currentColor" /> {t(containerStateLabel(detail.state))}
          </span>
          <HealthBadge health={detail.health} />
        </h1>
        <div className="button-row inline">
          {containerActionsFor(detail.state).map((action) => {
            const Icon = CONTAINER_ACTION_ICONS[action];
            const label = t(CONTAINER_ACTION_LABELS[action]);
            return (
              <button
                key={action}
                type="button"
                className="secondary"
                disabled={busy !== null}
                onClick={() => runAction(action)}
              >
                <Icon size={15} /> {busy === action ? t("{action}…", { action: label }) : label}
              </button>
            );
          })}
          {user?.is_admin && detail.state === "running" && (
            <button
              type="button"
              className="secondary"
              title={t("Open a shell in this container")}
              onClick={() => setShowConsole(true)}
            >
              <SquareTerminal size={15} /> {t("console")}
            </button>
          )}
          <button type="button" className="secondary" onClick={load}>
            <RefreshCw size={15} /> {t("Refresh")}
          </button>
        </div>
      </div>
      <div className="muted">
        <code>
          <ImageName image={detail.image} version={detail.image_version} />
        </code>
        {project && (
          <>
            {" · "}
            {t("project")}{" "}
            <Link to={`/projects/${project.id}`}>{project.name}</Link>
            {detail.compose_service && ` / ${detail.compose_service}`}
          </>
        )}
        {liveStats && (
          <>
            {" · CPU "}
            {liveStats.cpu_percent.toFixed(1)}% · RAM {formatBytes(liveStats.memory_usage)} /{" "}
            {formatBytes(liveStats.memory_limit)}
          </>
        )}
      </div>
      {error && <div className="error">{error}</div>}

      <div className="tabs">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            className={tab === key ? "tab active" : "tab"}
            onClick={() =>
              setSearchParams(key === "overview" ? {} : { tab: key }, { replace: true })
            }
          >
            <Icon size={15} /> {t(label)}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab detail={detail} isAdmin={!!user?.is_admin} />}
      {tab === "logs" && <LogsTab id={detail.id} name={detail.name} />}
      {tab === "cves" && <CvesTab image={detail.image} />}
      {tab === "updates" && <UpdatesTab container={detail} project={project} />}

      {liveStats && tab === "overview" && (
        <section className="section">
          <h2>{t("Resources")}</h2>
          <ul className="fact-list">
            <li>
              <span>CPU</span>
              <span>
                {liveStats.cpu_percent.toFixed(1)}% <Meter percent={liveStats.cpu_percent} />
              </span>
            </li>
            <li>
              <span>{t("Memory")}</span>
              <span>
                {formatBytes(liveStats.memory_usage)} / {formatBytes(liveStats.memory_limit)}
                <Meter percent={liveStats.memory_percent} />
              </span>
            </li>
            <li>
              <span>{t("Network rx / tx")}</span>
              <span>
                {formatBytes(liveStats.network_rx)} / {formatBytes(liveStats.network_tx)}
              </span>
            </li>
            <li>
              <span>{t("Disk read / write")}</span>
              <span>
                {formatBytes(liveStats.block_read)} / {formatBytes(liveStats.block_write)}
              </span>
            </li>
            <li>
              <span>PIDs</span>
              <span>{liveStats.pids ?? "—"}</span>
            </li>
          </ul>
        </section>
      )}

      {showConsole && (
        <Suspense fallback={null}>
          <ContainerConsole
            containerId={detail.id}
            title={detail.name}
            onClose={() => setShowConsole(false)}
          />
        </Suspense>
      )}
    </div>
  );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv-grid">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

function OverviewTab({ detail, isAdmin }: { detail: ContainerDetailData; isAdmin: boolean }) {
  const t = useT();
  const ports = detail.ports.filter((port) => port.public_port);
  const labels = Object.entries(detail.labels).sort(([leftKey], [rightKey]) =>
    leftKey.localeCompare(rightKey),
  );

  return (
    <>
      <Facts
        rows={[
          [t("Status"), detail.status],
          [t("Created"), formatDate(detail.created_at)],
          [t("Started"), formatDate(detail.started_at)],
          [t("Finished"), formatDate(detail.finished_at)],
          [t("Exit code"), detail.exit_code ?? "—"],
          [t("Restart policy"), detail.restart_policy || "no"],
          [t("Restart count"), detail.restart_count],
          [t("Command"), detail.command ? <code>{detail.command.join(" ")}</code> : "—"],
          [t("Entrypoint"), detail.entrypoint ? <code>{detail.entrypoint.join(" ")}</code> : "—"],
          [t("Working dir"), detail.working_dir ?? "—"],
          [t("User"), detail.user ?? "—"],
          [t("Hostname"), detail.hostname ?? "—"],
          [t("Image ID"), detail.image_id ? <code>{detail.image_id.slice(0, 19)}</code> : "—"],
          [t("Container ID"), <code>{detail.id.slice(0, 12)}</code>],
          [
            t("Ports"),
            ports.length
              ? ports
                  .map(
                    (port) =>
                      `${port.host_ip ? `${port.host_ip}:` : ""}${port.public_port}→${port.private_port}/${port.protocol}`,
                  )
                  .join(", ")
              : "—",
          ],
        ]}
      />

      <section className="section">
        <h2>{t("Networks")}</h2>
        {detail.networks.length === 0 ? (
          <div className="empty">{t("No networks.")}</div>
        ) : (
          <table className="projects-table">
            <thead>
              <tr>
                <th>{t("Network")}</th>
                <th>{t("IP address")}</th>
                <th>{t("Gateway")}</th>
                <th>MAC</th>
              </tr>
            </thead>
            <tbody>
              {detail.networks.map((network) => (
                <tr key={network.name}>
                  <td className="row-name">{network.name}</td>
                  <td>{network.ip_address ?? "—"}</td>
                  <td className="muted">{network.gateway ?? "—"}</td>
                  <td className="muted">{network.mac_address ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="section">
        <h2>{t("Mounts")}</h2>
        {detail.mounts.length === 0 ? (
          <div className="empty">{t("No mounts.")}</div>
        ) : (
          <table className="projects-table">
            <thead>
              <tr>
                <th>{t("Type")}</th>
                <th>{t("Source")}</th>
                <th>{t("Destination")}</th>
                <th>{t("Access")}</th>
              </tr>
            </thead>
            <tbody>
              {detail.mounts.map((mount) => (
                <tr key={mount.destination}>
                  <td>
                    <span className="badge">{mount.type}</span>
                  </td>
                  <td>
                    <code>{mount.source ?? "—"}</code>
                  </td>
                  <td>
                    <code>{mount.destination}</code>
                  </td>
                  <td className="muted">{mount.rw ? t("read-write") : t("read-only")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="section">
        <h2>
          {t("Environment")}{" "}
          {!detail.env_revealed && (
            <span className="muted">{t("values hidden (admin only)")}</span>
          )}
        </h2>
        {detail.env.length === 0 ? (
          <div className="empty">{t("No environment variables.")}</div>
        ) : (
          <table className="projects-table">
            <tbody>
              {detail.env.map((variable) => (
                <tr key={variable.key}>
                  <td>
                    <code>{variable.key}</code>
                  </td>
                  <td className="break-all">
                    <code>{variable.value}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="section">
        <details>
          <summary>
            <strong>{t("Labels")}</strong> <span className="muted">({labels.length})</span>
          </summary>
          <table className="projects-table">
            <tbody>
              {labels.map(([key, value]) => (
                <tr key={key}>
                  <td>
                    <code>{key}</code>
                  </td>
                  <td className="break-all">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </section>

      {isAdmin && detail.raw && (
        <section className="section">
          <details>
            <summary>
              <strong>{t("Raw inspect JSON")}</strong>
            </summary>
            <pre className="raw-json">{JSON.stringify(detail.raw, null, 2)}</pre>
          </details>
        </section>
      )}
    </>
  );
}

function LogsTab({ id, name }: { id: string; name: string }) {
  const [filter, setFilter] = useState("");
  const t = useT();
  return (
    <>
      <div className="button-row">
        <input
          placeholder={t("Filter lines…")}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </div>
      <LogPanel
        inline
        title={name}
        url={`/api/logs/container/${id}?tail=200`}
        filter={filter}
      />
    </>
  );
}

function CvesTab({ image }: { image: string }) {
  const [history, setHistory] = useState<ScanSummary[] | null>(null);
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const t = useT();

  const openScan = useCallback((summary: ScanSummary): void => {
    api
      .getScan(summary.id)
      .then(setScan)
      .catch((scanError: Error) => setError(scanError.message));
  }, []);

  const load = useCallback((): void => {
    api
      .scanHistory(image)
      .then((pastScans) => {
        setHistory(pastScans);
        if (pastScans.length) openScan(pastScans[0]);
      })
      .catch((historyError: Error) => setError(historyError.message));
  }, [image, openScan]);

  const { jobs, start, dismiss, busy } = useJobs(load, setError);

  useEffect(load, [load]);

  return (
    <>
      <div className="row-between">
        <div className="muted">
          {scan && !scan.error ? (
            <>
              {fillElements(
                t("Scanned {date} — {critical} critical, {high} high, {medium} medium, {low} low", {
                  date: formatDate(scan.scanned_at),
                  medium: scan.medium,
                  low: scan.low,
                }),
                { critical: <strong>{scan.critical}</strong>, high: <strong>{scan.high}</strong> },
              )}
              {scan.fixable > 0 && ` · ${t("{count} fixable", { count: scan.fixable })}`}
            </>
          ) : history?.length === 0 ? (
            t("Image not scanned yet.")
          ) : null}
        </div>
        <button type="button" className="secondary" disabled={busy} onClick={() => start(() => api.scanImage(image))}>
          <ShieldCheck size={15} /> {history?.length ? t("Rescan") : t("Scan now")}
        </button>
      </div>
      <JobList jobs={jobs} onDismiss={dismiss} />
      {error && <div className="error">{error}</div>}

      {history === null ? (
        <div className="empty">{t("Loading…")}</div>
      ) : (
        scan && <ScanFindings key={scan.id} detail={scan} />
      )}

      {history && history.length > 1 && (
        <section className="section">
          <h2>{t("Scan history")}</h2>
          <table className="projects-table">
            <tbody>
              {history.map((pastScan) => (
                <tr key={pastScan.id} className={scan?.id === pastScan.id ? "selected" : undefined}>
                  <td>
                    <button type="button" className="linklike" onClick={() => openScan(pastScan)}>
                      {formatDate(pastScan.scanned_at)}
                    </button>
                  </td>
                  <td>
                    {pastScan.error ? (
                      <span className="muted">{t("failed")}</span>
                    ) : (
                      `${pastScan.critical}C · ${pastScan.high}H · ${pastScan.medium}M · ${pastScan.low}L`
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}

function UpdatesTab({
  container,
  project,
}: {
  container: ContainerDetailData;
  project: Project | null;
}) {
  const image = container.image;
  const [update, setUpdate] = useState<UpdateSummary | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const t = useT();

  const load = useCallback((): void => {
    api
      .listUpdates()
      .then((updateList) =>
        setUpdate(updateList.find((summary) => summary.image === image) ?? null),
      )
      .catch((loadError: Error) => setError(loadError.message));
  }, [image]);

  // A finished update recreated the container under a new id: follow it there.
  const onJobSettled = useCallback((): void => {
    load();
    api
      .listContainers()
      .then((containerList) => {
        const recreated = containerList.find((candidate) => candidate.name === container.name);
        if (recreated && recreated.id !== container.id) {
          navigate(`/containers/${recreated.id}?tab=updates`);
        }
      })
      .catch(() => undefined);
  }, [load, container.name, container.id, navigate]);

  const { jobs, track, start, dismiss, busy } = useJobs(onJobSettled, setError);

  useEffect(load, [load]);

  const outdated = hasUpdate(update);

  return (
    <>
      <div className="row-between">
        <div className="button-row inline">
          <UpdateBadge update={update ?? undefined} />
          <UpdateAction
            container={container}
            update={update ?? undefined}
            project={project}
            pending={busy}
            onJob={track}
            onError={setError}
          />
        </div>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => start(() => api.checkUpdates([image]))}
        >
          <ArrowUpCircle size={15} /> {t("Check now")}
        </button>
      </div>
      <JobList jobs={jobs} onDismiss={dismiss} />
      {error && <div className="error">{error}</div>}

      {update === undefined ? (
        <div className="empty">{t("Loading…")}</div>
      ) : update === null ? (
        <div className="empty">{t("No update check recorded for this image yet.")}</div>
      ) : (
        <Facts
          rows={[
            [t("Checked"), formatDate(update.checked_at)],
            [t("Local digest"), update.local_digest ? <code>{update.local_digest}</code> : "—"],
            [t("Remote digest"), update.remote_digest ? <code>{update.remote_digest}</code> : "—"],
            [t("Same tag rebuilt"), update.update_available ? t("yes — pull to update") : t("no")],
            [t("Newest tag"), update.newest_tag ?? "—"],
            [t("Newest in current major"), update.newest_same_major_tag ?? "—"],
            [t("Error"), update.error ?? update.tag_error ?? "—"],
          ]}
        />
      )}

      {outdated && (
        <div className="output" style={{ padding: "0.75rem" }}>
          {project ? (
            <>
              {update?.newest_tag
                ? t("Change the image tag in the compose file, then redeploy.")
                : t("Run pull, then up, on the stack to update.")}{" "}
              <Link to={`/projects/${project.id}`}>
                {t("Open project {name}", { name: project.name })}
              </Link>
            </>
          ) : (
            t("Container not managed by a known Compose project; recreate it with the new image.")
          )}
        </div>
      )}
    </>
  );
}
