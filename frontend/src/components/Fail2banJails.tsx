import { CircleAlert, Copy, Pencil, Plus, RotateCcw, Save, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatDate } from "../format";
import { useT } from "../i18n";
import { waitForJob } from "../stackActions";
import type { Fail2banEdit, Fail2banJails as Jails, Fail2banPlan, Fail2banReport } from "../types";
import { PlanView, PROXY_LOG, ruleText, watches } from "./fail2banParts";

/**
 * The host's jails, one line each: what a jail reads, when it bans, and its bans. A jail
 * opens on its own page to edit; a new one starts from a template or a copy.
 */
export default function Fail2banJails({
  report,
  onApplied,
}: {
  /** Bans per jail, from fail2ban's database; null while loading or unreadable. */
  report: Fail2banReport | null;
  onApplied: () => void;
}) {
  const t = useT();
  const [data, setData] = useState<Jails | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // A reset of the default jail set and its plan, shown before it is applied.
  const [reset, setReset] = useState<{ edit: Fail2banEdit; plan: Fail2banPlan } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    try {
      setData(await api.fail2banJails());
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data) {
    return error ? <pre className="error">{error}</pre> : <div className="empty">{t("Loading…")}</div>;
  }

  // The default set goes where DryDock's jails already look, else the proxy's log.
  const logpath = data.jails.find((jail) => jail.managed && jail.logpath[0])?.logpath[0] ?? PROXY_LOG;

  async function planReset(): Promise<void> {
    setBusy(t("Reading the host…"));
    setError(null);
    setNotice(null);
    try {
      const edit = await api.fail2banDefaults({ ban_hook: "forward", logpath });
      setReset({ edit, plan: await api.planFail2ban(edit) });
    } catch (resetError) {
      setError((resetError as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function applyReset(): Promise<void> {
    if (!reset) return;
    setBusy(t("Applying…"));
    setError(null);
    try {
      await waitForJob(await api.applyFail2ban(reset.edit));
      setReset(null);
      await load();
      setNotice(t("Applied: fail2ban checked the config and reloaded."));
      onApplied();
    } catch (applyError) {
      setError((applyError as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="subsection">
      <div className="button-row">
        <Link className="button" to="/proxy/jails/new">
          <Plus size={15} /> {t("New jail")}
        </Link>
        <button
          type="button"
          className="secondary"
          title={t("Replaces every drydock-* jail with the default set for this log")}
          disabled={busy !== null}
          onClick={() => void planReset()}
        >
          <RotateCcw size={15} /> {t("Reset default jails")}
        </button>
      </div>

      {reset && (
        <div className="subsection">
          <div className="output padded">
            {t(
              "Every drydock-* jail is replaced by the default set (401, 403, scanners, bad bots, unknown host names).",
            )}
          </div>
          <PlanView plan={reset.plan} />
          <div className="button-row">
            <button type="button" disabled={busy !== null} onClick={() => void applyReset()}>
              <Save size={15} /> {busy ?? t("Apply")}
            </button>
            <button type="button" className="secondary" onClick={() => setReset(null)}>
              <X size={15} /> {t("Cancel")}
            </button>
          </div>
        </div>
      )}
      {notice && <div className="output ok padded">{notice}</div>}
      {error && <pre className="error">{error}</pre>}

      <table className="projects-table">
        <thead>
          <tr>
            <th>{t("Jail")}</th>
            <th>{t("Reads")}</th>
            <th>{t("Bans when")}</th>
            <th>{t("Banned now")}</th>
            <th>{t("Last ban")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.jails.map((jail) => {
            const stats = report?.jails.find((other) => other.name === jail.name);
            const reads = watches(jail);
            const path = `/proxy/jails/${encodeURIComponent(jail.name)}`;
            return (
              <tr key={jail.name}>
                <td>
                  <Link to={path}>{jail.name}</Link>{" "}
                  {!jail.enabled && <span className="badge">{t("Off")}</span>}
                  {jail.enabled && stats?.bans === 0 && (
                    <span
                      className="muted"
                      title={t(
                        "This jail has banned nobody. Check that its log path and filter match your logs.",
                      )}
                    >
                      <CircleAlert size={13} />
                    </span>
                  )}
                </td>
                <td title={reads.title}>
                  <code>{reads.label}</code>
                </td>
                <td className="muted">{ruleText(jail)}</td>
                <td>{stats?.active_bans ?? "—"}</td>
                <td className="muted">{formatDate(stats?.last_ban_at ?? null, "—")}</td>
                <td>
                  <div className="button-row inline">
                    <Link className="button secondary small" to={path}>
                      <Pencil size={13} /> {t("Edit")}
                    </Link>
                    <Link
                      className="button secondary small"
                      to={`/proxy/jails/new?from=${encodeURIComponent(jail.name)}`}
                    >
                      <Copy size={13} /> {t("Duplicate")}
                    </Link>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
