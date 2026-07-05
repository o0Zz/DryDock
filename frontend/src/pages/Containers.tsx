import {
  Circle,
  Play,
  RefreshCw,
  RotateCw,
  ScrollText,
  Square,
  X,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Container } from "../types";

type Action = "start" | "stop" | "restart";
const ACTIONS: Action[] = ["start", "stop", "restart"];
const ACTION_ICONS: Record<Action, LucideIcon> = {
  start: Play,
  stop: Square,
  restart: RotateCw,
};

export default function Containers() {
  const [containers, setContainers] = useState<Container[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Container | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api
      .listContainers()
      .then(setContainers)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const runAction = useCallback(
    async (id: string, action: Action) => {
      const key = `${id}:${action}`;
      setBusy(key);
      try {
        await api.containerAction(id, action);
        refresh();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  if (error) return <div className="error">Failed: {error}</div>;
  if (!containers) return <div>Loading…</div>;

  return (
    <div>
      <div className="row-between">
        <h1>Containers</h1>
        <button type="button" className="secondary" onClick={refresh}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>

      {containers.length === 0 ? (
        <div className="empty">No containers running.</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Image</th>
              <th>Status</th>
              <th>Ports</th>
              <th>Compose</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {containers.map((c) => (
              <tr key={c.id}>
                <td>
                  <button
                    type="button"
                    className="linklike"
                    title="View logs"
                    onClick={() => setSelected(c)}
                  >
                    <ScrollText size={14} /> {c.name}
                  </button>
                </td>
                <td>{c.image}</td>
                <td>
                  <span className={`badge ${c.state}`}>
                    <Circle size={8} fill="currentColor" /> {c.state}
                  </span>
                </td>
                <td>
                  {c.ports
                    .filter((p) => p.public_port)
                    .map((p) => `${p.public_port}→${p.private_port}/${p.protocol}`)
                    .join(", ") || "—"}
                </td>
                <td>
                  {c.compose_project
                    ? `${c.compose_project} / ${c.compose_service ?? ""}`
                    : "—"}
                </td>
                <td>
                  <div className="button-row inline">
                    {ACTIONS.map((a) => {
                      const Icon = ACTION_ICONS[a];
                      return (
                        <button
                          key={a}
                          type="button"
                          className="secondary small"
                          disabled={busy === `${c.id}:${a}`}
                          onClick={() => runAction(c.id, a)}
                        >
                          <Icon size={14} /> {a}
                        </button>
                      );
                    })}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <LogPanel container={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function LogPanel({ container, onClose }: { container: Container; onClose: () => void }) {
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<"connecting" | "open" | "closed" | "error">("connecting");
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setLines([]);
    setStatus("connecting");
    const src = new EventSource(`/api/logs/container/${container.id}?tail=200`);

    src.addEventListener("open", () => setStatus("open"));
    src.addEventListener("close", () => setStatus("closed"));
    src.addEventListener("error", (e: MessageEvent) => {
      setStatus("error");
      if (e.data) setLines((prev) => [...prev, `[error] ${e.data}`]);
    });
    src.onmessage = (e) => setLines((prev) => [...prev, e.data]);
    src.onerror = () => setStatus("error");

    return () => src.close();
  }, [container.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [lines]);

  return (
    <div className="log-panel">
      <div className="log-header">
        <div>
          <ScrollText size={15} /> <strong>{container.name}</strong>{" "}
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
