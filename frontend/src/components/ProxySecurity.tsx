import { ShieldBan } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { formatDate } from "../format";
import { useSort } from "../hooks/useSort";
import { translate, useT } from "../i18n";
import type { Fail2banBan, Fail2banReport } from "../types";
import Fail2banJails from "./Fail2banJails";
import IpBlocklist from "./IpBlocklist";
import SortHeader from "./SortHeader";

/**
 * The Proxy page's Security tab (admin only): fail2ban's jails, the known bad IPs, then
 * who is banned now. fail2ban and nftables run on the host; DryDock reads their state
 * and writes their config. A jail opens on its own page to edit.
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

  // Laid out like the Routes tab: a line of context, then one section per part. The
  // page's Reload button remounts this tab, so it has no refresh button of its own.
  return (
    <>
      <p className="muted">
        {t(
          "What protects the services you expose. fail2ban bans the IPs that misbehave in the proxy's access log; the blocklist drops known bad IPs before they connect. Both run on the host: DryDock reads their state and writes their config.",
        )}
      </p>
      <section className="section">
        <h2>
          <ShieldBan size={18} /> fail2ban
        </h2>
        {error && <div className="error">{error}</div>}
        <Fail2banJails report={report} onApplied={load} />
      </section>
      <IpBlocklist />
      {report && <Bans report={report} />}
    </>
  );
}

function Bans({ report }: { report: Fail2banReport }) {
  const t = useT();
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const bans = needle
    ? report.active_bans.filter(
        (ban) => ban.ip.includes(needle) || ban.jail.toLowerCase().includes(needle),
      )
    : report.active_bans;
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

  return (
    <section className="section">
      <h2>{t("Active bans ({count})", { count: report.active_bans.length })}</h2>
      {report.active_bans.length === 0 ? (
        <p className="muted">{t("Nobody is banned right now.")}</p>
      ) : (
        <>
          <div className="button-row">
            <input
              placeholder={t("Filter by IP or jail…")}
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
          </div>
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
                <BanRow key={`${ban.jail}-${ban.ip}-${ban.banned_at}`} ban={ban} />
              ))}
            </tbody>
          </table>
        </>
      )}
      {report.top_users.length > 0 && (
        <details className="subsection">
          <summary className="muted">{t("User names tried on SSH")}</summary>
          <div className="button-row">
            {report.top_users.map((user) => (
              <span key={user.name} className="badge">
                {user.name} × {user.count}
              </span>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function BanRow({ ban }: { ban: Fail2banBan }) {
  const t = useT();
  return (
    <tr>
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
  );
}
