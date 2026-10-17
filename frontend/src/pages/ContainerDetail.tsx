import {
  ArrowUpCircle,
  ChevronLeft,
  Circle,
  Info,
  Play,
  RefreshCw,
  RotateCw,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  Square,
  SquareTerminal,
  type LucideIcon,
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import JobList from "../components/JobList";
import LogPanel from "../components/LogPanel";
import Meter, { formatBytes } from "../components/Meter";
import ScanFindings from "../components/ScanFindings";
import UpdateBadge from "../components/UpdateBadge";
import { useContainerStats } from "../hooks/useContainerStats";
import { useJobs } from "../hooks/useJobs";
import type {
  ContainerDetail as Detail,
  Job,
  Project,
  ScanDetail,
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

const TABS = [
  { key: "overview", label: "Overview", icon: Info },
  { key: "logs", label: "Logs", icon: ScrollText },
  { key: "cves", label: "CVEs", icon: ShieldAlert },
  { key: "updates", label: "Updates", icon: ArrowUpCircle },
] as const;
type Tab = (typeof TABS)[number]["key"];

// xterm.js is heavy; only load it when a console is opened.
const ContainerConsole = lazy(() => import("../components/ContainerConsole"));

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function ContainerDetail() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.some((t) => t.key === params.get("tab"))
    ? (params.get("tab") as Tab)
    : "overview";
  const { user } = useAuth();
  const stats = useContainerStats()[id];

  const [detail, setDetail] = useState<Detail | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [showConsole, setShowConsole] = useState(false);

  const load = useCallback(() => {
    api
      .inspectContainer(id)
      .then((d) => {
        setDetail(d);
        setLoadError(null);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, [id]);

  useEffect(() => {
    load();
    // The owning project gives a link back to the stack and its pull/redeploy actions.
    api
      .listProjects()
      .then((list) => setProject(list.find((p) => p.containers.some((c) => c.id === id)) ?? null))
      .catch(() => undefined);
  }, [id, load]);

  const runAction = useCallback(
    async (action: Action) => {
      setBusy(action);
      setError(null);
      try {
        await api.containerAction(id, action);
        load();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [id, load],
  );

  if (loadError && !detail) return <div className="error">Failed to load: {loadError}</div>;
  if (!detail) return <div>Loading…</div>;

  const live = stats;

  return (
    <div>
      <div className="crumb">
        <Link to="/containers">
          <ChevronLeft size={15} /> Containers
        </Link>
      </div>
      <div className="row-between">
        <h1>
          {detail.name}{" "}
          <span className={`badge ${detail.state}`}>
            <Circle size={8} fill="currentColor" /> {detail.state}
          </span>
          {detail.health && (
            <span className={`badge ${detail.health === "healthy" ? "running" : "paused"}`}>
              {detail.health}
            </span>
          )}
        </h1>
        <div className="button-row inline">
          {ACTIONS.map((a) => {
            const Icon = ACTION_ICONS[a];
            return (
              <button
                key={a}
                type="button"
                className="secondary"
                disabled={busy !== null}
                onClick={() => runAction(a)}
              >
                <Icon size={15} /> {busy === a ? `${a}…` : a}
              </button>
            );
          })}
          {user?.is_admin && detail.state === "running" && (
            <button
              type="button"
              className="secondary"
              title="Open a shell in this container"
              onClick={() => setShowConsole(true)}
            >
              <SquareTerminal size={15} /> console
            </button>
          )}
          <button type="button" className="secondary" onClick={load}>
            <RefreshCw size={15} /> Refresh
          </button>
        </div>
      </div>
      <div className="muted">
        <code>{detail.image}</code>
        {project && (
          <>
            {" · project "}
            <Link to={`/projects/${project.id}`}>{project.name}</Link>
            {detail.compose_service && ` / ${detail.compose_service}`}
          </>
        )}
        {live && (
          <>
            {" · CPU "}
            {live.cpu_percent.toFixed(1)}% · RAM {formatBytes(live.memory_usage)} /{" "}
            {formatBytes(live.memory_limit)}
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
            onClick={() => setParams(key === "overview" ? {} : { tab: key }, { replace: true })}
          >
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab detail={detail} isAdmin={!!user?.is_admin} />}
      {tab === "logs" && <LogsTab id={detail.id} name={detail.name} />}
      {tab === "cves" && <CvesTab image={detail.image} />}
      {tab === "updates" && <UpdatesTab image={detail.image} project={project} />}

      {live && tab === "overview" && (
        <section className="section">
          <h2>Resources</h2>
          <ul className="fact-list">
            <li>
              <span>CPU</span>
              <span>
                {live.cpu_percent.toFixed(1)}% <Meter percent={live.cpu_percent} />
              </span>
            </li>
            <li>
              <span>Memory</span>
              <span>
                {formatBytes(live.memory_usage)} / {formatBytes(live.memory_limit)}
                <Meter percent={live.memory_percent} />
              </span>
            </li>
            <li>
              <span>Network rx / tx</span>
              <span>
                {formatBytes(live.network_rx)} / {formatBytes(live.network_tx)}
              </span>
            </li>
            <li>
              <span>Disk read / write</span>
              <span>
                {formatBytes(live.block_read)} / {formatBytes(live.block_write)}
              </span>
            </li>
            <li>
              <span>PIDs</span>
              <span>{live.pids ?? "—"}</span>
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
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

function OverviewTab({ detail, isAdmin }: { detail: Detail; isAdmin: boolean }) {
  const ports = detail.ports.filter((p) => p.public_port);
  const labels = Object.entries(detail.labels).sort(([a], [b]) => a.localeCompare(b));

  return (
    <>
      <Facts
        rows={[
          ["Status", detail.status],
          ["Created", when(detail.created_at)],
          ["Started", when(detail.started_at)],
          ["Finished", when(detail.finished_at)],
          ["Exit code", detail.exit_code ?? "—"],
          ["Restart policy", detail.restart_policy || "no"],
          ["Restart count", detail.restart_count],
          ["Command", detail.command ? <code>{detail.command.join(" ")}</code> : "—"],
          ["Entrypoint", detail.entrypoint ? <code>{detail.entrypoint.join(" ")}</code> : "—"],
          ["Working dir", detail.working_dir ?? "—"],
          ["User", detail.user ?? "—"],
          ["Hostname", detail.hostname ?? "—"],
          ["Image ID", detail.image_id ? <code>{detail.image_id.slice(0, 19)}</code> : "—"],
          ["Container ID", <code>{detail.id.slice(0, 12)}</code>],
          [
            "Ports",
            ports.length
              ? ports
                  .map((p) => `${p.host_ip ? `${p.host_ip}:` : ""}${p.public_port}→${p.private_port}/${p.protocol}`)
                  .join(", ")
              : "—",
          ],
        ]}
      />

      <section className="section">
        <h2>Networks</h2>
        {detail.networks.length === 0 ? (
          <div className="empty">No networks.</div>
        ) : (
          <table className="projects-table">
            <thead>
              <tr>
                <th>Network</th>
                <th>IP address</th>
                <th>Gateway</th>
                <th>MAC</th>
              </tr>
            </thead>
            <tbody>
              {detail.networks.map((n) => (
                <tr key={n.name}>
                  <td>{n.name}</td>
                  <td>{n.ip_address ?? "—"}</td>
                  <td className="muted">{n.gateway ?? "—"}</td>
                  <td className="muted">{n.mac_address ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="section">
        <h2>Mounts</h2>
        {detail.mounts.length === 0 ? (
          <div className="empty">No mounts.</div>
        ) : (
          <table className="projects-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Source</th>
                <th>Destination</th>
                <th>Access</th>
              </tr>
            </thead>
            <tbody>
              {detail.mounts.map((m) => (
                <tr key={m.destination}>
                  <td>
                    <span className="badge">{m.type}</span>
                  </td>
                  <td>
                    <code>{m.source ?? "—"}</code>
                  </td>
                  <td>
                    <code>{m.destination}</code>
                  </td>
                  <td className="muted">{m.rw ? "read-write" : "read-only"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="section">
        <h2>
          Environment{" "}
          {!detail.env_revealed && <span className="muted">values hidden (admin only)</span>}
        </h2>
        {detail.env.length === 0 ? (
          <div className="empty">No environment variables.</div>
        ) : (
          <table className="projects-table">
            <tbody>
              {detail.env.map((e) => (
                <tr key={e.key}>
                  <td>
                    <code>{e.key}</code>
                  </td>
                  <td className="break-all">
                    <code>{e.value}</code>
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
            <strong>Labels</strong> <span className="muted">({labels.length})</span>
          </summary>
          <table className="projects-table">
            <tbody>
              {labels.map(([k, v]) => (
                <tr key={k}>
                  <td>
                    <code>{k}</code>
                  </td>
                  <td className="break-all">{v}</td>
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
              <strong>Raw inspect JSON</strong>
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
  return (
    <>
      <div className="button-row">
        <input
          placeholder="Filter lines…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
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

  const openScan = useCallback((summary: ScanSummary) => {
    api
      .getScan(summary.id)
      .then(setScan)
      .catch((e: Error) => setError(e.message));
  }, []);

  const load = useCallback(() => {
    api
      .scanHistory(image)
      .then((list) => {
        setHistory(list);
        if (list.length) openScan(list[0]);
      })
      .catch((e: Error) => setError(e.message));
  }, [image, openScan]);

  const { jobs, track, dismiss, busy } = useJobs(load);

  useEffect(load, [load]);

  const rescan = async () => {
    setError(null);
    try {
      track(await api.scanImage(image));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <div className="row-between">
        <div className="muted">
          {scan && !scan.error ? (
            <>
              Scanned {when(scan.scanned_at)} — <strong>{scan.critical}</strong> critical,{" "}
              <strong>{scan.high}</strong> high, {scan.medium} medium, {scan.low} low
              {scan.fixable > 0 && ` · ${scan.fixable} fixable`}
            </>
          ) : history?.length === 0 ? (
            "Image not scanned yet."
          ) : null}
        </div>
        <button type="button" className="secondary" disabled={busy} onClick={rescan}>
          <ShieldCheck size={15} /> {history?.length ? "Rescan" : "Scan now"}
        </button>
      </div>
      <JobList jobs={jobs} onDismiss={dismiss} />
      {error && <div className="error">{error}</div>}

      {history === null ? (
        <div className="empty">Loading…</div>
      ) : (
        scan && <ScanFindings key={scan.id} detail={scan} />
      )}

      {history && history.length > 1 && (
        <section className="section">
          <h2>Scan history</h2>
          <table className="projects-table">
            <tbody>
              {history.map((h) => (
                <tr key={h.id} className={scan?.id === h.id ? "selected" : undefined}>
                  <td>
                    <button type="button" className="linklike" onClick={() => openScan(h)}>
                      {when(h.scanned_at)}
                    </button>
                  </td>
                  <td>
                    {h.error ? (
                      <span className="muted">failed</span>
                    ) : (
                      `${h.critical}C · ${h.high}H · ${h.medium}M · ${h.low}L`
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

function UpdatesTab({ image, project }: { image: string; project: Project | null }) {
  const [update, setUpdate] = useState<UpdateSummary | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listUpdates()
      .then((list) => setUpdate(list.find((u) => u.image === image) ?? null))
      .catch((e: Error) => setError(e.message));
  }, [image]);

  const { jobs, track, dismiss, busy } = useJobs(load);

  useEffect(load, [load]);

  const check = async (fn: () => Promise<Job>) => {
    setError(null);
    try {
      track(await fn());
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const outdated = !!update && (update.update_available || !!update.newest_tag);

  return (
    <>
      <div className="row-between">
        <div>
          <UpdateBadge update={update ?? undefined} />
        </div>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => check(() => api.checkUpdates([image]))}
        >
          <ArrowUpCircle size={15} /> Check now
        </button>
      </div>
      <JobList jobs={jobs} onDismiss={dismiss} />
      {error && <div className="error">{error}</div>}

      {update === undefined ? (
        <div className="empty">Loading…</div>
      ) : update === null ? (
        <div className="empty">No update check recorded for this image yet.</div>
      ) : (
        <Facts
          rows={[
            ["Checked", when(update.checked_at)],
            ["Local digest", update.local_digest ? <code>{update.local_digest}</code> : "—"],
            ["Remote digest", update.remote_digest ? <code>{update.remote_digest}</code> : "—"],
            ["Same tag rebuilt", update.update_available ? "yes — pull to update" : "no"],
            ["Newest tag", update.newest_tag ?? "—"],
            ["Newest in current major", update.newest_same_major_tag ?? "—"],
            ["Error", update.error ?? update.tag_error ?? "—"],
          ]}
        />
      )}

      {outdated && (
        <div className="output" style={{ padding: "0.75rem" }}>
          {project ? (
            <>
              {update?.newest_tag
                ? "Change the image tag in the compose file, then redeploy. "
                : "Run pull, then up, on the stack to update. "}
              <Link to={`/projects/${project.id}`}>Open project {project.name}</Link>
            </>
          ) : (
            "Container not managed by a known Compose project; recreate it with the new image."
          )}
        </div>
      )}
    </>
  );
}
