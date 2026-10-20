import { Network, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import ContainerLink from "../components/ContainerLink";
import JobList from "../components/JobList";
import SortHeader from "../components/SortHeader";
import { formatDate } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import { useSort } from "../hooks/useSort";
import { useT } from "../i18n";
import type { DockerNetwork } from "../types";

export default function Networks() {
  const confirm = useConfirm();
  const t = useT();
  const [networks, setNetworks] = useState<DockerNetwork[] | null>(null);
  const sorting = useSort(networks, {
    storageKey: "drydock.sort.networks",
    columns: {
      name: (network) => network.name,
      driver: (network) => network.driver,
      subnet: (network) => network.subnets[0],
      containers: (network) => network.used_by.length,
      compose: (network) => network.compose_project,
      created: (network) => (network.created_at ? Date.parse(network.created_at) : null),
    },
    initial: { column: "name", descending: false },
    descendingFirst: ["containers", "created"],
  });
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
  const { jobs, start, dismiss } = useJobs(refresh, setError);
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
      setError(actionError instanceof Error ? actionError.message : t("Action failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(network: DockerNetwork): Promise<void> {
    const confirmed = await confirm({
      title: t("Delete network {name}?", { name: network.name }),
      message: network.compose_project
        ? t("Compose creates it again on the next up of {project}.", {
            project: network.compose_project,
          })
        : t("Containers can no longer join it."),
      confirmLabel: t("Delete"),
      tone: "danger",
    });
    if (!confirmed) return;
    run(
      () => api.deleteNetwork(network.id),
      t("Network \"{name}\" removed.", { name: network.name }),
    );
  }

  async function onPrune(): Promise<void> {
    const confirmed = await confirm({
      title: t("Prune unused networks?"),
      message: t(
        "Removes every custom network no container uses. Networks of stopped containers are kept.",
      ),
      confirmLabel: t("Prune"),
      tone: "danger",
    });
    if (!confirmed) return;
    setNotice(null);
    start(api.pruneNetworks);
  }

  return (
    <div>
      <div className="row-between">
        <h1>{t("Networks")}</h1>
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
      {notice && <div className="output ok padded">{notice}</div>}
      <JobList jobs={pruneJobs} onDismiss={dismiss} />

      {!networks ? (
        <div className="empty">{t("Loading…")}</div>
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
              <SortHeader sorting={sorting} column="subnet">
                {t("Subnet")}
              </SortHeader>
              <SortHeader sorting={sorting} column="containers">
                {t("Containers")}
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
            {sorting.rows.map((network) => {
              const inUse = network.used_by.length > 0;
              return (
                <tr key={network.id}>
                  <td>
                    <span className="icon-link row-name">
                      <Network size={15} /> {network.name}
                    </span>{" "}
                    {network.predefined && <span className="badge">{t("built-in")}</span>}{" "}
                    {network.internal && <span className="badge">{t("internal")}</span>}
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
                              <div className="muted">
                                {t("gateway {address}", { address: network.gateways[index] })}
                              </div>
                            )}
                          </div>
                        ))}
                  </td>
                  <td>
                    {inUse ? (
                      network.used_by.map((attachment) => (
                        <div key={attachment.id}>
                          <ContainerLink
                            id={attachment.id}
                            name={attachment.name}
                            running={attachment.running}
                          />
                          {attachment.ip_address && (
                            <span className="muted"> {attachment.ip_address}</span>
                          )}
                        </div>
                      ))
                    ) : (
                      <span className="badge">{t("unused")}</span>
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
                        title={inUse ? t("A container uses this network") : t("Delete network")}
                        onClick={() => onDelete(network)}
                      >
                        <Trash2 size={14} /> {t("Delete")}
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
