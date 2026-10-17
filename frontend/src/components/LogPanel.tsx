import { ScrollText, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type Status = "connecting" | "open" | "closed" | "error";

/** Live log viewer backed by a Server-Sent Events endpoint. */
export default function LogPanel({
  title,
  url,
  onClose,
}: {
  title: string;
  url: string;
  onClose: () => void;
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [lines]);

  return (
    <div className="log-panel">
      <div className="log-header">
        <div>
          <ScrollText size={15} /> <strong>{title}</strong>{" "}
          <span className="muted">— {status}</span>
        </div>
        <button type="button" className="secondary small" onClick={onClose}>
          <X size={15} /> Close
        </button>
      </div>
      <pre className="log-body">
        {lines.join("\n")}
        <div ref={bottomRef} />
      </pre>
    </div>
  );
}
