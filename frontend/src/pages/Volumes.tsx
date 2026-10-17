import { Circle, HardDrive, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useConfirm } from "../components/ConfirmDialog";
import JobList from "../components/JobList";
import { formatDate } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import type { Volume } from "../types";

export default function Volumes() {
  const confirm = useConfirm();
  const { user } = useAuth();
  const [volumes, setVolumes] = useState<Volume[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback((): void => {
    api
      .listVolumes()
      .then((volumeList) => {
        setVolumes(volumeList);
        setError(null);
      })
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Prunes run as background jobs; useJobs also re-attaches to unrelated ones
  // (scans), so only this page's own kind is shown.
  const { jobs, track, dismiss } = useJobs(refresh);
  const pruneJobs = jobs.filter((job) => job.kind === "volume_prune");
  const pruning = pruneJobs.some(isActive);

  async function run(action: () => Promise<unknown>, successNotice?: string): Promise<void> {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      if (successNotice) setNotice(successNotice);
      refresh();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  function onCreate(event: FormEvent): void {
    event.preventDefault();
    run(async () => {
      await api.createVolume(name.trim());
      setName("");
    }, `Volume "${name.trim()}" created.`);
  }

  async function onDelete(volume: Volume): Promise<void> {
    const confirmed = await confirm({
      title: `Delete volume ${volume.name}?`,
      message: "The data in it will be lost.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!confirmed) return;
    run(() => api.deleteVolume(volume.name), `Volume "${volume.name}" removed.`);
  }

  async function onPrune(): Promise<void> {
    const confirmed = await confirm({
      title: "Prune unused volumes?",
      message: "Removes every volume no container uses. This cannot be undone.",
      confirmLabel: "Prune",
      tone: "danger",
    });
    if (!confirmed) return;
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
            onChange={(event) => setName(event.target.value)}
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
            {volumes.map((volume) => {
              const inUse = volume.used_by.length > 0;
              return (
                <tr key={volume.name}>
                  <td>
                    {user?.is_admin ? (
                      <Link
                        className="icon-link"
                        to={`/volumes/${encodeURIComponent(volume.name)}`}
                        title="Browse files"
                      >
                        <HardDrive size={15} /> {volume.name}
                      </Link>
                    ) : (
                      <span className="icon-link">
                        <HardDrive size={15} /> {volume.name}
                      </span>
                    )}
                    <div className="muted">
                      <code>{volume.mountpoint}</code>
                    </div>
                  </td>
                  <td>{volume.driver}</td>
                  <td>
                    {inUse ? (
                      volume.used_by.map((attachment) => (
                        <div key={`${attachment.id}:${attachment.destination}`}>
                          <Link
                            className="icon-link"
                            to={`/containers/${attachment.id}`}
                            title={attachment.running ? "running" : "stopped"}
                          >
                            <Circle
                              size={8}
                              fill="currentColor"
                              className={attachment.running ? "dot-running" : "dot-stopped"}
                            />{" "}
                            {attachment.name}
                          </Link>
                          <div className="muted">
                            <code>{attachment.destination}</code>
                            {!attachment.rw && " (ro)"}
                          </div>
                        </div>
                      ))
                    ) : (
                      <span className="badge">unused</span>
                    )}
                  </td>
                  <td>{volume.compose_project ?? "—"}</td>
                  <td className="muted">
                    {formatDate(volume.created_at)}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="secondary small"
                      disabled={busy || inUse}
                      title={inUse ? "Volume is attached to a container" : "Delete volume"}
                      onClick={() => onDelete(volume)}
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
