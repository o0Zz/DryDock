import { ChevronLeft, Copy, FileCode, FlaskConical, Save, Trash2, Undo2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { copyText } from "../clipboard";
import {
  Block,
  blockKey,
  PlanView,
  PROXY_LOG,
  ruleText,
  TEMPLATE_LABELS,
  TestResult,
  watches,
  where,
} from "../components/fail2banParts";
import { useT } from "../i18n";
import { waitForJob } from "../stackActions";
import type {
  Fail2banBlock,
  Fail2banEdit,
  Fail2banFileEdit,
  Fail2banJailConfig,
  Fail2banJails,
  Fail2banPlan,
  Fail2banTestResult,
} from "../types";

const SECURITY = "/proxy?tab=security";
const JAIL_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$/;

/**
 * One jail on its own page (/proxy/jails/<name>), or a new one (/proxy/jails/new, with
 * ?from=<jail> to copy one). A jail is the raw blocks of /etc/fail2ban that define it;
 * applying writes them, fail2ban checks the config, and a refused one is put back.
 */
export default function Fail2banJail() {
  const t = useT();
  const { name } = useParams();
  const [searchParams] = useSearchParams();
  const [jails, setJails] = useState<Fail2banJails | null>(null);
  // The jail being edited: the host's, or a new one not written yet.
  const [jail, setJail] = useState<Fail2banJailConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const creating = name === undefined;

  useEffect(() => {
    api
      .fail2banJails()
      .then((read) => {
        setJails(read);
        if (!creating) {
          const found = read.jails.find((other) => other.name === name);
          if (found) setJail(found);
          else setError(t("No jail named {name} on the host.", { name: name ?? "" }));
        }
      })
      .catch((loadError: Error) => setError(loadError.message));
  }, [creating, name, t]);

  return (
    <div>
      <div className="crumb">
        <Link to={SECURITY}>
          <ChevronLeft size={15} /> {t("Security")}
        </Link>
      </div>
      {error && <pre className="error">{error}</pre>}
      {!jails && !error && <div className="empty">{t("Loading…")}</div>}
      {jails && creating && !jail && (
        <NewJailForm
          jails={jails}
          from={searchParams.get("from") ?? ""}
          onReady={setJail}
        />
      )}
      {jail && (
        <JailEditor
          key={jail.name}
          jail={jail}
          isNew={creating}
          onStartOver={creating ? () => setJail(null) : undefined}
        />
      )}
    </div>
  );
}

/** Name the jail and pick what it starts from: a template, or a copy of a jail. */
function NewJailForm({
  jails,
  from,
  onReady,
}: {
  jails: Fail2banJails;
  from: string;
  onReady: (jail: Fail2banJailConfig) => void;
}) {
  const t = useT();
  const taken = jails.jails.map((jail) => jail.name);
  const copyOf = taken.includes(from) ? from : "";
  // "template:<id>" or "copy:<jail>".
  const [start, setStart] = useState(copyOf ? `copy:${copyOf}` : `template:${jails.templates[0]}`);
  const [name, setName] = useState(copyOf ? `${copyOf}-copy` : "");
  const [banHook, setBanHook] = useState<"forward" | "input">("forward");
  const [logpath, setLogpath] = useState(PROXY_LOG);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [kind, source] = start.split(/:(.*)/s);
  const free = JAIL_NAME.test(name) && !taken.includes(name);

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onReady(
        kind === "copy"
          ? await api.duplicateFail2banJail({ source, name })
          : await api.newFail2banJail({ name, template: source, ban_hook: banHook, logpath }),
      );
    } catch (createError) {
      setError((createError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>{t("New jail")}</h1>
      <form className="fail2ban-fields" onSubmit={(event) => void submit(event)}>
        <label className="field">
          {t("Name")}
          <input
            type="text"
            value={name}
            placeholder="drydock-wordpress"
            onChange={(event) => setName(event.target.value.trim())}
          />
          {name && !free && (
            <span className="error-text">
              {taken.includes(name) ? t("A jail already has this name.") : t("Letters, digits, . _ and - only.")}
            </span>
          )}
        </label>
        <label className="field">
          {t("Start from")}
          <select value={start} onChange={(event) => setStart(event.target.value)}>
            <optgroup label={t("Template")}>
              {jails.templates.map((template) => (
                <option key={template} value={`template:${template}`}>
                  {TEMPLATE_LABELS[template] ? t(TEMPLATE_LABELS[template]) : template}
                </option>
              ))}
            </optgroup>
            <optgroup label={t("Copy of a jail")}>
              {taken.map((jail) => (
                <option key={jail} value={`copy:${jail}`}>
                  {jail}
                </option>
              ))}
            </optgroup>
          </select>
        </label>
        {kind === "template" && (
          <>
            <label className="field">
              {t("Log file")}
              <input
                type="text"
                className="fail2ban-log"
                value={logpath}
                onChange={(event) => setLogpath(event.target.value.trim())}
              />
            </label>
            <label className="field">
              {t("Ban")}
              <select
                value={banHook}
                onChange={(event) => setBanHook(event.target.value as "forward" | "input")}
              >
                <option value="forward">{t("Ban forwarded traffic (ports published by Docker)")}</option>
                <option value="input">{t("Ban input traffic (host network)")}</option>
              </select>
            </label>
          </>
        )}
        <div className="button-row">
          <button type="submit" disabled={busy || !free || (kind === "template" && !logpath)}>
            {busy ? t("Reading the host…") : t("Continue")}
          </button>
        </div>
      </form>
      {error && <pre className="error">{error}</pre>}
    </>
  );
}

function JailEditor({
  jail,
  isNew,
  onStartOver,
}: {
  jail: Fail2banJailConfig;
  isNew: boolean;
  onStartOver?: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  // Edited block text, by blockKey.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [removing, setRemoving] = useState(false);
  const [plan, setPlan] = useState<Fail2banPlan | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<Fail2banTestResult | string | null>(null);
  const [copied, setCopied] = useState(false);
  const journal = jail.backend === "systemd";
  const reads = watches(jail);

  const textOf = (block: Fail2banBlock): string => drafts[blockKey(block)] ?? block.text;

  // What the server must write, from the blocks as edited.
  const files: Fail2banFileEdit[] = [];
  for (const block of jail.blocks) {
    if (removing) {
      if (block.owner === "drydock") files.push({ path: block.path, section: null, text: null });
    } else if (isNew) {
      files.push({ path: block.path, section: null, text: textOf(block), new: true });
    } else if (textOf(block) !== block.text) {
      files.push({ path: block.path, section: block.section, text: textOf(block) });
    }
  }
  const edit: Fail2banEdit = { files };

  function setText(block: Fail2banBlock, text: string): void {
    setDrafts((current) => ({ ...current, [blockKey(block)]: text }));
    setPlan(null);
  }

  async function run(label: string, action: () => Promise<void>): Promise<void> {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (actionError) {
      setError((actionError as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const preview = () =>
    run(t("Reading the host…"), async () => setPlan(await api.planFail2ban(edit)));

  const apply = () =>
    run(t("Applying…"), async () => {
      await waitForJob(await api.applyFail2ban(edit));
      navigate(SECURITY);
    });

  const runTest = () =>
    run(t("Testing…"), async () => {
      if (!jail.filter) return;
      const edited = jail.blocks.filter(
        (block) => block.section === null && (isNew || textOf(block) !== block.text),
      );
      try {
        setTest(
          await api.testFail2ban({
            logpath: jail.logpath[0],
            filter: jail.filter,
            files: Object.fromEntries(edited.map((block) => [block.path, textOf(block)])),
          }),
        );
      } catch (testError) {
        setTest((testError as Error).message);
      }
    });

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
    <>
      <div className="row-between">
        <h1>
          {jail.name} {isNew && <span className="badge paused">{t("new")}</span>}
          {!isNew && (
            <span className={`badge ${jail.enabled ? "running" : ""}`}>
              {jail.enabled ? t("On") : t("Off")}
            </span>
          )}
          {jail.managed && !isNew && <span className="badge">DryDock</span>}
        </h1>
        <div className="button-row inline">
          <button
            type="button"
            className="secondary"
            disabled={busy !== null || journal || !jail.filter || jail.logpath.length === 0 || removing}
            title={
              journal
                ? t("The systemd backend reads the journal: test it on the host.")
                : t("Run the filter, as edited, over the end of the log")
            }
            onClick={() => void runTest()}
          >
            <FlaskConical size={15} /> {t("Test")}
          </button>
          <button
            type="button"
            className="secondary"
            title={t("Every block with its file, to paste into an AI or a terminal")}
            onClick={() => void copy()}
          >
            <Copy size={15} /> {copied ? t("Copied") : t("Copy")}
          </button>
          {jail.managed && !isNew && (
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setRemoving(!removing);
                setPlan(null);
              }}
            >
              {removing ? <Undo2 size={15} /> : <Trash2 size={15} />}{" "}
              {removing ? t("Keep") : t("Remove")}
            </button>
          )}
        </div>
      </div>
      {!isNew && (
        <p className="muted">
          <code title={reads.title}>{reads.label}</code> · {ruleText(jail)}
        </p>
      )}
      {typeof test === "string" && <pre className="error">{test}</pre>}
      {test !== null && typeof test !== "string" && <TestResult result={test} />}

      {removing ? (
        <div className="output padded">{t("Apply removes this jail and its filter.")}</div>
      ) : (
        <>
          <p className="muted">
            {t(
              "The blocks of /etc/fail2ban that define this jail, in the order fail2ban reads them: the last value of a key wins. Package files are read only; change them in the .local file.",
            )}
          </p>
          {jail.blocks.map((block) => (
            <Block
              key={blockKey(block)}
              block={block}
              text={textOf(block)}
              disabled={false}
              onText={(text) => setText(block, text)}
            />
          ))}
          {jail.dump.length > 0 && (
            <details className="fail2ban-block">
              <summary className="muted">fail2ban-client -d</summary>
              <pre className="match-lines">{jail.dump.join("\n")}</pre>
            </details>
          )}
        </>
      )}

      <div className="button-row">
        <button
          type="button"
          disabled={busy !== null || edit.files.length === 0}
          onClick={() => void apply()}
        >
          <Save size={15} /> {busy ?? t("Apply")}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy !== null || edit.files.length === 0}
          onClick={() => void preview()}
        >
          <FileCode size={15} /> {t("Preview the files")}
        </button>
        {!isNew && (Object.keys(drafts).length > 0 || removing) && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setDrafts({});
              setRemoving(false);
              setPlan(null);
            }}
          >
            <Undo2 size={15} /> {t("Discard changes")}
          </button>
        )}
        {onStartOver && (
          <button type="button" className="secondary" onClick={onStartOver}>
            <Undo2 size={15} /> {t("Start over")}
          </button>
        )}
      </div>
      {error && <pre className="error">{error}</pre>}
      {plan && <PlanView plan={plan} />}
    </>
  );
}
