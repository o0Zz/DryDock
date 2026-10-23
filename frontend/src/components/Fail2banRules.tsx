import { CheckCircle2, CircleAlert, FlaskConical, Plus, Save, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { msg, useT } from "../i18n";
import { waitForJob } from "../stackActions";
import type {
  Fail2banConfig,
  Fail2banJailConfig,
  Fail2banRule,
  Fail2banTestResult,
} from "../types";

const RULES: { id: Fail2banRule; label: string; hint: string }[] = [
  { id: "auth", label: msg("Failed logins"), hint: msg("401 answers") },
  { id: "forbidden", label: msg("Refused"), hint: msg("403 answers, e.g. the private allowlist") },
  { id: "botsearch", label: msg("Scanners"), hint: msg("404 on paths like /wp-login.php or /.env") },
  { id: "badbots", label: msg("Bad bots"), hint: msg("known bad user agents") },
  { id: "custom", label: msg("Custom"), hint: msg("your own failregex") },
];

const NEW_JAIL: Fail2banJailConfig = {
  name: "",
  enabled: true,
  rule: "auth",
  failregex: "",
  maxretry: 5,
  findtime: 600,
  bantime: 86400,
};

/**
 * The fail2ban jails DryDock writes on the host, against the proxy's access log.
 * Saving stores them; applying writes them and reloads fail2ban.
 */
export default function Fail2banRules({ onApplied }: { onApplied: () => void }) {
  const t = useT();
  const [saved, setSaved] = useState<Fail2banConfig | null>(null);
  const [draft, setDraft] = useState<Fail2banConfig | null>(null);
  const [applied, setApplied] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<number, Fail2banTestResult | string>>({});

  const load = useCallback(async (): Promise<void> => {
    try {
      const read = await api.getFail2banConfig();
      setSaved(read.config);
      setDraft(read.config);
      setApplied(read.applied);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!draft || !saved) {
    return error ? <div className="error">{error}</div> : <div className="empty">{t("Loading…")}</div>;
  }
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  function edit(patch: Partial<Fail2banConfig>): void {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setNotice(null);
  }

  function editJail(index: number, patch: Partial<Fail2banJailConfig>): void {
    if (!draft) return;
    edit({ jails: draft.jails.map((jail, at) => (at === index ? { ...jail, ...patch } : jail)) });
    setTests(({ [index]: _dropped, ...rest }) => rest);
  }

  async function saveAndApply(): Promise<void> {
    if (!draft) return;
    setBusy(t("Applying…"));
    setError(null);
    setNotice(null);
    try {
      const read = await api.saveFail2banConfig(draft);
      setSaved(read.config);
      setDraft(read.config);
      await waitForJob(await api.applyFail2banConfig());
      setApplied(true);
      setNotice(t("Applied: fail2ban reloaded with these jails."));
      onApplied();
    } catch (applyError) {
      setError((applyError as Error).message);
      setApplied((await api.getFail2banConfig().catch(() => null))?.applied ?? null);
    } finally {
      setBusy(null);
    }
  }

  async function test(index: number): Promise<void> {
    if (!draft) return;
    setBusy(t("Testing…"));
    try {
      const result = await api.testFail2banJail(draft, draft.jails[index]);
      setTests((current) => ({ ...current, [index]: result }));
    } catch (testError) {
      setTests((current) => ({ ...current, [index]: (testError as Error).message }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="subsection">
      <div className="row-between">
        <h3>{t("Proxy jails managed by DryDock")}</h3>
        <AppliedBadge applied={applied} dirty={dirty} />
      </div>
      <p className="muted">
        {t(
          "DryDock writes /etc/fail2ban/jail.d/drydock.local and one filter per jail, and never touches the rest of fail2ban. The rules read your proxy's access log, whatever the proxy.",
        )}
      </p>

      <div className="fail2ban-fields">
        <label className="field">
          {t("Access log on the host")}
          <input
            type="text"
            value={draft.log_path}
            onChange={(event) => edit({ log_path: event.target.value })}
          />
        </label>
        <label className="field">
          {t("Log format")}
          <select
            value={draft.log_format}
            onChange={(event) => edit({ log_format: event.target.value as "text" | "json" })}
          >
            <option value="text">{t("Text line (Traefik, nginx / SWAG)")}</option>
            <option value="json">{t("JSON (Caddy)")}</option>
          </select>
        </label>
        <label className="field">
          {t("Allowlist file (never banned)")}
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
        <label className="field">
          {t("Where bans apply")}
          <select
            value={draft.ban_hook}
            onChange={(event) => edit({ ban_hook: event.target.value as "forward" | "input" })}
          >
            <option value="forward">{t("Forward: the proxy's ports are published by Docker")}</option>
            <option value="input">{t("Input: the proxy runs on the host network")}</option>
          </select>
        </label>
      </div>

      <div className="table-scroll">
        <table className="projects-table fail2ban-jails">
          <thead>
            <tr>
              <th>{t("On")}</th>
              <th>{t("Name")}</th>
              <th>{t("Rule")}</th>
              <th title={t("Failures before a ban")}>{t("Max retries")}</th>
              <th title={t("Failures count within this window")}>{t("Window (min)")}</th>
              <th>{t("Ban (h)")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {draft.jails.map((jail, index) => (
              <JailRows
                key={index}
                jail={jail}
                result={tests[index]}
                busy={busy !== null}
                onChange={(patch) => editJail(index, patch)}
                onTest={() => void test(index)}
                onRemove={() => {
                  edit({ jails: draft.jails.filter((_, at) => at !== index) });
                  setTests({});
                }}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="button-row">
        <button
          type="button"
          className="secondary"
          onClick={() => edit({ jails: [...draft.jails, { ...NEW_JAIL, name: `jail-${draft.jails.length + 1}` }] })}
        >
          <Plus size={15} /> {t("Add a jail")}
        </button>
        <button type="button" disabled={busy !== null} onClick={() => void saveAndApply()}>
          <Save size={15} /> {busy ?? t("Save & apply")}
        </button>
        {dirty && (
          <button type="button" className="secondary" onClick={() => setDraft(saved)}>
            <Undo2 size={15} /> {t("Discard changes")}
          </button>
        )}
      </div>
      {notice && <div className="output ok padded">{notice}</div>}
      {error && <pre className="error">{error}</pre>}
    </div>
  );
}

function AppliedBadge({ applied, dirty }: { applied: boolean | null; dirty: boolean }) {
  const t = useT();
  if (dirty) return <span className="badge paused">{t("Unsaved changes")}</span>;
  if (applied === null) return <span className="badge">{t("Host state unknown")}</span>;
  return applied ? (
    <span className="badge running">
      <CheckCircle2 size={12} /> {t("Applied on the host")}
    </span>
  ) : (
    <span className="badge paused">
      <CircleAlert size={12} /> {t("Not applied yet")}
    </span>
  );
}

function JailRows({
  jail,
  result,
  busy,
  onChange,
  onTest,
  onRemove,
}: {
  jail: Fail2banJailConfig;
  result: Fail2banTestResult | string | undefined;
  busy: boolean;
  onChange: (patch: Partial<Fail2banJailConfig>) => void;
  onTest: () => void;
  onRemove: () => void;
}) {
  const t = useT();
  const rule = RULES.find((candidate) => candidate.id === jail.rule);
  let extra: ReactNode = null;
  if (jail.rule === "custom") {
    extra = (
      <input
        type="text"
        className="fail2ban-regex"
        placeholder={'^<HOST> \\S+ \\S+ \\[\\] "[A-Z]+ [^"]*" 418 '}
        value={jail.failregex}
        onChange={(event) => onChange({ failregex: event.target.value })}
      />
    );
  }

  return (
    <>
      <tr>
        <td>
          <input
            type="checkbox"
            checked={jail.enabled}
            onChange={(event) => onChange({ enabled: event.target.checked })}
          />
        </td>
        <td>
          <input
            type="text"
            className="fail2ban-name"
            value={jail.name}
            onChange={(event) => onChange({ name: event.target.value.toLowerCase() })}
          />
        </td>
        <td>
          <select
            value={jail.rule}
            title={rule ? t(rule.hint) : undefined}
            onChange={(event) => onChange({ rule: event.target.value as Fail2banRule })}
          >
            {RULES.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {t(candidate.label)}
              </option>
            ))}
          </select>
        </td>
        <td>
          <NumberInput value={jail.maxretry} onChange={(maxretry) => onChange({ maxretry })} />
        </td>
        <td>
          <NumberInput
            value={jail.findtime / 60}
            onChange={(minutes) => onChange({ findtime: Math.round(minutes * 60) })}
          />
        </td>
        <td>
          <NumberInput
            value={jail.bantime / 3600}
            step={0.5}
            onChange={(hours) => onChange({ bantime: Math.round(hours * 3600) })}
          />
        </td>
        <td>
          <div className="button-row inline">
            <button
              type="button"
              className="secondary small"
              disabled={busy}
              title={t("Run this rule over the end of the access log")}
              onClick={onTest}
            >
              <FlaskConical size={13} /> {t("Test")}
            </button>
            <button
              type="button"
              className="secondary small icon-only"
              title={t("Remove")}
              onClick={onRemove}
            >
              <Trash2 size={13} />
            </button>
          </div>
        </td>
      </tr>
      {(extra || result !== undefined) && (
        <tr className="fail2ban-detail">
          <td colSpan={7}>
            {extra}
            {typeof result === "string" && <pre className="error">{result}</pre>}
            {result !== undefined && typeof result !== "string" && <TestResult result={result} />}
          </td>
        </tr>
      )}
    </>
  );
}

function NumberInput({
  value,
  step = 1,
  onChange,
}: {
  value: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <input
      type="number"
      className="fail2ban-number"
      min={step}
      step={step}
      value={value}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  );
}

function TestResult({ result }: { result: Fail2banTestResult }) {
  const t = useT();
  return (
    <div className="fail2ban-test">
      <div>
        {t("{matched} of the last {lines} lines match.", {
          matched: result.matched,
          lines: result.lines,
        })}{" "}
        {result.top_ips.length > 0 &&
          result.top_ips
            .map((hit) => `${hit.ip} ×${hit.count}`)
            .join(", ")}
      </div>
      {result.samples.length > 0 && <pre className="diff">{result.samples.join("\n")}</pre>}
    </div>
  );
}
