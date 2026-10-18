import { Copy, RefreshCw, ShieldBan } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import JobList from "../components/JobList";
import SortHeader from "../components/SortHeader";
import { formatDate } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import { useSort } from "../hooks/useSort";
import { translate, useT } from "../i18n";
import type { Fail2banBan, Fail2banReport, HostPackage, HostUpdates } from "../types";

// Package lists older than this mean the host no longer runs `apt update`.
const STALE_LISTS_DAYS = 7;

function daysSince(value: string): number {
  return (Date.now() - new Date(value).getTime()) / 86_400_000;
}

// Raspberry Pi's documented upgrade. Interactive: apt lists what it removes before asking.
const UPGRADE_COMMAND = "sudo apt update && sudo apt full-upgrade";
const AUTO_UPGRADES_COMMAND =
  "sudo apt install unattended-upgrades\nsudo dpkg-reconfigure -plow unattended-upgrades";

/** A shell command to run on the host, with a copy button. DryDock never runs it. */
function Command({ command }: { command: string }) {
  const t = useT();
  return (
    <div className="output" style={{ padding: "0.75rem" }}>
      <div className="row-between">
        <pre style={{ margin: 0 }}>{command}</pre>
        <button
          type="button"
          className="secondary small"
          onClick={() => navigator.clipboard?.writeText(command)}
        >
          <Copy size={14} /> {t("Copy")}
        </button>
      </div>
    </div>
  );
}

function Updates({ updates }: { updates: HostUpdates | null }) {
  const t = useT();
  if (!updates) {
    return (
      <p className="muted">
        {t("Never checked. Use “Check updates”, or wait for the scheduled update check.")}
      </p>
    );
  }
  if (updates.error) {
    return <div className="error">{t("Last check failed: {error}", { error: updates.error })}</div>;
  }
  if (!updates.supported) {
    return (
      <p className="muted">
        {t("The host has no apt. Only Debian, Ubuntu and Raspberry Pi OS are supported.")}
      </p>
    );
  }
  const stale = updates.lists_updated_at && daysSince(updates.lists_updated_at) > STALE_LISTS_DAYS;
  return (
    <>
      <ul className="fact-list">
        <li>
          <span className="muted">{t("Pending updates")}</span>
          <strong>
            {updates.upgradable}{" "}
            {updates.security > 0 && (
              <span className="badge sev-critical">
                {t("{count} security", { count: updates.security })}
              </span>
            )}
          </strong>
        </li>
        <li>
          <span className="muted">{t("Reboot required")}</span>
          <strong>
            {updates.reboot_required ? (
              <span className="badge sev-high">{t("yes")}</span>
            ) : (
              t("no")
            )}
          </strong>
        </li>
        <li>
          <span className="muted">{t("Package lists refreshed")}</span>
          <strong>
            {formatDate(updates.lists_updated_at, t("never"))}
            {stale && <span className="stat-detail-warn"> · {t("stale")}</span>}
          </strong>
        </li>
        {updates.auto_upgrades !== null && (
          <li>
            <span className="muted">{t("Automatic security updates")}</span>
            <strong>
              {updates.auto_upgrades ? (
                t("on")
              ) : (
                <span className="badge sev-high">{t("off")}</span>
              )}
            </strong>
          </li>
        )}
        <li>
          <span className="muted">{t("Kernel")}</span>
          <strong>{updates.kernel ?? "—"}</strong>
        </li>
        <li>
          <span className="muted">{t("Last check")}</span>
          <strong>{formatDate(updates.checked_at)}</strong>
        </li>
      </ul>
      {stale && (
        <p className="muted">
          {t("The host has not run")} <code>apt update</code>{" "}
          {t("for over {days} days, so this list may miss updates. Install", {
            days: STALE_LISTS_DAYS,
          })}{" "}
          <code>unattended-upgrades</code> {t("to refresh it daily.")}
        </p>
      )}
      {updates.upgradable > 0 && (
        <>
          <p className="muted">{t("To install them, run this on the host:")}</p>
          <Command command={UPGRADE_COMMAND} />
        </>
      )}
      {updates.reboot_required && (
        <>
          <p className="muted">{t("Then reboot the host to load the new kernel and libraries:")}</p>
          <Command command="sudo reboot" />
        </>
      )}
      {updates.auto_upgrades === false && (
        <>
          <p className="muted">
            {t(
              "Automatic updates are off. To install security updates every day, turn on unattended-upgrades:",
            )}
          </p>
          <Command command={AUTO_UPGRADES_COMMAND} />
        </>
      )}
      {updates.packages.length > 0 && <PackageTable packages={updates.packages} />}
    </>
  );
}

