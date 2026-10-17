import {
  ArrowUpCircle,
  Boxes,
  Container as ContainerIcon,
  HardDrive,
  Layers,
  ShieldAlert,
  ShieldQuestion,
  Square,
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
  tone,
  to,
}: {
  icon: ReactNode;
  value: number | string;
  label: string;
  tone?: "danger" | "warn" | "ok";
  to?: string;
}) {
  const body = (
    <div className={`stat${tone ? ` stat-${tone}` : ""}`}>
      <div className="stat-icon">{icon}</div>
      <div>
        <div className="stat-value">{value}</div>
        <div className="stat-label">{label}</div>
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

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .dashboard()
      .then(setStats)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="error">Failed to load dashboard: {error}</div>;
  if (!stats) return <div>Loading…</div>;

  return (
    <div>
      <h1>Dashboard</h1>

      {stats.docker_error && (
        <div className="error">
          Docker is unreachable, so container and volume counts are unavailable:{" "}
          {stats.docker_error}
        </div>
      )}

      <div className="stat-grid">
        <Stat
          icon={<ContainerIcon size={22} />}
          value={stats.containers_running}
          label="Containers running"
          tone="ok"
          to="/containers"
        />
        <Stat
          icon={<Square size={22} />}
          value={stats.containers_stopped}
          label="Containers stopped"
          to="/containers"
        />
        <Stat
          icon={<Boxes size={22} />}
          value={stats.projects}
          label="Compose projects"
          to="/projects"
        />
        <Stat icon={<Layers size={22} />} value={stats.services} label="Services defined" />
        <Stat
          icon={<ShieldAlert size={22} />}
          value={stats.images_critical}
          label="Images with critical CVEs"
          tone={stats.images_critical > 0 ? "danger" : undefined}
          to="/images"
        />
        <Stat
          icon={<ShieldAlert size={22} />}
          value={stats.images_high}
          label="Images with high CVEs"
          tone={stats.images_high > 0 ? "warn" : undefined}
          to="/images"
        />
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
          <li>
            <span className="muted">Open critical / high findings</span>
            <strong>
              {stats.critical_total} / {stats.high_total}
            </strong>
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
