import { HardDrive, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import type { Volume } from "../types";

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export default function Volumes() {
  const [volumes, setVolumes] = useState<Volume[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    api
      .listVolumes()
      .then((v) => {
        setVolumes(v);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      if (ok) setNotice(ok);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  function onCreate(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      await api.createVolume(name.trim());
      setName("");
    }, `Volume "${name.trim()}" created.`);
  }

  function onDelete(v: Volume) {
    if (!window.confirm(`Delete volume "${v.name}"? Data in it will be lost.`)) return;
    run(() => api.deleteVolume(v.name), `Volume "${v.name}" removed.`);
  }

  function onPrune() {
    if (!window.confirm("Remove all unused volumes? This cannot be undone.")) return;
    run(async () => {
      const res = await api.pruneVolumes();
      setNotice(
        `Pruned ${res.deleted.length} volume(s), reclaimed ${formatBytes(res.space_reclaimed)}.`,
      );
    });
  }

  return (
    <div>
      <div className="row-between">
        <h1>Volumes</h1>
        <div className="button-row">
          <button type="button" className="secondary" disabled={busy} onClick={onPrune}>
            <Trash2 size={15} /> Prune unused
          </button>
          <button type="button" className="secondary" onClick={refresh}>
            <RefreshCw size={15} /> Refresh
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {notice && <div className="output ok" style={{ padding: "0.75rem" }}>{notice}</div>}

      <div className="section">
        <h2>Create volume</h2>
        <form className="button-row" onSubmit={onCreate}>
          <input
            placeholder="volume name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" disabled={busy || !name.trim()}>
            <HardDrive size={15} /> Create
          </button>
        </form>
      </div>

      {!volumes ? (
        <div className="empty">Loading…</div>
      ) : volumes.length === 0 ? (
        <div className="empty">No volumes found.</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Driver</th>
              <th>Usage</th>
              <th>Compose</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {volumes.map((v) => {
              const inUse = v.used_by.length > 0;
              return (
                <tr key={v.name}>
                  <td>
                    <span className="icon-link">
                      <HardDrive size={15} /> {v.name}
                    </span>
                    <div className="muted">
                      <code>{v.mountpoint}</code>
                    </div>
                  </td>
                  <td>{v.driver}</td>
                  <td>
                    {inUse ? (
                      <span className="badge running" title={v.used_by.join(", ")}>
                        in use ({v.used_by.length})
                      </span>
                    ) : (
                      <span className="badge">unused</span>
                    )}
                  </td>
                  <td>{v.compose_project ?? "—"}</td>
                  <td className="muted">
                    {v.created_at ? new Date(v.created_at).toLocaleString() : "—"}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="secondary small"
                      disabled={busy || inUse}
                      title={inUse ? "Volume is attached to a container" : "Delete volume"}
                      onClick={() => onDelete(v)}
                    >
                      <Trash2 size={14} /> Delete
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
