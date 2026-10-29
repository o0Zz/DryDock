import { Copy, FileCode, FlaskConical, Plus, RotateCcw, Save, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { copyText } from "../clipboard";
import { formatDate } from "../format";
import { msg, useT } from "../i18n";
import { waitForJob } from "../stackActions";
import type {
  Fail2banBlock,
  Fail2banEdit,
  Fail2banFileEdit,
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
  custom: msg("Your own regex"),
};
const OWNER_LABELS = {
  package: msg("package file, read only"),
  local: msg("your file"),
  drydock: msg("made by DryDock"),
};
// A package filter is long (sshd: 139 lines): it opens on demand.
const LONG_BLOCK = 30;

function blockKey(block: Fail2banBlock): string {
  return `${block.path}#${block.section ?? ""}`;
}

function where(block: Fail2banBlock): string {
  return `/etc/fail2ban/${block.path}${block.line ? `:${block.line}` : ""}`;
}

/**
 * Every fail2ban jail of the host, shown as the raw blocks that define it, in the order
 * fail2ban reads them: its [section] in each jail file, then its filter files. The
 * package's files are read only; an override goes in the .local file after them. A block
 * goes back where it was, and applying checks the config before reloading.
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
  // Jails added here and not applied yet, shown after the host's.
  const [added, setAdded] = useState<Fail2banJailConfig[]>([]);
  // Edited block text, by blockKey.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  // DryDock's jails to remove.
  const [removed, setRemoved] = useState<string[]>([]);
  const [plan, setPlan] = useState<Fail2banPlan | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, Fail2banTestResult | string>>({});

  const discard = (): void => {
    setAdded([]);
    setDrafts({});
    setRemoved([]);
    setPlan(null);
  };

  const load = useCallback(async (): Promise<void> => {
    try {
      setData(await api.fail2banJails());
      setError(null);
      discard();
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

  const textOf = (block: Fail2banBlock): string => drafts[blockKey(block)] ?? block.text;
  const isNew = (jail: Fail2banJailConfig): boolean => added.includes(jail);

  // What the server must write, from the blocks as edited.
  const files: Fail2banFileEdit[] = [];
  for (const jail of [...data.jails, ...added]) {
    for (const block of jail.blocks) {
      if (removed.includes(jail.name)) {
        if (block.owner === "drydock") files.push({ path: block.path, section: null, text: null });
      } else if (isNew(jail)) {
        files.push({ path: block.path, section: null, text: textOf(block), new: true });
      } else if (textOf(block) !== block.text) {
        files.push({ path: block.path, section: block.section, text: textOf(block) });
      }
    }
  }
  const edit: Fail2banEdit = { files };

  function setText(block: Fail2banBlock, text: string): void {
    setDrafts((current) => ({ ...current, [blockKey(block)]: text }));
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
      await load();
      setNotice(t("Applied: fail2ban checked the config and reloaded."));
      onApplied();
    } catch (applyError) {
      setError((applyError as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function test(jail: Fail2banJailConfig): Promise<void> {
    if (!jail.filter) return;
    setBusy(t("Testing…"));
    const edited = jail.blocks.filter(
      (block) => block.section === null && (isNew(jail) || textOf(block) !== block.text),
    );
    try {
      const result = await api.testFail2ban({
        logpath: jail.logpath[0],
        filter: jail.filter,
        files: Object.fromEntries(edited.map((block) => [block.path, textOf(block)])),
      });
      setTests((current) => ({ ...current, [jail.name]: result }));
    } catch (testError) {
      setTests((current) => ({ ...current, [jail.name]: (testError as Error).message }));
    } finally {
      setBusy(null);
    }
  }

  async function add(jail: Fail2banNewJail): Promise<void> {
    setError(null);
    try {
      const created = await api.newFail2banJail(jail);
      setAdded((current) => [...current, created]);
      setPlan(null);
    } catch (addError) {
      setError((addError as Error).message);
    }
  }

  function remove(jail: Fail2banJailConfig): void {
    if (isNew(jail)) {
      setAdded((current) => current.filter((other) => other !== jail));
    } else {
      setRemoved((current) =>
        current.includes(jail.name)
          ? current.filter((name) => name !== jail.name)
          : [...current, jail.name],
      );
    }
    setPlan(null);
  }

  return (
    <div className="subsection">
      <p className="muted">
        {t(
          "Every jail of the host, as the blocks of /etc/fail2ban that define it, in the order fail2ban reads them: the last value of a key wins. The package's files are read only, since apt replaces them; put a change in the .local file after them. Jails DryDock creates get their own jail.d/<name>.local and filter.d/<name>.conf.",
        )}
      </p>
      {data.legacy && (
        <div className="output padded">
          {t("Jails from an older DryDock are all in jail.d/drydock.local, as drydock-<name>.")}{" "}
          <button
            type="button"
            className="secondary small"
            disabled={busy !== null}
            onClick={() => void preview({ files: [], convert_legacy: true })}
          >
            <FileCode size={13} /> {t("Preview the split")}
          </button>{" "}
          <button
            type="button"
            className="small"
            disabled={busy !== null || files.length > 0}
            title={files.length > 0 ? t("Apply or discard your changes first") : undefined}
            onClick={() => void apply({ files: [], convert_legacy: true })}
          >
            {t("Split into one file per jail")}
          </button>
        </div>
      )}

      {[...data.jails, ...added].map((jail) => (
        <JailCard
          key={jail.name}
          jail={jail}
          isNew={isNew(jail)}
          removed={removed.includes(jail.name)}
          stats={report?.jails.find((other) => other.name === jail.name)}
          result={tests[jail.name]}
          busy={busy !== null}
          textOf={textOf}
          onText={setText}
          onTest={() => void test(jail)}
          onRemove={() => remove(jail)}
        />
      ))}

      <NewJail
        templates={data.templates}
        taken={[...data.jails, ...added].map((jail) => jail.name)}
        onAdd={(jail) => void add(jail)}
      />

      <div className="button-row">
        <button
          type="button"
          disabled={busy !== null || files.length === 0}
          onClick={() => void apply(edit)}
        >
          <Save size={15} /> {busy ?? t("Apply")}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy !== null || files.length === 0}
          onClick={() => void preview(edit)}
        >
          <FileCode size={15} /> {t("Preview the files")}
        </button>
        {files.length > 0 && (
          <button type="button" className="secondary" onClick={discard}>
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

function JailCard({
  jail,
  isNew,
  removed,
  stats,
  result,
  busy,
  textOf,
  onText,
  onTest,
  onRemove,
}: {
  jail: Fail2banJailConfig;
  isNew: boolean;
  removed: boolean;
  stats: Fail2banReport["jails"][number] | undefined;
  result: Fail2banTestResult | string | undefined;
  busy: boolean;
  textOf: (block: Fail2banBlock) => string;
  onText: (block: Fail2banBlock, text: string) => void;
  onTest: () => void;
  onRemove: () => void;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const journal = jail.backend === "systemd";
  const edited = jail.blocks.some((block) => textOf(block) !== block.text);

  // Every block with its file, ready to paste into an AI or a terminal.
  async function copy(): Promise<void> {
    const text = jail.blocks
      .filter((block) => textOf(block))
      .map((block) => `# ${where(block)} (${block.owner})\n${textOf(block).trimEnd()}\n`)
      .join("\n");
    if (await copyText(text)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <details className={`fail2ban-jail${removed ? " fail2ban-removed" : ""}`} open={isNew || undefined}>
      <summary>
        <span className="row-name">{jail.name}</span>
        {isNew && <span className="badge paused">{t("new")}</span>}
        {jail.managed && !isNew && <span className="badge">DryDock</span>}
        {removed && <span className="badge paused">{t("removed on apply")}</span>}
        {edited && <span className="badge paused">{t("edited")}</span>}
        <span className={`badge ${jail.enabled ? "running" : ""}`}>
          {jail.enabled ? t("on") : t("off")}
        </span>
        <code className="muted">
          {journal ? "journal" : jail.logpath.join(" ") || "—"} · maxretry {jail.maxretry || "—"} ·
          findtime {jail.findtime || "—"} · bantime {jail.bantime || "—"}
        </code>
        {stats && (
          <span className="muted">
            {t("{active} banned now, {bans} in history", {
              active: stats.active_bans,
              bans: stats.bans,
            })}
            {stats.last_ban_at && ` · ${t("last {date}", { date: formatDate(stats.last_ban_at) })}`}
          </span>
        )}
        {jail.enabled && stats?.bans === 0 && (
          <span
            className="badge"
            title={t(
              "This jail has banned nobody. Check that its log path and filter match your logs.",
            )}
          >
            {t("no bans")}
          </span>
        )}
      </summary>

      <div className="button-row">
        <button
          type="button"
          className="secondary small"
          title={t("Every block with its file, to paste into an AI or a terminal")}
          onClick={() => void copy()}
        >
          <Copy size={13} /> {copied ? t("Copied") : t("Copy")}
        </button>
        <button
          type="button"
          className="secondary small"
          disabled={busy || journal || !jail.filter || jail.logpath.length === 0 || removed}
          title={
            journal
              ? t("The systemd backend reads the journal: test it on the host.")
              : t("Run the filter, as edited, over the end of the log")
          }
          onClick={onTest}
        >
          <FlaskConical size={13} /> {t("Test")}
        </button>
        {jail.managed && (
          <button type="button" className="secondary small" onClick={onRemove}>
            {removed ? <Undo2 size={13} /> : <Trash2 size={13} />}{" "}
            {removed ? t("Keep") : t("Remove")}
          </button>
        )}
      </div>
      {typeof result === "string" && <pre className="error">{result}</pre>}
      {result !== undefined && typeof result !== "string" && <TestResult result={result} />}

      {jail.blocks.map((block) => (
        <Block
          key={blockKey(block)}
          block={block}
          text={textOf(block)}
          disabled={removed}
          onText={(text) => onText(block, text)}
        />
      ))}
      {jail.dump.length > 0 && (
        <details>
          <summary className="muted">fail2ban-client -d</summary>
          <pre className="match-lines">{jail.dump.join("\n")}</pre>
        </details>
      )}
    </details>
  );
}

function Block({
  block,
  text,
  disabled,
  onText,
}: {
  block: Fail2banBlock;
  text: string;
  disabled: boolean;
  onText: (text: string) => void;
}) {
  const t = useT();
  const readOnly = block.owner === "package";
  const lines = text.split("\n").length;
  const header = (
    <span className="fail2ban-block-path">
      <code>{where(block)}</code> <span className="muted">{t(OWNER_LABELS[block.owner])}</span>
    </span>
  );
  // A place for an override that is not there yet.
  if (!block.text && !text) {
    return (
      <div className="fail2ban-block">
        {header}
        <button
          type="button"
          className="secondary small"
          disabled={disabled}
          onClick={() =>
            onText(block.section ? `[${block.section}]\n` : "[Definition]\nfailregex = \n")
          }
        >
          <Plus size={13} /> {t("Override here")}
        </button>
      </div>
    );
  }
  const area = (
    <textarea
      className="fail2ban-text"
      rows={Math.min(LONG_BLOCK, Math.max(2, lines))}
      spellCheck={false}
      readOnly={readOnly}
      disabled={disabled}
      value={text}
      onChange={(event) => onText(event.target.value)}
    />
  );
  if (readOnly && lines > LONG_BLOCK) {
    return (
      <details className="fail2ban-block">
        <summary>
          {header} <span className="muted">{t("{count} lines", { count: lines })}</span>
        </summary>
        {area}
      </details>
    );
  }
  return (
    <div className="fail2ban-block">
      {header}
      {area}
    </div>
  );
}

function NewJail({
  templates,
  taken,
  onAdd,
}: {
  templates: string[];
  taken: string[];
  onAdd: (jail: Fail2banNewJail) => void;
}) {
  const t = useT();
  const [jail, setJail] = useState<Fail2banNewJail>({
    name: "",
    template: "auth",
    log_format: "text",
    ban_hook: "forward",
    logpath: "/data/proxy/logs/access.log",
  });
  const valid = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$/.test(jail.name) && !taken.includes(jail.name);

  return (
    <div className="fail2ban-new button-row">
      <input
        type="text"
        className="fail2ban-name"
        placeholder={t("new jail name")}
        value={jail.name}
        onChange={(event) => setJail({ ...jail, name: event.target.value.trim() })}
      />
      <select
        value={jail.template}
        title={t("Fills the new files; edit them as you like")}
        onChange={(event) => setJail({ ...jail, template: event.target.value })}
      >
        {templates.map((template) => (
          <option key={template} value={template}>
            {TEMPLATE_LABELS[template] ? t(TEMPLATE_LABELS[template]) : template}
          </option>
        ))}
      </select>
      <select
        value={jail.log_format}
        onChange={(event) =>
          setJail({ ...jail, log_format: event.target.value as "text" | "json" })
        }
      >
        <option value="text">{t("Text log (Traefik, nginx / SWAG)")}</option>
        <option value="json">{t("JSON log (Caddy)")}</option>
      </select>
      <select
        value={jail.ban_hook}
        onChange={(event) =>
          setJail({ ...jail, ban_hook: event.target.value as "forward" | "input" })
        }
      >
        <option value="forward">{t("Ban forwarded traffic (ports published by Docker)")}</option>
        <option value="input">{t("Ban input traffic (host network)")}</option>
      </select>
      <input
        type="text"
        className="fail2ban-log"
        value={jail.logpath}
        onChange={(event) => setJail({ ...jail, logpath: event.target.value.trim() })}
      />
      <button
        type="button"
        className="secondary"
        disabled={!valid || !jail.logpath}
        onClick={() => {
          onAdd(jail);
          setJail({ ...jail, name: "" });
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
