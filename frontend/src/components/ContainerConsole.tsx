import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { SquareTerminal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type Status = "connecting" | "open" | "closed" | "error";

/** Interactive shell in a container, over the /api/containers/{id}/exec WebSocket. */
export default function ContainerConsole({
  containerId,
  title,
  onClose,
}: {
  containerId: string;
  title: string;
  onClose: () => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const term = new Terminal({
      cursorBlink: true,
      fontFamily: '"Cascadia Code", Consolas, Menlo, monospace',
      fontSize: 13,
      theme: { background: "#0d1117" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    fit.fit();

    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const params = new URLSearchParams({ cols: String(term.cols), rows: String(term.rows) });
    const ws = new WebSocket(
      `${scheme}://${window.location.host}/api/containers/${containerId}/exec?${params}`,
    );
    ws.binaryType = "arraybuffer";

    const send = (msg: object) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    };

    ws.onopen = () => {
      setStatus("open");
      term.focus();
    };
    ws.onmessage = (e) => {
      term.write(typeof e.data === "string" ? e.data : new Uint8Array(e.data));
    };
    ws.onclose = (e) => {
      // 1000 = shell exited normally; 4xxx = backend refused (auth, not running…)
      setStatus(e.code === 1000 ? "closed" : "error");
      if (e.reason) setReason(e.reason);
      term.write(`\r\n\x1b[90m[${e.reason || "connection closed"}]\x1b[0m\r\n`);
    };

    const onData = term.onData((data) => send({ type: "input", data }));
    const onResize = term.onResize(({ cols, rows }) => send({ type: "resize", cols, rows }));
    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(host);

    return () => {
      observer.disconnect();
      onData.dispose();
      onResize.dispose();
      ws.close();
      term.dispose();
    };
  }, [containerId]);

  return (
    <div className="log-panel console-panel">
      <div className="log-header">
        <div>
          <SquareTerminal size={15} /> <strong>{title}</strong>{" "}
          <span className="muted">
            — {status}
            {reason && status === "error" ? `: ${reason}` : ""}
          </span>
        </div>
        <button type="button" className="secondary small" onClick={onClose}>
          <X size={15} /> Close
        </button>
      </div>
      <div className="console-body" ref={hostRef} />
    </div>
  );
}
