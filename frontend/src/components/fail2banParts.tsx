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

// One text for every block of a jail: each block starts with a header line naming its
// file, so the whole jail can be copied into an AI and its answer pasted back at once.
const HEADER = "# --- /etc/fail2ban/";
const HEADER_LINE = /^# --- \/etc\/fail2ban\/(\S+)/;

function headerKey(block: Fail2banBlock): string {
  return `${block.path}${block.line ? `:${block.line}` : ""}`;
}

// Blank lines around a block do not count as a change.
function normalise(text: string): string {
  return text.replace(/^\s*\n/, "").trimEnd();
}

/** The jail's blocks as one text, in fail2ban's read order. */
export function combineBlocks(blocks: Fail2banBlock[]): string {
  return blocks
    .map((block) => {
      const note = !block.text
        ? translate("empty, put your changes here")
        : translate(OWNER_LABELS[block.owner]);
      return `${HEADER}${headerKey(block)}  (${note})\n${normalise(block.text)}\n`;
    })
    .join("\n");
}

export interface SplitBlocks {
  /** Changed text, by blockKey. */
  texts: Record<string, string>;
  /** Header lines that name no file of this jail. */
  unknown: string[];
  /** Read-only files whose text was changed; the change is not written. */
  readOnly: string[];
}

/** The combined text cut back into its blocks, by their header lines. */
export function splitBlocks(text: string, blocks: Fail2banBlock[]): SplitBlocks {
  const result: SplitBlocks = { texts: {}, unknown: [], readOnly: [] };
  const parts: { key: string; lines: string[] }[] = [];
  for (const line of text.replace(/\r\n/g, "\n").split("\n")) {
    const header = HEADER_LINE.exec(line);
    if (header) parts.push({ key: header[1], lines: [] });
    else parts[parts.length - 1]?.lines.push(line);
  }
  for (const part of parts) {
    const path = part.key.replace(/:\d+$/, "");
    const byPath = blocks.filter((block) => block.path === path);
    const block =
      blocks.find((other) => headerKey(other) === part.key) ??
      (byPath.length === 1 ? byPath[0] : undefined);
    if (!block) {
      result.unknown.push(part.key);
      continue;
    }
    const body = normalise(part.lines.join("\n"));
    if (body === normalise(block.text)) continue;
    if (block.owner === "package") result.readOnly.push(block.path);
    else result.texts[blockKey(block)] = body ? `${body}\n` : "";
  }
  return result;
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
