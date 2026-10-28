import { FileCode, FlaskConical, Plus, RotateCcw, Save, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { formatDate } from "../format";
import { msg, useT } from "../i18n";
import { waitForJob } from "../stackActions";
import type {
  Fail2banEdit,
  Fail2banJailChange,
  Fail2banJailConfig,
  Fail2banJails as Jails,
  Fail2banNewJail,
  Fail2banPlan,
  Fail2banReport,
  Fail2banTestResult,
} from "../types";
import DiffView from "./DiffView";

const TEMPLATE_LABELS: Record<string, string> = {
  auth: msg("Failed logins (401)"),
  forbidden: msg("Refused (403)"),
  botsearch: msg("Scanners (404 on /wp-login.php, /.env...)"),
  badbots: msg("Bad bots (user agent)"),
  custom: msg("Empty"),
};
const PROXY_LOG = "/data/proxy/logs/access.log";

/** A jail as edited: the multi-line fields are textarea text, one item per line. */
interface Row {
  name: string;
  /** As read from the host; null for a jail not created yet. */
  original: Fail2banJailConfig | null;
  create: Fail2banNewJail | null;
  deleted: boolean;
  enabled: boolean;
  logpath: string;
  failregex: string;
  ignoreregex: string;
  maxretry: string;
  findtime: string;
  bantime: string;
}

type TextField = "logpath" | "failregex" | "ignoreregex" | "maxretry" | "findtime" | "bantime";
const LIST_FIELDS = ["logpath", "failregex", "ignoreregex"] as const;
const VALUE_FIELDS = ["maxretry", "findtime", "bantime"] as const;

function toRow(jail: Fail2banJailConfig): Row {
  return {
    name: jail.name,
    original: jail,
    create: null,
    deleted: false,
    enabled: jail.enabled,
    logpath: jail.logpath.join("\n"),
    failregex: jail.failregex.join("\n"),
    ignoreregex: jail.ignoreregex.join("\n"),
    maxretry: jail.maxretry,
    findtime: jail.findtime,
    bantime: jail.bantime,
  };
}

function lines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/** What the server must change, from the rows as edited. */
function changesOf(rows: Row[]): Fail2banJailChange[] {
  const changes: Fail2banJailChange[] = [];
  for (const row of rows) {
    const { original } = row;
    if (!original) {
      if (row.deleted || !row.create) continue;
      changes.push({
        name: row.name,
        create: row.create,
        enabled: row.enabled,
        ...Object.fromEntries(LIST_FIELDS.map((key) => [key, lines(row[key])])),
        ...Object.fromEntries(VALUE_FIELDS.map((key) => [key, row[key].trim()])),
      });
      continue;
    }
    if (row.deleted) {
      changes.push({ name: row.name, delete: true });
      continue;
    }
    const change: Fail2banJailChange = { name: row.name };
    if (row.enabled !== original.enabled) change.enabled = row.enabled;
    for (const key of LIST_FIELDS) {
      if (lines(row[key]).join("\n") !== original[key].join("\n")) change[key] = lines(row[key]);
    }
    for (const key of VALUE_FIELDS) {
      if (row[key].trim() !== original[key]) change[key] = row[key].trim();
    }
    if (Object.keys(change).length > 1) changes.push(change);
  }
  return changes;
}

/**
 * Every fail2ban jail of the host in one table: its log, its regexes, its limits and its
 * bans. Values are the host's own; an edit goes where the value lives (see
 * fail2ban_jails on the server), and applying checks the config before reloading.
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
  const [rows, setRows] = useState<Row[]>([]);
  const [plan, setPlan] = useState<Fail2banPlan | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, Fail2banTestResult | string>>({});

  const load = useCallback(async (): Promise<void> => {
    try {
      const read = await api.fail2banJails();
      setData(read);
      setRows(read.jails.map(toRow));
      setPlan(null);
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
  const changes = changesOf(rows);

  function edit(name: string, patch: Partial<Row>): void {
    setRows((current) => current.map((row) => (row.name === name ? { ...row, ...patch } : row)));
    setPlan(null);
    setNotice(null);
  }

  async function preview(request: Fail2banEdit): Promise<void> {
    setBusy(t("Reading the host…"));
    setError(null);
    try {
      setPlan(await api.planFail2ban(request));
    } catch (planError) {
      setError((planError as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function apply(request: Fail2banEdit): Promise<void> {
    setBusy(t("Applying…"));
    setError(null);
    setNotice(null);
    try {
      await waitForJob(await api.applyFail2ban(request));
      setNotice(t("Applied: fail2ban checked the config and reloaded."));
      await load();
      onApplied();
    } catch (applyError) {
      setError((applyError as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function test(row: Row): Promise<void> {
    setBusy(t("Testing…"));
    try {
      const result = await api.testFail2ban({
        logpath: lines(row.logpath)[0] ?? "",
        failregex: lines(row.failregex),
        ignoreregex: lines(row.ignoreregex),
        filter: row.original?.filter ?? null,
        template: row.create?.template ?? null,
        log_format: row.create?.log_format ?? "text",
      });
      setTests((current) => ({ ...current, [row.name]: result }));
    } catch (testError) {
      setTests((current) => ({ ...current, [row.name]: (testError as Error).message }));
    } finally {
      setBusy(null);
    }
  }

  function add(name: string, create: Fail2banNewJail, logpath: string): void {
    const regex = data?.templates[create.template]?.failregex[create.log_format] ?? "";
    setRows((current) => [
      ...current,
      {
        name,
        original: null,
        create,
        deleted: false,
        enabled: true,
        logpath,
        failregex: regex,
        ignoreregex: "",
        maxretry: "5",
        findtime: "600",
        bantime: "86400",
      },
    ]);
    setPlan(null);
  }

  return (
    <div className="subsection">
      <p className="muted">
        {t(
          "Every jail of the host, read from /etc/fail2ban. An edit goes where the value lives: a .local file is changed in place; a value from a package .conf file goes to its .local twin, since apt replaces the .conf files. Jails DryDock creates get their own jail.d/<name>.local and filter.d/<name>.conf.",
        )}
      </p>
      {data.legacy && (
        <div className="output padded">
          {t("Jails from an older DryDock are all in jail.d/drydock.local, as drydock-<name>.")}{" "}
          <button
            type="button"
            className="secondary small"
            disabled={busy !== null}
            onClick={() => void preview({ changes: [], convert_legacy: true })}
          >
            <FileCode size={13} /> {t("Preview the split")}
          </button>{" "}
          <button
            type="button"
            className="small"
            disabled={busy !== null || changes.length > 0}
            title={changes.length > 0 ? t("Apply or discard your changes first") : undefined}
            onClick={() => void apply({ changes: [], convert_legacy: true })}
          >
            {t("Split into one file per jail")}
          </button>
        </div>
      )}

      <div className="table-scroll">
        <table className="projects-table fail2ban-jails">
          <thead>
            <tr>
              <th>{t("On")}</th>
              <th>{t("Jail")}</th>
              <th>{t("Log")}</th>
              <th title={t("Failures before a ban")}>maxretry</th>
              <th title={t("Failures count within this window")}>findtime</th>
              <th>bantime</th>
              <th>{t("Active bans")}</th>
              <th>{t("Bans in history")}</th>
              <th>{t("Last ban")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <JailRows
                key={row.name}
                row={row}
                stats={report?.jails.find((jail) => jail.name === row.name)}
                result={tests[row.name]}
                busy={busy !== null}
                onChange={(patch) => {
                  edit(row.name, patch);
                  setTests(({ [row.name]: _dropped, ...rest }) => rest);
                }}
                onTest={() => void test(row)}
                onRemove={() =>
                  row.original
                    ? edit(row.name, { deleted: !row.deleted })
                    : setRows((current) => current.filter((other) => other !== row))
                }
              />
            ))}
          </tbody>
        </table>
      </div>

      <NewJail
        templates={Object.keys(data.templates)}
        taken={rows.map((row) => row.name)}
        onAdd={add}
      />

      <div className="button-row">
        <button
          type="button"
          disabled={busy !== null || changes.length === 0}
          onClick={() => void apply({ changes })}
        >
          <Save size={15} /> {busy ?? t("Apply")}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy !== null || changes.length === 0}
          onClick={() => void preview({ changes })}
        >
          <FileCode size={15} /> {t("Preview the files")}
        </button>
        {changes.length > 0 && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setRows(data.jails.map(toRow));
              setPlan(null);
            }}
          >
            <Undo2 size={15} /> {t("Discard changes")}
          </button>
        )}
        <button type="button" className="secondary" disabled={busy !== null} onClick={() => void load()}>
          <RotateCcw size={15} /> {t("Reload from the host")}
        </button>
      </div>
      {notice && <div className="output ok padded">{notice}</div>}
      {error && <pre className="error">{error}</pre>}
      {plan &&
        (plan.files.length === 0 ? (
          <div className="output padded">{t("Nothing changes on the host.")}</div>
        ) : (
          plan.files.map((file) => (
            <div key={file.path} className="output">
              <div className="output-header">
                <code>/etc/fail2ban/{file.path}</code>
                <span className="muted">
                  {file.before === null ? t("new file") : file.after === null ? t("removed") : ""}
                </span>
              </div>
              <DiffView before={file.before ?? ""} after={file.after ?? ""} />
            </div>
          ))
        ))}
    </div>
  );
}

function JailRows({
  row,
  stats,
  result,
  busy,
  onChange,
  onTest,
  onRemove,
}: {
  row: Row;
  stats: Fail2banReport["jails"][number] | undefined;
  result: Fail2banTestResult | string | undefined;
  busy: boolean;
  onChange: (patch: Partial<Row>) => void;
  onTest: () => void;
  onRemove: () => void;
}) {
  const t = useT();
  const sources = row.original?.sources ?? {};
  const journal = row.original?.backend === "systemd";
  const text = (field: TextField, className: string, placeholder?: string) => (
    <textarea
      className={className}
      rows={Math.min(8, Math.max(1, row[field].split("\n").length))}
      placeholder={placeholder}
      title={sources[field]}
      value={row[field]}
      disabled={row.deleted}
      onChange={(event) => onChange({ [field]: event.target.value })}
    />
  );
  const value = (field: TextField) => (
    <input
      type="text"
      className="fail2ban-number"
      title={sources[field]}
      value={row[field]}
      disabled={row.deleted}
      onChange={(event) => onChange({ [field]: event.target.value })}
    />
  );

  return (
    <>
      <tr className={row.deleted ? "fail2ban-deleted" : undefined}>
        <td>
          <input
            type="checkbox"
            checked={row.enabled}
            disabled={row.deleted}
            onChange={(event) => onChange({ enabled: event.target.checked })}
          />
        </td>
        <td>
          <span className="row-name">{row.name}</span>{" "}
          {!row.original && <span className="badge paused">{t("new")}</span>}
          {row.original?.managed && <span className="badge">DryDock</span>}
          {row.original?.enabled && stats?.bans === 0 && (
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
        <td>
          {journal ? (
            <code title={t("The systemd backend reads the journal, not a file.")}>journal</code>
          ) : (
            text("logpath", "fail2ban-log", PROXY_LOG)
          )}
        </td>
        <td>{value("maxretry")}</td>
        <td>{value("findtime")}</td>
        <td>{value("bantime")}</td>
        <td>{stats?.active_bans ?? "—"}</td>
        <td>{stats?.bans ?? "—"}</td>
        <td className="muted">{stats ? formatDate(stats.last_ban_at) : "—"}</td>
        <td>
          <div className="button-row inline">
            <button
              type="button"
              className="secondary small"
              disabled={busy || journal || row.deleted}
              title={
                journal
                  ? t("The systemd backend reads the journal: test it on the host.")
                  : t("Run these regexes over the end of the log")
              }
              onClick={onTest}
            >
              <FlaskConical size={13} /> {t("Test")}
            </button>
            {(!row.original || row.original.managed) && (
              <button
                type="button"
                className="secondary small icon-only"
                title={row.deleted ? t("Keep") : t("Remove")}
                onClick={onRemove}
              >
                {row.deleted ? <Undo2 size={13} /> : <Trash2 size={13} />}
              </button>
            )}
          </div>
        </td>
      </tr>
      <tr className={`fail2ban-detail${row.deleted ? " fail2ban-deleted" : ""}`}>
        <td colSpan={10}>
          <div className="fail2ban-filter">
            <label className="field">
              <span>
                <code>failregex</code>{" "}
                <span className="muted">{sources.failregex ?? row.original?.filter ?? ""}</span>
              </span>
              {text("failregex", "fail2ban-regex")}
            </label>
            <label className="field">
              <span>
                <code>ignoreregex</code>{" "}
                <span className="muted">{sources.ignoreregex ?? ""}</span>
              </span>
              {text("ignoreregex", "fail2ban-regex")}
            </label>
            {row.original && row.original.dump.length > 0 && (
              <details>
                <summary className="muted">fail2ban-client -d</summary>
                <pre className="match-lines">{row.original.dump.join("\n")}</pre>
              </details>
            )}
            {typeof result === "string" && <pre className="error">{result}</pre>}
            {result !== undefined && typeof result !== "string" && <TestResult result={result} />}
          </div>
        </td>
      </tr>
    </>
  );
}

function NewJail({
  templates,
  taken,
  onAdd,
}: {
  templates: string[];
  taken: string[];
  onAdd: (name: string, create: Fail2banNewJail, logpath: string) => void;
}) {
  const t = useT();
  const [name, setName] = useState("");
  const [create, setCreate] = useState<Fail2banNewJail>({
    template: "auth",
    log_format: "text",
    ban_hook: "forward",
  });
  const [logpath, setLogpath] = useState(PROXY_LOG);
  const valid = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$/.test(name) && !taken.includes(name);

  return (
    <div className="fail2ban-new button-row">
      <input
        type="text"
        className="fail2ban-name"
        placeholder={t("new jail name")}
        value={name}
        onChange={(event) => setName(event.target.value.trim())}
      />
      <select
        value={create.template}
        title={t("Fills the regex; edit it as you like")}
        onChange={(event) => setCreate({ ...create, template: event.target.value })}
      >
        {templates.map((template) => (
          <option key={template} value={template}>
            {TEMPLATE_LABELS[template] ? t(TEMPLATE_LABELS[template]) : template}
          </option>
        ))}
      </select>
      <select
        value={create.log_format}
        onChange={(event) =>
          setCreate({ ...create, log_format: event.target.value as "text" | "json" })
        }
      >
        <option value="text">{t("Text log (Traefik, nginx / SWAG)")}</option>
        <option value="json">{t("JSON log (Caddy)")}</option>
      </select>
      <select
        value={create.ban_hook}
        onChange={(event) =>
          setCreate({ ...create, ban_hook: event.target.value as "forward" | "input" })
        }
      >
        <option value="forward">{t("Ban forwarded traffic (ports published by Docker)")}</option>
        <option value="input">{t("Ban input traffic (host network)")}</option>
      </select>
      <input
        type="text"
        className="fail2ban-log"
        value={logpath}
        onChange={(event) => setLogpath(event.target.value.trim())}
      />
      <button
        type="button"
        className="secondary"
        disabled={!valid || !logpath}
        onClick={() => {
          onAdd(name, create, logpath);
          setName("");
        }}
      >
        <Plus size={15} /> {t("Add a jail")}
      </button>
    </div>
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
        {result.top_ips.map((hit) => `${hit.ip} ×${hit.count}`).join(", ")}
      </div>
      {result.samples.length > 0 && <pre className="diff">{result.samples.join("\n")}</pre>}
    </div>
  );
}
