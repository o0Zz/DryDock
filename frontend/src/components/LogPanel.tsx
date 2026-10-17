import { ScrollText, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type Status = "connecting" | "open" | "closed" | "error";

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
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setLines([]);
    setStatus("connecting");
    const src = new EventSource(url);

    src.addEventListener("open", () => setStatus("open"));
    src.addEventListener("close", () => setStatus("closed"));
    src.addEventListener("error", (e: MessageEvent) => {
      setStatus("error");
      if (e.data) setLines((prev) => [...prev, `[error] ${e.data}`]);
    });
    src.onmessage = (e) => setLines((prev) => [...prev, e.data]);
    src.onerror = () => setStatus("error");

    return () => src.close();
  }, [url]);

  const needle = filter.trim().toLowerCase();
  const shown = needle ? lines.filter((l) => l.toLowerCase().includes(needle)) : lines;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [shown.length]);

  return (
    <div className={inline ? "log-panel inline" : "log-panel"}>
      <div className="log-header">
        <div>
          <ScrollText size={15} /> <strong>{title}</strong>{" "}
          <span className="muted">— {status}</span>
        </div>
        {onClose && (
          <button type="button" className="secondary small" onClick={onClose}>
            <X size={15} /> Close
          </button>
        )}
      </div>
      <pre className="log-body">
        {shown.join("\n")}
        <div ref={bottomRef} />
      </pre>
    </div>
  );
}
