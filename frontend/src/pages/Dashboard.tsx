import {
  ArrowUpCircle,
  Boxes,
  Container as ContainerIcon,
  HardDrive,
  HeartPulse,
  Layers,
  ShieldAlert,
  ShieldQuestion,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatBytes, formatDate, formatDuration } from "../format";
import { useHostUsage } from "../hooks/useHostUsage";
import type { DashboardStats, HostInfo, HostUsage } from "../types";

type Tone = "danger" | "warn" | "ok";

function Stat({
  icon,
  value,
  label,
  detail,
  tone,
  to,
}: {
  icon: ReactNode;
  value: number | string;
  label: string;
  detail?: ReactNode;
  tone?: Tone;
  to?: string;
}) {
  const body = (
    <div className={`stat${tone ? ` stat-${tone}` : ""}`}>
      <div className="stat-icon">{icon}</div>
      <div>
        <div className="stat-value">{value}</div>
        <div className="stat-label">{label}</div>
        {detail && <div className="stat-detail">{detail}</div>}
      </div>
    </div>
  );
  return to ? (
    <Link to={to} className="stat-link">
      {body}
    </Link>
  ) : (
    body
  );
}

function cveDetail(images: number, scanned: number): string {
  if (scanned === 0) return "No image scanned yet";
  return `in ${images} of ${scanned} scanned image${scanned === 1 ? "" : "s"}`;
}

// The Raspberry Pi firmware starts throttling at 80 °C.
const THROTTLE_TEMP_C = 80;

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li>
      <span className="muted">{label}</span>
      <strong>{children}</strong>
    </li>
  );
}

/** Live load first (refreshed every few seconds), then the static `docker info` facts.
 * Rows whose value the host does not expose are left out. */
function HostFacts({ host, usage }: { host: HostInfo | null; usage: HostUsage | null }) {
  const cpu = usage?.cpu_percent ?? null;
  const load = usage?.load_1m ?? null;
  const used = usage?.memory_used ?? null;
  const total = usage?.memory_total ?? null;
  const temperature = usage?.temperature_c ?? null;
  const uptime = usage?.uptime_seconds ?? null;
  return (
    <ul className="fact-list">
      {cpu !== null && (
        <Fact label="CPU usage">
          {cpu.toFixed(0)} %{load !== null && ` (load ${load.toFixed(2)})`}
        </Fact>
      )}
      {used !== null && total && (
        <Fact label="Memory used">
          {formatBytes(used)} of {formatBytes(total)} ({((100 * used) / total).toFixed(0)} %)
        </Fact>
      )}
      {temperature !== null && (
        <Fact label="CPU temperature">
          {temperature.toFixed(1)} °C
          {temperature >= THROTTLE_TEMP_C && (
            <span className="stat-detail-warn"> · throttling</span>
          )}
        </Fact>
      )}
      {uptime !== null && <Fact label="Uptime">{formatDuration(uptime)}</Fact>}
      {host && (
        <>
          <Fact label="Operating system">{host.os ?? "—"}</Fact>
          <Fact label="Kernel / architecture">
            {host.kernel ?? "—"} / {host.architecture ?? "—"}
          </Fact>
          <Fact label="Docker">{host.docker_version ?? "—"}</Fact>
          <Fact label="CPUs / memory">
            {host.cpus ?? "—"} / {host.memory_total ? formatBytes(host.memory_total) : "—"}
          </Fact>
        </>
      )}
    </ul>
  );
}

