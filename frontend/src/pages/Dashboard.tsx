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
import type { DashboardStats, HostUsage } from "../types";

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

/** Amber from `warn`, red from `danger`. */
function toneFor(value: number, warn: number, danger: number): Tone {
  if (value >= danger) return "danger";
  if (value >= warn) return "warn";
  return "ok";
}

function Meter({
  label,
  value,
  percent,
  tone,
  detail,
}: {
  label: string;
  value: string;
  percent: number;
  tone: Tone;
  detail?: string;
}) {
  return (
    <div className={`meter meter-${tone}`}>
      <div className="meter-head">
        <span className="muted">{label}</span>
        <strong>{value}</strong>
      </div>
      <div className="meter-bar">
        <div className="meter-fill" style={{ width: `${Math.min(Math.max(percent, 0), 100)}%` }} />
      </div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

// The Raspberry Pi firmware starts throttling at 80 °C.
const TEMP_WARN_C = 70;
const TEMP_DANGER_C = 80;

function HostMeters({ usage, cpus }: { usage: HostUsage | null; cpus: number | null }) {
  if (!usage) return <p className="muted">Loading host load…</p>;
  const { cpu_percent, load_1m, memory_total, memory_used, temperature_c } = usage;
  const meters: ReactNode[] = [];
  if (cpu_percent !== null) {
    meters.push(
      <Meter
        key="cpu"
        label="CPU"
        value={`${cpu_percent.toFixed(0)} %`}
        percent={cpu_percent}
        tone={toneFor(cpu_percent, 80, 95)}
        detail={
          load_1m !== null
            ? `Load ${load_1m.toFixed(2)}${cpus ? ` on ${cpus} CPUs` : ""}`
            : undefined
        }
      />,
    );
  }
  if (memory_total && memory_used !== null) {
    const percent = (100 * memory_used) / memory_total;
    meters.push(
      <Meter
        key="memory"
        label="Memory"
        value={`${percent.toFixed(0)} %`}
        percent={percent}
        tone={toneFor(percent, 80, 95)}
        detail={`${formatBytes(memory_used)} of ${formatBytes(memory_total)} used`}
      />,
    );
  }
  if (temperature_c !== null) {
    meters.push(
      <Meter
        key="temperature"
        label="CPU temperature"
        value={`${temperature_c.toFixed(1)} °C`}
        percent={temperature_c}
        tone={toneFor(temperature_c, TEMP_WARN_C, TEMP_DANGER_C)}
        detail={temperature_c >= TEMP_DANGER_C ? "Hot enough to throttle" : undefined}
      />,
    );
  }
  if (meters.length === 0) {
    return <p className="muted">Live host load is not available on this host.</p>;
  }
  return <div className="meter-grid">{meters}</div>;
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
  const host = stats.host;

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
        <HostMeters usage={usage} cpus={host?.cpus ?? null} />
        {host && (
          <ul className="fact-list host-facts">
            <li>
              <span className="muted">Operating system</span>
              <strong>{host.os ?? "—"}</strong>
            </li>
            <li>
              <span className="muted">Kernel / architecture</span>
              <strong>
                {host.kernel ?? "—"} / {host.architecture ?? "—"}
              </strong>
            </li>
            <li>
              <span className="muted">Docker</span>
              <strong>{host.docker_version ?? "—"}</strong>
            </li>
            <li>
              <span className="muted">CPUs / memory</span>
              <strong>
                {host.cpus ?? "—"} / {host.memory_total ? formatBytes(host.memory_total) : "—"}
              </strong>
            </li>
            {usage?.uptime_seconds != null && (
              <li>
                <span className="muted">Uptime</span>
                <strong>{formatDuration(usage.uptime_seconds)}</strong>
              </li>
            )}
          </ul>
        )}
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
