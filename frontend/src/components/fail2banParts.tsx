import { Plus } from "lucide-react";
import { msg, translate, useT } from "../i18n";
import type { Fail2banBlock, Fail2banJailConfig, Fail2banPlan, Fail2banTestResult } from "../types";
import DiffView from "./DiffView";

/** What the shared fail2ban views (jail list, jail page) need. */

export const TEMPLATE_LABELS: Record<string, string> = {
  auth: msg("Failed logins (401)"),
  forbidden: msg("Refused (403)"),
  botsearch: msg("Scanners (404 on /wp-login.php, /.env...)"),
  badbots: msg("Bad bots (user agent)"),
  unknownhost: msg("Unknown host names (no route)"),
  custom: msg("Your own regex"),
};
const OWNER_LABELS = {
  package: msg("package file, read only"),
  local: msg("your file"),
  drydock: msg("made by DryDock"),
};
// A package filter is long (sshd: 139 lines): it opens on demand.
const LONG_BLOCK = 30;
// The proxy's access log, where the default jails look.
export const PROXY_LOG = "/data/proxy/logs/access.log";

export function blockKey(block: Fail2banBlock): string {
  return `${block.path}#${block.section ?? ""}`;
}

export function where(block: Fail2banBlock): string {
  return `/etc/fail2ban/${block.path}${block.line ? `:${block.line}` : ""}`;
}

const UNITS: [number, string][] = [
  [86400, "d"],
  [3600, "h"],
  [60, "m"],
];

/** Seconds in fail2ban's own short form (600 is 10m); anything else as it is written. */
export function duration(value: string): string {
  const text = value.trim();
  if (!/^-?\d+$/.test(text)) return text || "—";
  const seconds = Number(text);
  if (seconds < 0) return translate("permanent");
  const unit = UNITS.find(([size]) => seconds >= size && seconds % size === 0);
  return unit ? `${seconds / unit[0]}${unit[1]}` : `${seconds}s`;
}

/** "5 tries in 10m, ban 1d": when a jail bans, in one line. */
export function ruleText(jail: Fail2banJailConfig): string {
  return translate("{retries} tries in {window}, ban {bantime}", {
    retries: jail.maxretry || "—",
    window: duration(jail.findtime),
    bantime: duration(jail.bantime),
  });
}

/** What the jail reads: the journal, or its log files by name (the full path in `title`). */
export function watches(jail: Fail2banJailConfig): { label: string; title: string } {
  if (jail.backend === "systemd") return { label: "journal", title: "systemd journal" };
  const title = jail.logpath.join("\n");
  const label = jail.logpath.map((path) => path.split("/").pop() || path).join(", ");
  return { label: label || "—", title };
}

export function Block({
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

/** The files an edit changes, each as a diff. */
export function PlanView({ plan }: { plan: Fail2banPlan }) {
  const t = useT();
  if (plan.files.length === 0) {
    return <div className="output padded">{t("Nothing changes on the host.")}</div>;
  }
  return (
    <>
      {plan.files.map((file) => (
        <div key={file.path} className="output">
          <div className="output-header">
            <code>/etc/fail2ban/{file.path}</code>
            <span className="muted">
              {file.before === null ? t("new file") : file.after === null ? t("removed") : ""}
            </span>
          </div>
          <DiffView before={file.before ?? ""} after={file.after ?? ""} />
        </div>
      ))}
    </>
  );
}

export function TestResult({ result }: { result: Fail2banTestResult }) {
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
