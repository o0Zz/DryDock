import { RefreshCw, ShieldBan } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import JobList from "../components/JobList";
import { formatDate } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import type { Fail2banBan, Fail2banReport, HostUpdates } from "../types";

// Package lists older than this mean the host no longer runs `apt update`.
const STALE_LISTS_DAYS = 7;

function daysSince(value: string): number {
  return (Date.now() - new Date(value).getTime()) / 86_400_000;
}

function Updates({ updates }: { updates: HostUpdates | null }) {
  if (!updates) {
    return (
      <p className="muted">
        Never checked. Use “Check updates”, or wait for the scheduled update check.
      </p>
    );
  }
  if (updates.error) {
    return <div className="error">Last check failed: {updates.error}</div>;
  }
  if (!updates.supported) {
    return (
      <p className="muted">
        The host has no apt. Only Debian, Ubuntu and Raspberry Pi OS are supported.
      </p>
    );
  }
  const stale = updates.lists_updated_at && daysSince(updates.lists_updated_at) > STALE_LISTS_DAYS;
  return (
    <>
      <ul className="fact-list">
        <li>
          <span className="muted">Pending updates</span>
          <strong>
            {updates.upgradable}{" "}
            {updates.security > 0 && (
              <span className="badge sev-critical">{updates.security} security</span>
            )}
          </strong>
        </li>
        <li>
          <span className="muted">Reboot required</span>
          <strong>
            {updates.reboot_required ? <span className="badge sev-high">yes</span> : "no"}
          </strong>
        </li>
        <li>
          <span className="muted">Package lists refreshed</span>
          <strong>
            {formatDate(updates.lists_updated_at, "never")}
            {stale && <span className="stat-detail-warn"> · stale</span>}
          </strong>
        </li>
        <li>
          <span className="muted">Kernel</span>
          <strong>{updates.kernel ?? "—"}</strong>
        </li>
        <li>
          <span className="muted">Last check</span>
          <strong>{formatDate(updates.checked_at)}</strong>
        </li>
      </ul>
      {stale && (
        <p className="muted">
          The host has not run <code>apt update</code> for over {STALE_LISTS_DAYS} days, so this list
          may miss updates. Install <code>unattended-upgrades</code> to refresh it daily.
        </p>
      )}
      {updates.packages.length > 0 && (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Package</th>
              <th>Installed</th>
              <th>Available</th>
            </tr>
          </thead>
          <tbody>
            {updates.packages.map((pkg) => (
              <tr key={pkg.name}>
                <td>
                  {pkg.name} {pkg.security && <span className="badge sev-critical">security</span>}
                </td>
                <td className="muted">{pkg.current}</td>
                <td>{pkg.candidate}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function BanTable({ bans, empty }: { bans: Fail2banBan[]; empty: string }) {
  if (bans.length === 0) return <p className="muted">{empty}</p>;
  return (
    <table className="projects-table">
      <thead>
        <tr>
          <th>IP</th>
          <th>Jail</th>
          <th>Banned</th>
          <th>Until</th>
          <th>Times</th>
          <th>Log lines</th>
        </tr>
      </thead>
      <tbody>
        {bans.map((ban) => (
          <tr key={`${ban.jail}-${ban.ip}-${ban.banned_at}`}>
            <td>
              <code>{ban.ip}</code>
            </td>
            <td>{ban.jail}</td>
            <td className="muted">{formatDate(ban.banned_at)}</td>
            <td className="muted">{ban.expires_at ? formatDate(ban.expires_at) : "permanent"}</td>
            <td>{ban.ban_count}</td>
            <td>
              {ban.matches.length > 0 ? (
                <details>
                  <summary className="muted">{ban.matches.length} line(s)</summary>
                  <pre className="match-lines">{ban.matches.join("\n")}</pre>
                </details>
              ) : (
                "—"
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Fail2ban({ report }: { report: Fail2banReport }) {
  return (
    <>
      <p className="muted">
        History since {formatDate(report.history_since, "—")}. fail2ban keeps it for{" "}
        <code>dbpurgeage</code> (1 day by default).
      </p>
      <table className="projects-table">
        <thead>
          <tr>
            <th>Jail</th>
            <th>Active bans</th>
            <th>Bans in history</th>
            <th>Last ban</th>
          </tr>
        </thead>
        <tbody>
          {report.jails.map((jail) => (
            <tr key={jail.name}>
              <td>
                {jail.name} {!jail.enabled && <span className="badge">disabled</span>}
                {jail.enabled && jail.bans === 0 && (
                  <span
                    className="badge"
                    title="This jail has banned nobody. Check that its log path and filter match your logs."
                  >
                    no bans
                  </span>
                )}
              </td>
              <td>{jail.active_bans}</td>
              <td>{jail.bans}</td>
              <td className="muted">{formatDate(jail.last_ban_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {report.top_users.length > 0 && (
        <>
          <h3>User names tried on SSH</h3>
          <div className="button-row">
            {report.top_users.map((user) => (
              <span key={user.name} className="badge">
                {user.name} × {user.count}
              </span>
            ))}
          </div>
        </>
      )}

      <h3>Active bans ({report.active_bans.length})</h3>
      <BanTable bans={report.active_bans} empty="Nobody is banned right now." />

      <h3>Recent bans</h3>
      <BanTable bans={report.recent_bans} empty="No bans in fail2ban's history." />
    </>
  );
}

export default function Host() {
  const { user } = useAuth();
  const [updates, setUpdates] = useState<HostUpdates | null | undefined>(undefined);
  const [report, setReport] = useState<Fail2banReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fail2banError, setFail2banError] = useState<string | null>(null);

  const loadUpdates = useCallback((): void => {
    api
      .hostUpdates()
      .then(setUpdates)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  const loadFail2ban = useCallback((): void => {
    if (!user?.is_admin) return;
    setFail2banError(null);
    api
      .fail2ban()
      .then(setReport)
      .catch((loadError: Error) =>
        setFail2banError(
          loadError instanceof ApiError && loadError.status === 404
            ? `fail2ban was not found on the host (${loadError.message}). ` +
                "Set DRYDOCK_FAIL2BAN_DB if its database lives elsewhere."
            : loadError.message,
        ),
      );
  }, [user?.is_admin]);

  useEffect(() => {
    loadUpdates();
    loadFail2ban();
  }, [loadUpdates, loadFail2ban]);

  const { jobs, start, dismiss } = useJobs(loadUpdates, setError);
  const checkJobs = jobs.filter((job) => job.kind === "host_update_check");
  const checking = checkJobs.some(isActive);

  return (
    <div>
      <div className="row-between">
        <h1>Host</h1>
        <div className="button-row">
          <button type="button" disabled={checking} onClick={() => start(api.checkHostUpdates)}>
            <RefreshCw size={15} /> Check updates
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      <JobList jobs={checkJobs} onDismiss={dismiss} />

      <section className="section">
        <h2>OS updates</h2>
        {updates === undefined ? (
          <div className="empty">Loading…</div>
        ) : (
          <Updates updates={updates} />
        )}
      </section>

      {user?.is_admin && (
        <section className="section">
          <div className="row-between">
            <h2>
              <ShieldBan size={18} /> fail2ban
            </h2>
            <button type="button" className="secondary small" onClick={loadFail2ban}>
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
          {fail2banError ? (
            <div className="error">{fail2banError}</div>
          ) : report ? (
            <Fail2ban report={report} />
          ) : (
            <div className="empty">Loading…</div>
          )}
        </section>
      )}
    </div>
  );
}
