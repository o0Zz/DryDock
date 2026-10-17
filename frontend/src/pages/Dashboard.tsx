import {
  ArrowUpCircle,
  Boxes,
  Container as ContainerIcon,
  HardDrive,
  Layers,
  ShieldAlert,
  ShieldQuestion,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatDate } from "../format";
import type { DashboardStats } from "../types";

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
  tone?: "danger" | "warn" | "ok";
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

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .dashboard()
      .then(setStats)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  if (error) return <div className="error">Failed to load dashboard: {error}</div>;
  if (!stats) return <div>Loadingâ€¦</div>;

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
              {stats.containers_unhealthy > 0 && (
                <span className="stat-detail-warn"> · {stats.containers_unhealthy} unhealthy</span>
              )}
            </>
          }
          tone={stats.containers_unhealthy > 0 ? "warn" : "ok"}
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
