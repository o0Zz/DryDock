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
    const hostElement = hostRef.current;
    if (!hostElement) return;

    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: '"Cascadia Code", Consolas, Menlo, monospace',
      fontSize: 13,
      theme: { background: "#0d1117" },
    });
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(hostElement);
    fitAddon.fit();

    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const sizeParams = new URLSearchParams({
      cols: String(terminal.cols),
      rows: String(terminal.rows),
    });
    const socket = new WebSocket(
      `${scheme}://${window.location.host}/api/containers/${containerId}/exec?${sizeParams}`,
    );
    socket.binaryType = "arraybuffer";

    const send = (message: object): void => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
    };

    socket.onopen = () => {
      setStatus("open");
      terminal.focus();
    };
    socket.onmessage = (event) => {
      terminal.write(typeof event.data === "string" ? event.data : new Uint8Array(event.data));
    };
    socket.onclose = (event) => {
      // 1000 = shell exited normally; 4xxx = backend refused (auth, not running…)
      setStatus(event.code === 1000 ? "closed" : "error");
      if (event.reason) setReason(event.reason);
      terminal.write(`\r\n\x1b[90m[${event.reason || "connection closed"}]\x1b[0m\r\n`);
    };

    const inputListener = terminal.onData((data) => send({ type: "input", data }));
    const resizeListener = terminal.onResize(({ cols, rows }) =>
      send({ type: "resize", cols, rows }),
    );
    const observer = new ResizeObserver(() => fitAddon.fit());
    observer.observe(hostElement);

    return () => {
      observer.disconnect();
      inputListener.dispose();
      resizeListener.dispose();
      socket.close();
      terminal.dispose();
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