function Attention({ stats }: { stats: DashboardStats }) {
  const { unhealthy_containers, most_vulnerable, updates } = stats;
  if (!unhealthy_containers.length && !most_vulnerable.length && !updates.length) {
    return <p className="muted">Nothing needs attention.</p>;
  }
  const moreUpdates = stats.updates_available - updates.length;
  return (
    <div className="attention-grid">
      {unhealthy_containers.length > 0 && (
        <div className="attention-card">
          <h3>
            <HeartPulse size={15} /> Unhealthy containers
          </h3>
          <ul className="attention-list">
            {unhealthy_containers.map((container) => (
              <li key={container.id}>
                <Link to={`/containers/${container.id}`}>{container.name}</Link>
                <span className="muted">{container.status}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {most_vulnerable.length > 0 && (
        <div className="attention-card">
          <h3>
            <ShieldAlert size={15} /> Most vulnerable images
          </h3>
          <ul className="attention-list">
            {most_vulnerable.map((risk) => (
              <li key={risk.image}>
                <Link to="/images" title={risk.image}>
                  {risk.image}
                </Link>
                <span>
                  {risk.critical > 0 && (
                    <span className="badge sev-critical">{risk.critical} critical</span>
                  )}{" "}
                  {risk.high > 0 && <span className="badge sev-high">{risk.high} high</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {updates.length > 0 && (
        <div className="attention-card">
          <h3>
            <ArrowUpCircle size={15} /> Updates available
          </h3>
          <ul className="attention-list">
            {updates.map((update) => (
              <li key={update.image}>
                <Link to="/images" title={update.image}>
                  {update.image}
                </Link>
                <span className="muted">
                  {update.newest_tag ? `→ ${update.newest_tag}` : "rebuilt"}
                </span>
              </li>
            ))}
          </ul>
          {moreUpdates > 0 && (
            <Link to="/images" className="muted">
              and {moreUpdates} more
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const usage = useHostUsage();

  useEffect(() => {
    api
      .dashboard()
      .then(setStats)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  if (error) return <div className="error">Failed to load dashboard: {error}</div>;
  if (!stats) return <div>Loading…</div>;

  const unhealthy = stats.unhealthy_containers.length;

  return (
    <div>
      <h1>Dashboard</h1>

      {stats.docker_error && (
        <div className="error">
          Docker is unreachable, so container and volume counts are unavailable:{" "}
          {stats.docker_error}
        </div>
      )}

      <div className="stat-grid stat-grid-hero">
        <Stat
          icon={<ContainerIcon size={26} />}
          value={stats.containers_running}
          label="Containers running"
          detail={
            <>
              {stats.containers_stopped} stopped
              {unhealthy > 0 && <span className="stat-detail-warn"> · {unhealthy} unhealthy</span>}
            </>
          }
          tone={unhealthy > 0 ? "warn" : "ok"}
          to="/containers"
        />
        <Stat
          icon={<ShieldAlert size={26} />}
          value={stats.critical_total}
          label="Critical CVEs"
          detail={cveDetail(stats.images_critical, stats.images_scanned)}
          tone={stats.critical_total > 0 ? "danger" : "ok"}
          to="/images"
        />
        <Stat
          icon={<ShieldAlert size={26} />}
          value={stats.high_total}
          label="High CVEs"
          detail={cveDetail(stats.images_high, stats.images_scanned)}
          tone={stats.high_total > 0 ? "warn" : "ok"}
          to="/images"
        />
      </div>

      <div className="stat-grid">
        <Stat
          icon={<Boxes size={22} />}
          value={stats.projects}
          label="Compose projects"
          to="/projects"
        />
        <Stat icon={<Layers size={22} />} value={stats.services} label="Services defined" />
        <Stat
          icon={<ArrowUpCircle size={22} />}
          value={stats.updates_available}
          label="Images with updates"
          tone={stats.updates_available > 0 ? "warn" : undefined}
          to="/images"
        />
        <Stat
          icon={<ShieldQuestion size={22} />}
          value={`${stats.images_scanned}/${stats.images_tracked}`}
          label="Images scanned"
          to="/images"
        />
        <Stat icon={<HardDrive size={22} />} value={stats.volumes} label="Volumes" to="/volumes" />
      </div>

      <section className="section">
        <h2>Needs attention</h2>
        <Attention stats={stats} />
      </section>

      <section className="section">
        <h2>Host</h2>
        <HostFacts host={stats.host} usage={usage} />
      </section>

      <section className="section">
        <h2>Security</h2>
        <ul className="fact-list">
          <li>
            <span className="muted">Last CVE scan</span>
            <strong>{formatDate(stats.last_scan_at, "never")}</strong>
          </li>
          <li>
            <span className="muted">Last update check</span>
            <strong>{formatDate(stats.last_update_check_at, "never")}</strong>
          </li>
        </ul>
        <div className="button-row">
          <Link to="/images">
            <button type="button" className="secondary">
              <Layers size={15} /> Images
            </button>
          </Link>
        </div>
      </section>
    </div>
  );
}
