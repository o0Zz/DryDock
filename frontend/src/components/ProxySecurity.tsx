import { RefreshCw, ShieldBan } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { formatDate } from "../format";
import { useSort } from "../hooks/useSort";
import { translate, useT } from "../i18n";
import type { Fail2banBan, Fail2banReport } from "../types";
import Fail2banRules from "./Fail2banRules";
import IpBlocklist from "./IpBlocklist";
import SortHeader from "./SortHeader";

/**
 * The Proxy page's Security tab (admin only): who fail2ban banned, the jails that
 * watch the proxy's access log, and the IP blocklist. fail2ban and nftables run on
 * the host; DryDock reads their state and writes their config.
 */
export default function ProxySecurity() {
  const t = useT();
  const [report, setReport] = useState<Fail2banReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((): void => {
    setError(null);
    api
      .fail2ban()
      .then(setReport)
      .catch((loadError: Error) =>
        setError(
          loadError instanceof ApiError && loadError.status === 404
            ? translate(
                "fail2ban was not found on the host ({error}). Set DRYDOCK_FAIL2BAN_DB if its database lives elsewhere.",
                { error: loadError.message },
              )
            : loadError.message,
        ),
      );
  }, []);

  useEffect(load, [load]);

  return (
    <section className="section">
      <div className="row-between">
        <h2>
          <ShieldBan size={18} /> fail2ban
        </h2>
        <button type="button" className="secondary small" onClick={load}>
          <RefreshCw size={14} /> {t("Refresh")}
        </button>
      </div>
      {error ? (
        <div className="error">{error}</div>
      ) : report ? (
        <Fail2ban report={report} />
      ) : (
        <div className="empty">{t("Loading…")}</div>
      )}
      <Fail2banRules onApplied={load} />
      <IpBlocklist />
    </section>
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
            <td className="muted">{formatDate(ban.expires_at, t("permanent"))}</td>
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
          date: formatDate(report.history_since),
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
