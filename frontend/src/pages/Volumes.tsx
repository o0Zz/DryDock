import { Circle, HardDrive, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useConfirm } from "../components/ConfirmDialog";
import JobList from "../components/JobList";
import SortHeader from "../components/SortHeader";
import { formatDate } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import { useSort } from "../hooks/useSort";
import { useT } from "../i18n";
import type { Volume } from "../types";

export default function Volumes() {
  const confirm = useConfirm();
  const t = useT();
  const { user } = useAuth();
  const [volumes, setVolumes] = useState<Volume[] | null>(null);
  const sorting = useSort(volumes, {
    storageKey: "drydock.sort.volumes",
    columns: {
      name: (volume) => volume.name,
      driver: (volume) => volume.driver,
      used: (volume) => volume.used_by.length,
      compose: (volume) => volume.compose_project,
      created: (volume) => (volume.created_at ? Date.parse(volume.created_at) : null),
    },
    initial: { column: "name", descending: false },
    descendingFirst: ["used", "created"],
  });
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
      setError(actionError instanceof Error ? actionError.message : t("Action failed"));
    } finally {
      setBusy(false);
    }
  }

  function onCreate(event: FormEvent): void {
    event.preventDefault();
    run(async () => {
      await api.createVolume(name.trim());
      setName("");
    }, t("Volume \"{name}\" created.", { name: name.trim() }));
  }

  async function onDelete(volume: Volume): Promise<void> {
    const confirmed = await confirm({
      title: t("Delete volume {name}?", { name: volume.name }),
      message: t("The data in it will be lost."),
      confirmLabel: t("Delete"),
      tone: "danger",
    });
    if (!confirmed) return;
    run(() => api.deleteVolume(volume.name), t("Volume \"{name}\" removed.", { name: volume.name }));
  }

  async function onPrune(): Promise<void> {
    const confirmed = await confirm({
      title: t("Prune unused volumes?"),
      message: t("Removes every volume no container uses. This cannot be undone."),
      confirmLabel: t("Prune"),
      tone: "danger",
    });
    if (!confirmed) return;
    run(async () => track(await api.pruneVolumes()));
  }

  return (
    <div>
      <div className="row-between">
        <h1>{t("Volumes")}</h1>
        <div className="button-row">
          <button type="button" className="secondary" disabled={busy || pruning} onClick={onPrune}>
            <Trash2 size={15} /> {t("Prune unused")}
          </button>
          <button type="button" className="secondary" onClick={refresh}>
            <RefreshCw size={15} /> {t("Refresh")}
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {notice && <div className="output ok" style={{ padding: "0.75rem" }}>{notice}</div>}
      <JobList jobs={pruneJobs} onDismiss={dismiss} />

      <div className="section">
        <h2>{t("Create volume")}</h2>
        <form className="button-row" onSubmit={onCreate}>
          <input
            placeholder={t("volume name")}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button type="submit" disabled={busy || !name.trim()}>
            <HardDrive size={15} /> {t("Create")}
          </button>
        </form>
      </div>

      {!volumes ? (
        <div className="empty">{t("Loading…")}</div>
      ) : volumes.length === 0 ? (
        <div className="empty">{t("No volumes found.")}</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <SortHeader sorting={sorting} column="name">
                {t("Name")}
              </SortHeader>
              <SortHeader sorting={sorting} column="driver">
                {t("Driver")}
              </SortHeader>
              <SortHeader sorting={sorting} column="used">
                {t("Used by")}
              </SortHeader>
              <SortHeader sorting={sorting} column="compose">
                {t("Compose")}
              </SortHeader>
              <SortHeader sorting={sorting} column="created">
                {t("Created")}
              </SortHeader>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((volume) => {
              const inUse = volume.used_by.length > 0;
              return (
                <tr key={volume.name}>
                  <td>
                    {user?.is_admin ? (
                      <Link
                        className="icon-link row-name"
                        to={`/volumes/${encodeURIComponent(volume.name)}`}
                        title={t("Browse files")}
                      >
                        <HardDrive size={15} /> {volume.name}
                      </Link>
                    ) : (
                      <span className="icon-link row-name">
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
                            title={attachment.running ? t("running") : t("stopped")}
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
                            {!attachment.rw && ` (${t("ro")})`}
                          </div>
                        </div>
                      ))
                    ) : (
                      <span className="badge">{t("unused")}</span>
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
                      title={inUse ? t("Volume is attached to a container") : t("Delete volume")}
                      onClick={() => onDelete(volume)}
                    >
                      <Trash2 size={14} /> {t("Delete")}
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