function PackageTable({ packages }: { packages: HostPackage[] }) {
  const t = useT();
  // No default: the server lists security updates first.
  const sorting = useSort(packages, {
    storageKey: "drydock.sort.host-packages",
    columns: {
      name: (pkg) => pkg.name,
    },
  });
  return (
    <table className="projects-table">
      <thead>
        <tr>
          <SortHeader sorting={sorting} column="name">
            {t("Package")}
          </SortHeader>
          <th>{t("Installed")}</th>
          <th>{t("Available")}</th>
        </tr>
      </thead>
      <tbody>
        {sorting.rows.map((pkg) => (
          <tr key={pkg.name}>
            <td>
              <span className="row-name">{pkg.name}</span>{" "}
              {pkg.security && <span className="badge sev-critical">{t("security")}</span>}
            </td>
            <td className="muted">{pkg.current}</td>
            <td>{pkg.candidate}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BanTable({ bans, empty }: { bans: Fail2banBan[]; empty: string }) {
  const t = useT();
  // No default: the server lists the newest bans first.
  const sorting = useSort(bans, {
    storageKey: "drydock.sort.bans",
    columns: {
      banned: (ban) => Date.parse(ban.banned_at),
      ip: (ban) => ban.ip,
      jail: (ban) => ban.jail,
      // A permanent ban outlasts every dated one.
      until: (ban) => (ban.expires_at ? Date.parse(ban.expires_at) : Number.MAX_SAFE_INTEGER),
      times: (ban) => ban.ban_count,
    },
    descendingFirst: ["banned", "until", "times"],
  });
  if (bans.length === 0) return <p className="muted">{empty}</p>;
  return (
    <table className="projects-table">
      <thead>
        <tr>
          <SortHeader sorting={sorting} column="ip">
            IP
          </SortHeader>
          <SortHeader sorting={sorting} column="jail">
            {t("Jail")}
          </SortHeader>
          <SortHeader sorting={sorting} column="banned">
            {t("Banned")}
          </SortHeader>
          <SortHeader sorting={sorting} column="until">
            {t("Until")}
          </SortHeader>
          <SortHeader sorting={sorting} column="times">
            {t("Times")}
          </SortHeader>
          <th>{t("Log lines")}</th>
        </tr>
      </thead>
      <tbody>
        {sorting.rows.map((ban) => (
          <tr key={`${ban.jail}-${ban.ip}-${ban.banned_at}`}>
            <td>
              <code>{ban.ip}</code>
            </td>
            <td>{ban.jail}</td>
            <td className="muted">{formatDate(ban.banned_at)}</td>
            <td className="muted">{ban.expires_at ? formatDate(ban.expires_at) : t("permanent")}</td>
            <td>{ban.ban_count}</td>
            <td>
              {ban.matches.length > 0 ? (
                <details>
                  <summary className="muted">
                    {t("{count} line(s)", { count: ban.matches.length })}
                  </summary>
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
  const t = useT();
  return (
    <>
      <p className="muted">
        {t("History since {date}. fail2ban keeps it for", {
          date: formatDate(report.history_since, "—"),
        })}{" "}
        <code>dbpurgeage</code> {t("(1 day by default).")}
      </p>
      <table className="projects-table">
        <thead>
          <tr>
            <th>{t("Jail")}</th>
            <th>{t("Active bans")}</th>
            <th>{t("Bans in history")}</th>
            <th>{t("Last ban")}</th>
          </tr>
        </thead>
        <tbody>
          {report.jails.map((jail) => (
            <tr key={jail.name}>
              <td>
                <span className="row-name">{jail.name}</span>{" "}
                {!jail.enabled && <span className="badge">{t("disabled")}</span>}
                {jail.enabled && jail.bans === 0 && (
                  <span
                    className="badge"
                    title={t(
                      "This jail has banned nobody. Check that its log path and filter match your logs.",
                    )}
                  >
                    {t("no bans")}
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
          <h3>{t("User names tried on SSH")}</h3>
          <div className="button-row">
            {report.top_users.map((user) => (
              <span key={user.name} className="badge">
                {user.name} × {user.count}
              </span>
            ))}
          </div>
        </>
      )}

      <h3>{t("Active bans ({count})", { count: report.active_bans.length })}</h3>
      <BanTable bans={report.active_bans} empty={t("Nobody is banned right now.")} />

      <h3>{t("Recent bans")}</h3>
      <BanTable bans={report.recent_bans} empty={t("No bans in fail2ban's history.")} />
    </>
  );
}

export default function Host() {
  const t = useT();
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
            ? translate(
                "fail2ban was not found on the host ({error}). Set DRYDOCK_FAIL2BAN_DB if its database lives elsewhere.",
                { error: loadError.message },
              )
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
        <h1>{t("Host")}</h1>
        <div className="button-row">
          <button type="button" disabled={checking} onClick={() => start(api.checkHostUpdates)}>
            <RefreshCw size={15} /> {t("Check updates")}
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      <JobList jobs={checkJobs} onDismiss={dismiss} />

      <section className="section">
        <h2>{t("OS updates")}</h2>
        {updates === undefined ? (
          <div className="empty">{t("Loading…")}</div>
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
              <RefreshCw size={14} /> {t("Refresh")}
            </button>
          </div>
          {fail2banError ? (
            <div className="error">{fail2banError}</div>
          ) : report ? (
            <Fail2ban report={report} />
          ) : (
            <div className="empty">{t("Loading…")}</div>
          )}
        </section>
      )}
    </div>
  );
}
