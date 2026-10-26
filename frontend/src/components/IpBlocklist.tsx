import { CheckCircle2, CircleAlert, Save, Search, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { formatDate } from "../format";
import { useT } from "../i18n";
import { waitForJob } from "../stackActions";
import type { IpBlocklistCheck, IpBlocklistConfig, IpBlocklistRead } from "../types";

/**
 * Known bad IPs (FireHOL level1 by default), dropped by the host's nftables.
 * Saving stores the config; applying downloads the lists and loads them on the host.
 */
export default function IpBlocklist() {
  const t = useT();
  const [read, setRead] = useState<IpBlocklistRead | null>(null);
  const [draft, setDraft] = useState<IpBlocklistConfig | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [ip, setIp] = useState("");
  const [checked, setChecked] = useState<IpBlocklistCheck | string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    try {
      const current = await api.getBlocklist();
      setRead(current);
      setDraft(current.config);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!read || !draft) {
    return error ? <div className="error">{error}</div> : <div className="empty">{t("Loading…")}</div>;
  }
  const dirty = JSON.stringify(draft) !== JSON.stringify(read.config);

  function edit(patch: Partial<IpBlocklistConfig>): void {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setNotice(null);
  }

  async function saveAndApply(): Promise<void> {
    if (!draft) return;
    setBusy(t("Applying…"));
    setError(null);
    setNotice(null);
    try {
      await api.saveBlocklist(draft);
      const job = await waitForJob(await api.applyBlocklist());
      setNotice(job.message);
    } catch (applyError) {
      setError((applyError as Error).message);
    } finally {
      await load();
      setBusy(null);
    }
  }

  async function check(): Promise<void> {
    if (!ip.trim()) return;
    try {
      setChecked(await api.checkBlocklist(ip.trim()));
    } catch (checkError) {
      setChecked((checkError as Error).message);
    }
  }

  const { status, host } = read;
  return (
    <div className="subsection">
      <div className="row-between">
        <h3>{t("Known bad IPs")}</h3>
        <HostBadge active={host.active} enabled={read.config.enabled} dirty={dirty} />
      </div>
      <p className="muted">
        {t(
          "Ranges from public lists of known attackers, dropped by the host's firewall before they reach any container. DryDock owns the nftables table inet drydock_blocklist, reloads it every 24 hours and when it starts. Private ranges and the allowlist are never blocked.",
        )}
      </p>

      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(event) => edit({ enabled: event.target.checked })}
        />
        {t("Block known bad IPs")}
      </label>
      <div className="fail2ban-fields">
        <label className="field">
          {t("Lists (one URL per line)")}
          <textarea
            className="blocklist-sources"
            rows={Math.max(2, draft.sources.length)}
            value={draft.sources.join("\n")}
            onChange={(event) =>
              edit({ sources: event.target.value.split("\n").map((line) => line.trim()).filter(Boolean) })
            }
          />
        </label>
        <label className="field">
          {t("Allowlist file (never blocked)")}
          <input
            type="text"
            placeholder={t("none")}
            value={draft.allowlist_file}
            onChange={(event) => edit({ allowlist_file: event.target.value })}
          />
        </label>
        <label className="field">
          {t("Ignored IPs and networks")}
          <input
            type="text"
            value={draft.ignore_ips.join(" ")}
            onChange={(event) =>
              edit({ ignore_ips: event.target.value.split(/[\s,]+/).filter(Boolean) })
            }
          />
        </label>
      </div>

      {status && (
        <div className="blocklist-status muted">
          <div>
            {t("{entries} ranges loaded on {date}.", {
              entries: status.entries,
              date: formatDate(status.applied_at),
            })}{" "}
            {host.active && host.dropped !== null &&
              t("{count} packets dropped since.", { count: host.dropped })}
          </div>
          {status.sources.map((source) => (
            <div key={source.url}>
              <code>{source.url}</code>{" "}
              {t("{entries} ranges, downloaded {date}", {
                entries: source.entries,
                date: formatDate(source.fetched_at),
              })}
              {source.error && <span className="error-text"> · {source.error}</span>}
            </div>
          ))}
        </div>
      )}
      {host.error && <div className="error">{host.error}</div>}

      <div className="button-row">
        <button type="button" disabled={busy !== null} onClick={() => void saveAndApply()}>
          <Save size={15} /> {busy ?? t("Save & apply")}
        </button>
        {dirty && (
          <button type="button" className="secondary" onClick={() => setDraft(read.config)}>
            <Undo2 size={15} /> {t("Discard changes")}
          </button>
        )}
      </div>
      {notice && <div className="output ok padded">{notice}</div>}
      {error && <pre className="error">{error}</pre>}

      <form
        className="button-row blocklist-check"
        onSubmit={(event) => {
          event.preventDefault();
          void check();
        }}
      >
        <input
          type="text"
          placeholder={t("IP address")}
          value={ip}
          onChange={(event) => {
            setIp(event.target.value);
            setChecked(null);
          }}
        />
        <button type="submit" className="secondary" disabled={!status}>
          <Search size={15} /> {t("Check an IP")}
        </button>
        {checked !== null && <CheckResult result={checked} />}
      </form>
    </div>
  );
}

function HostBadge({
  active,
  enabled,
  dirty,
}: {
  active: boolean | null;
  enabled: boolean;
  dirty: boolean;
}) {
  const t = useT();
  if (dirty) return <span className="badge paused">{t("Unsaved changes")}</span>;
  if (active === null) return <span className="badge">{t("Host state unknown")}</span>;
  if (active === enabled) {
    return active ? (
      <span className="badge running">
        <CheckCircle2 size={12} /> {t("Active on the host")}
      </span>
    ) : (
      <span className="badge">{t("Off")}</span>
    );
  }
  return (
    <span className="badge paused">
      <CircleAlert size={12} /> {active ? t("Still loaded on the host") : t("Not loaded on the host")}
    </span>
  );
}

function CheckResult({ result }: { result: IpBlocklistCheck | string }) {
  const t = useT();
  if (typeof result === "string") return <span className="error-text">{result}</span>;
  if (result.blocked) {
    return (
      <span className="badge exited">{t("Blocked by {network}", { network: result.network ?? "" })}</span>
    );
  }
  if (result.allowed_by) {
    return (
      <span className="badge running">
        {t("Never blocked ({network})", { network: result.allowed_by })}
      </span>
    );
  }
  return <span className="badge running">{t("Not on the list")}</span>;
}
