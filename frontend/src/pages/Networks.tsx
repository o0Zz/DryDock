import { Circle, Network, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import JobList from "../components/JobList";
import { formatDate } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import type { DockerNetwork } from "../types";

export default function Networks() {
  const confirm = useConfirm();
  const [networks, setNetworks] = useState<DockerNetwork[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback((): void => {
    api
      .listNetworks()
      .then((networkList) => {
        setNetworks(networkList);
        setError(null);
      })
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // useJobs also re-attaches to unrelated jobs (scans); only show this page's kind.
  const { jobs, track, dismiss } = useJobs(refresh);
  const pruneJobs = jobs.filter((job) => job.kind === "network_prune");
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

  async function onDelete(network: DockerNetwork): Promise<void> {
    const confirmed = await confirm({
      title: `Delete network ${network.name}?`,
      message: network.compose_project
        ? `Compose creates it again on the next up of ${network.compose_project}.`
        : "Containers can no longer join it.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!confirmed) return;
    run(() => api.deleteNetwork(network.id), `Network "${network.name}" removed.`);
  }

  async function onPrune(): Promise<void> {
    const confirmed = await confirm({
      title: "Prune unused networks?",
      message:
        "Removes every custom network no container uses. Networks of stopped containers are kept.",
      confirmLabel: "Prune",
      tone: "danger",
    });
    if (!confirmed) return;
    run(async () => track(await api.pruneNetworks()));
  }

  return (
    <div>
      <div className="row-between">
        <h1>Networks</h1>
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

      {!networks ? (
        <div className="empty">Loading…</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Driver</th>
              <th>Subnet</th>
              <th>Containers</th>
              <th>Compose</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {networks.map((network) => {
              const inUse = network.used_by.length > 0;
              return (
                <tr key={network.id}>
                  <td>
                    <span className="icon-link">
                      <Network size={15} /> {network.name}
                    </span>{" "}
                    {network.predefined && <span className="badge">built-in</span>}{" "}
                    {network.internal && <span className="badge">internal</span>}
                  </td>
                  <td>
                    {network.driver}
                    {network.scope && network.scope !== "local" && (
                      <span className="muted"> ({network.scope})</span>
                    )}
                  </td>
                  <td>
                    {network.subnets.length === 0
                      ? "—"
                      : network.subnets.map((subnet, index) => (
                          <div key={subnet}>
                            <code>{subnet}</code>
                            {network.gateways[index] && (
                              <div className="muted">gateway {network.gateways[index]}</div>
                            )}
                          </div>
                        ))}
                  </td>
                  <td>
                    {inUse ? (
                      network.used_by.map((attachment) => (
                        <div key={attachment.id}>
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
                          {attachment.ip_address && (
                            <span className="muted"> {attachment.ip_address}</span>
                          )}
                        </div>
                      ))
                    ) : (
                      <span className="badge">unused</span>
                    )}
                  </td>
                  <td>{network.compose_project ?? "—"}</td>
                  <td className="muted">{formatDate(network.created_at)}</td>
                  <td>
                    {!network.predefined && (
                      <button
                        type="button"
                        className="secondary small"
                        disabled={busy || inUse}
                        title={inUse ? "A container uses this network" : "Delete network"}
                        onClick={() => onDelete(network)}
                      >
                        <Trash2 size={14} /> Delete
                      </button>
                    )}
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
