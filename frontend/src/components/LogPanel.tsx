import { ScrollText, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { msg, useT } from "../i18n";

type Status = "connecting" | "open" | "closed" | "error";

const STATUS_LABELS: Record<Status, string> = {
  connecting: msg("connecting"),
  open: msg("open"),
  closed: msg("closed"),
  error: msg("error"),
};

// Older lines are dropped so a long session does not keep growing memory.
const MAX_LINES = 5000;
// Within this many pixels of the end counts as "at the bottom".
const FOLLOW_SLACK = 24;
// An inline panel never gets shorter than this, even in a very short window.
const MIN_INLINE_HEIGHT = 240;
// SGR colours and other CSI sequences; rendered as text they are noise.
const ANSI_PATTERN = /\u001b\[[0-9;?]*[ -/]*[@-~]/g;

function appendLine(previous: string[], line: string): string[] {
  const next = [...previous, line.replace(ANSI_PATTERN, "")];
  return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
}

/** Live log viewer backed by a Server-Sent Events endpoint. Floats over the
 * page by default; `inline` renders it in the page flow instead. */
export default function LogPanel({
  title,
  url,
  onClose,
  inline = false,
  filter = "",
}: {
  title: string;
  url: string;
  onClose?: () => void;
  inline?: boolean;
  /** Case-insensitive substring; only matching lines are shown. */
  filter?: string;
}) {
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>("connecting");
  const t = useT();
  const bodyRef = useRef<HTMLPreElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [fitHeight, setFitHeight] = useState<number | null>(null);
  // Follow new lines only while the user has not scrolled up to read back.
  const followRef = useRef(true);

  useEffect(() => {
    setLines([]);
    setStatus("connecting");
    followRef.current = true;
    const eventSource = new EventSource(url);

    eventSource.addEventListener("open", () => setStatus("open"));
    eventSource.addEventListener("close", () => setStatus("closed"));
    eventSource.addEventListener("error", (event: MessageEvent) => {
      setStatus("error");
      if (event.data) setLines((previous) => appendLine(previous, `[error] ${event.data}`));
    });
    eventSource.onmessage = (event) => setLines((previous) => appendLine(previous, event.data));
    eventSource.onerror = () => setStatus("error");

    return () => eventSource.close();
  }, [url]);

  // Inline, the panel fills the window from where it starts down to the page's
  // bottom padding, so only the log scrolls, not the page around it. What sits
  // above it differs per page, so a fixed CSS height cannot get this right.
  useLayoutEffect(() => {
    if (!inline) return;
    const fit = (): void => {
      const panel = panelRef.current;
      if (!panel) return;
      const top = panel.getBoundingClientRect().top + window.scrollY;
      const content = panel.closest(".content");
      const padding = content ? parseFloat(getComputedStyle(content).paddingBottom) || 0 : 0;
      setFitHeight(Math.max(MIN_INLINE_HEIGHT, Math.floor(window.innerHeight - top - padding)));
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [inline]);

  const needle = filter.trim().toLowerCase();
  const shownLines = needle
    ? lines.filter((line) => line.toLowerCase().includes(needle))
    : lines;

  useEffect(() => {
    const body = bodyRef.current;
    if (body && followRef.current) body.scrollTop = body.scrollHeight;
  }, [shownLines]);

  const onScroll = () => {
    const body = bodyRef.current;
    if (!body) return;
    followRef.current = body.scrollHeight - body.scrollTop - body.clientHeight < FOLLOW_SLACK;
  };

  return (
    <div
      ref={panelRef}
      className={inline ? "log-panel inline" : "log-panel"}
      style={inline && fitHeight !== null ? { height: fitHeight } : undefined}
    >
      <div className="log-header">
        <div>
          <ScrollText size={15} /> <strong>{title}</strong>{" "}
          <span className="muted">— {t(STATUS_LABELS[status])}</span>
        </div>
        {onClose && (
          <button type="button" className="secondary small" onClick={onClose}>
            <X size={15} /> {t("Close")}
          </button>
        )}
      </div>
      <pre className="log-body" ref={bodyRef} onScroll={onScroll}>
        {shownLines.join("\n")}
      </pre>
    </div>
  );
}
