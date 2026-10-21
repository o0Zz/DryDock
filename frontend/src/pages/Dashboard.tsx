import {
  ArrowUpCircle,
  Boxes,
  Container as ContainerIcon,
  HardDrive,
  HeartPulse,
  Layers,
  ShieldAlert,
  ShieldQuestion,
  Server,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import Fact from "../components/Fact";
import { formatBytes, formatDate, formatDuration } from "../format";
import { useHostUsage } from "../hooks/useHostUsage";
import { useT, type Translate } from "../i18n";
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

function cveDetail(t: Translate, images: number, scanned: number): string {
  if (scanned === 0) return t("No image scanned yet");
  return scanned === 1
    ? t("in {images} of 1 scanned image", { images })
    : t("in {images} of {scanned} scanned images", { images, scanned });
}

// The Raspberry Pi firmware starts throttling at 80 °C.
const THROTTLE_TEMP_C = 80;

/** Live load first (refreshed every few seconds), then the static `docker info` facts.
 * Rows whose value the host does not expose are left out. */
function HostFacts({ host, usage }: { host: HostInfo | null; usage: HostUsage | null }) {
  const t = useT();
  const cpu = usage?.cpu_percent ?? null;
  const load = usage?.load_1m ?? null;
  const used = usage?.memory_used ?? null;
  const total = usage?.memory_total ?? null;
  const temperature = usage?.temperature_c ?? null;
  const uptime = usage?.uptime_seconds ?? null;
  return (
    <ul className="fact-list">
      {cpu !== null && (
        <Fact label={t("CPU usage")}>
          {cpu.toFixed(0)} %
          {load !== null && ` (${t("load {load}", { load: load.toFixed(2) })})`}
        </Fact>
      )}
      {used !== null && total && (
        <Fact label={t("Memory used")}>
          {t("{used} of {total} ({percent} %)", {
            used: formatBytes(used),
            total: formatBytes(total),
            percent: ((100 * used) / total).toFixed(0),
          })}
        </Fact>
      )}
      {temperature !== null && (
        <Fact label={t("CPU temperature")}>
          {temperature.toFixed(1)} °C
          {temperature >= THROTTLE_TEMP_C && (
            <span className="stat-detail-warn"> · {t("throttling")}</span>
          )}
        </Fact>
      )}
      {uptime !== null && <Fact label={t("Uptime")}>{formatDuration(uptime)}</Fact>}
      {host && (
        <>
          <Fact label={t("Operating system")}>{host.os ?? "—"}</Fact>
          <Fact label={t("Kernel / architecture")}>
            {host.kernel ?? "—"} / {host.architecture ?? "—"}
          </Fact>
          <Fact label="Docker">{host.docker_version ?? "—"}</Fact>
          <Fact label={t("CPUs / memory")}>
            {host.cpus ?? "—"} / {host.memory_total ? formatBytes(host.memory_total) : "—"}
          </Fact>
        </>
      )}
    </ul>
  );
}

function Attention({ stats }: { stats: DashboardStats }) {
  const t = useT();
  const { unhealthy_containers, most_vulnerable, updates } = stats;
  const hostNeedsAttention = stats.host_security_updates > 0 || stats.host_reboot_required;
  if (
    !unhealthy_containers.length &&
    !most_vulnerable.length &&
    !updates.length &&
    !hostNeedsAttention
  ) {
    return <p className="muted">{t("Nothing needs attention.")}</p>;
  }
  const moreUpdates = stats.updates_available - updates.length;
  return (
    <div className="attention-grid">
      {unhealthy_containers.length > 0 && (
        <div className="attention-card">
          <h3>
            <HeartPulse size={15} /> {t("Unhealthy containers")}
          </h3>
          <ul className="attention-list">
            {unhealthy_containers.map((container) => (
              <li key={container.id}>
                <Link to={`/containers/${container.id}?tab=logs`} title={t("Show the logs")}>
                  {container.name}
                </Link>
                <span className="muted">{container.status}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {most_vulnerable.length > 0 && (
        <div className="attention-card">
          <h3>
            <ShieldAlert size={15} /> {t("Most vulnerable images")}
          </h3>
          <ul className="attention-list">
            {most_vulnerable.map((risk) => (
              <li key={risk.image}>
                <Link to="/images" title={risk.image}>
                  {risk.image}
                </Link>
                <span>
                  {risk.critical > 0 && (
                    <span className="badge sev-critical">
                      {risk.critical === 1
                        ? t("1 critical")
                        : t("{count} critical", { count: risk.critical })}
                    </span>
                  )}{" "}
                  {risk.high > 0 && (
                    <span className="badge sev-high">
                      {risk.high === 1 ? t("1 high") : t("{count} high", { count: risk.high })}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {updates.length > 0 && (
        <div className="attention-card">
          <h3>
            <ArrowUpCircle size={15} /> {t("Updates available")}
          </h3>
          <ul className="attention-list">
            {updates.map((update) => (
              <li key={update.image}>
                <Link to="/images" title={update.image}>
                  {update.image}
                </Link>
                <span className="muted">
                  {update.newest_tag ? `→ ${update.newest_tag}` : t("rebuilt")}
                </span>
              </li>
            ))}
          </ul>
          {moreUpdates > 0 && (
            <Link to="/images" className="muted">
              {t("and {count} more", { count: moreUpdates })}
            </Link>
          )}
        </div>
      )}
      {hostNeedsAttention && (
        <div className="attention-card">
          <h3>
            <Server size={15} /> {t("Host")}
          </h3>
          <ul className="attention-list">
            {stats.host_security_updates > 0 && (
              <li>
                <Link to="/host">{t("Security updates")}</Link>
                <span className="badge sev-critical">{stats.host_security_updates}</span>
              </li>
            )}
            {stats.host_reboot_required && (
              <li>
                <Link to="/host">{t("Reboot required")}</Link>
                <span className="muted">{t("new kernel or libraries")}</span>
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const t = useT();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const usage = useHostUsage();

  useEffect(() => {
    api
      .dashboard()
      .then(setStats)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  if (error) return <div className="error">{t("Failed to load dashboard: {error}", { error })}</div>;
  if (!stats) return <div>{t("Loading…")}</div>;

  const unhealthy = stats.unhealthy_containers.length;

  return (
    <div>
      <h1>{t("Dashboard")}</h1>

      {stats.docker_error && (
        <div className="error">
          {t("Docker is unreachable, so container and volume counts are unavailable: {error}", {
            error: stats.docker_error,
          })}
        </div>
      )}

      <div className="stat-grid stat-grid-hero">
        <Stat
          icon={<ContainerIcon size={26} />}
          value={stats.containers_running}
          label={t("Containers running")}
          detail={
            <>
              {stats.containers_stopped === 1
                ? t("1 stopped")
                : t("{count} stopped", { count: stats.containers_stopped })}
              {unhealthy > 0 && (
                <span className="stat-detail-warn">
                  {" "}
                  · {t("{count} unhealthy", { count: unhealthy })}
                </span>
              )}
            </>
          }
          tone={unhealthy > 0 ? "warn" : "ok"}
          to="/containers"
        />
        <Stat
          icon={<ShieldAlert size={26} />}
          value={stats.critical_total}
          label={t("Critical CVEs")}
          detail={cveDetail(t, stats.images_critical, stats.images_scanned)}
          tone={stats.critical_total > 0 ? "danger" : "ok"}
          to="/images"
        />
        <Stat
          icon={<ShieldAlert size={26} />}
          value={stats.high_total}
          label={t("High CVEs")}
          detail={cveDetail(t, stats.images_high, stats.images_scanned)}
          tone={stats.high_total > 0 ? "warn" : "ok"}
          to="/images"
        />
      </div>

      <div className="stat-grid">
        <Stat
          icon={<Boxes size={22} />}
          value={stats.projects}
          label={t("Compose projects")}
          to="/projects"
        />
        <Stat icon={<Layers size={22} />} value={stats.services} label={t("Services defined")} />
        <Stat
          icon={<ArrowUpCircle size={22} />}
          value={stats.updates_available}
          label={t("Images with updates")}
          tone={stats.updates_available > 0 ? "warn" : undefined}
          to="/images"
        />
        <Stat
          icon={<ShieldQuestion size={22} />}
          value={`${stats.images_scanned}/${stats.images_tracked}`}
          label={t("Images scanned")}
          to="/images"
        />
        <Stat icon={<HardDrive size={22} />} value={stats.volumes} label={t("Volumes")} to="/volumes" />
        <Stat
          icon={<Server size={22} />}
          value={stats.host_updates ?? "—"}
          label={t("Host OS updates")}
          detail={
            stats.host_security_updates > 0 ? (
              <span className="stat-detail-warn">
                {t("{count} security", { count: stats.host_security_updates })}
              </span>
            ) : stats.host_updates === null ? (
              t("Not checked")
            ) : undefined
          }
          tone={
            stats.host_security_updates > 0
              ? "danger"
              : stats.host_updates
                ? "warn"
                : undefined
          }
          to="/host"
        />
      </div>

      <section className="section">
        <h2>{t("Needs attention")}</h2>
        <Attention stats={stats} />
      </section>

      <section className="section">
        <h2>{t("Host")}</h2>
        <HostFacts host={stats.host} usage={usage} />
      </section>

      <section className="section">
        <h2>{t("Security")}</h2>
        <ul className="fact-list">
          <Fact label={t("Last CVE scan")}>{formatDate(stats.last_scan_at, t("never"))}</Fact>
          <Fact label={t("Last update check")}>
            {formatDate(stats.last_update_check_at, t("never"))}
          </Fact>
          <Fact label={t("Last host update check")}>
            {formatDate(stats.last_host_update_check_at, t("never"))}
          </Fact>
        </ul>
        <div className="button-row">
          <Link to="/images">
            <button type="button" className="secondary">
              <Layers size={15} /> {t("Images")}
            </button>
          </Link>
        </div>
      </section>
    </div>
  );
}
