import { Circle, HardDrive, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import JobList from "../components/JobList";
import { useJobs } from "../hooks/useJobs";
import type { Volume } from "../types";

export default function Volumes() {
  const confirm = useConfirm();
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

  // Prunes run as background jobs; useJobs also re-attaches to unrelated ones
  // (scans), so only this page's own kind is shown.
  const { jobs, track, dismiss } = useJobs(refresh);
  const pruneJobs = jobs.filter((j) => j.kind === "volume_prune");
  const pruning = pruneJobs.some((j) => j.status === "pending" || j.status === "running");

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

  async function onDelete(v: Volume) {
    const ok = await confirm({
      title: `Delete volume ${v.name}?`,
      message: "The data in it will be lost.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    run(() => api.deleteVolume(v.name), `Volume "${v.name}" removed.`);
  }

  async function onPrune() {
    const ok = await confirm({
      title: "Prune unused volumes?",
      message: "Removes every volume no container uses. This cannot be undone.",
      confirmLabel: "Prune",
      tone: "danger",
    });
    if (!ok) return;
    run(async () => track(await api.pruneVolumes()));
  }

  return (
    <div>
      <div className="row-between">
        <h1>Volumes</h1>
        <div className="button-row">
          <button type="button" className="secondary" disabled={busy || pruning} onClick={onPrune}>
            <Trash2 size={15} /> Prune unused
          </button>
          <button type="button" className="secondary" onClick={refresh}>
            <RefreshCw size={15} /> Refresh
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {notice && <div className="output ok" style={{ padding: "0.75rem" }}>{notice}</div>}
      <JobList jobs={pruneJobs} onDismiss={dismiss} />

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
              <th>Used by</th>
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
                      v.used_by.map((u) => (
                        <div key={`${u.id}:${u.destination}`}>
                          <Link
                            className="icon-link"
                            to={`/containers/${u.id}`}
                            title={u.running ? "running" : "stopped"}
                          >
                            <Circle
                              size={8}
                              fill="currentColor"
                              className={u.running ? "dot-running" : "dot-stopped"}
                            />{" "}
                            {u.name}
                          </Link>
                          <div className="muted">
                            <code>{u.destination}</code>
                            {!u.rw && " (ro)"}
                          </div>
                        </div>
                      ))
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
