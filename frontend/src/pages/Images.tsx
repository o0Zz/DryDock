import {
  ArrowUpCircle,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import JobList from "../components/JobList";
import ScanBadge from "../components/ScanBadge";
import ScanFindings from "../components/ScanFindings";
import UpdateBadge, { hasUpdate } from "../components/UpdateBadge";
import { formatBytes, formatDate } from "../format";
import { useJobs } from "../hooks/useJobs";
import { useT } from "../i18n";
import type { LocalImage, ScanDetail, ScanSummary, UpdateSummary } from "../types";

interface ImageRow {
  image: string;
  scan?: ScanSummary;
  update?: UpdateSummary;
  /** Present when the image exists in the local Docker image store. */
  local?: LocalImage;
  inUse: boolean;
  inCompose: boolean;
}

/** "nginx" and "nginx:latest" name the same image; Docker always lists the latter. */
function withDefaultTag(image: string): string {
  if (image.includes("@")) return image;
  return image.slice(image.lastIndexOf("/") + 1).includes(":") ? image : `${image}:latest`;
}

/** Sort worst first: criticals, then highs, then pending updates, then name. */
function rank(row: ImageRow): [number, number, number, string] {
  return [
    row.scan?.critical ? 0 : 1,
    row.scan?.high ? 0 : 1,
    hasUpdate(row.update) ? 0 : 1,
    row.image,
  ];
}

export default function Images() {
  const confirm = useConfirm();
  const t = useT();
  const [scans, setScans] = useState<ScanSummary[]>([]);
  const [updates, setUpdates] = useState<UpdateSummary[]>([]);
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [composeImages, setComposeImages] = useState<Set<string>>(new Set());
  const [localImages, setLocalImages] = useState<LocalImage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [detail, setDetail] = useState<ScanDetail | null>(null);

  const load = useCallback(async (): Promise<void> => {
    try {
      const [scanList, updateList] = await Promise.all([api.listScans(), api.listUpdates()]);
      setScans(scanList);
      setUpdates(updateList);
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadImages = useCallback(async (): Promise<void> => {
    // Images worth listing even when never scanned: anything running, plus
    // anything a Compose file references. Docker being down is not fatal here.
    const [containers, projects, images] = await Promise.all([
      api.listContainers().catch(() => []),
      api.listProjects().catch(() => []),
      api.listImages().catch(() => []),
    ]);
    setLocalImages(images);
    setRunning(
      new Set(
        containers
          .filter((container) => container.state === "running")
          .map((container) => container.image),
      ),
    );
    setComposeImages(
      new Set(
        projects.flatMap(
          (project) => project.services.map((service) => service.image).filter(Boolean) as string[],
        ),
      ),
    );
  }, []);

  // Scans and update checks change the summaries, prunes change the local list.
  const onJobSettled = useCallback((): void => {
    load();
    loadImages();
  }, [load, loadImages]);
  const { jobs, start, dismiss, busy } = useJobs(onJobSettled, setError);

  useEffect(() => {
    load();
    loadImages();
  }, [load, loadImages]);

  const rows = useMemo(() => {
    const byImage = new Map<string, ImageRow>();
    const rowFor = (image: string): ImageRow => {
      let row = byImage.get(image);
      if (!row) {
        row = { image, inUse: running.has(image), inCompose: composeImages.has(image) };
        byImage.set(image, row);
      }
      return row;
    };
    running.forEach((image) => rowFor(image));
    composeImages.forEach((image) => rowFor(image));
    scans.forEach((scan) => {
      rowFor(scan.image).scan = scan;
    });
    updates.forEach((update) => {
      rowFor(update.image).update = update;
    });
    // Attach local images to the rows that name them, and list the ones
    // nothing else mentions — those are the usual cleanup candidates.
    const byTag = new Map<string, ImageRow>();
    byImage.forEach((row) => byTag.set(withDefaultTag(row.image), row));
    localImages.forEach((localImage) =>
      localImage.tags.forEach((tag) => {
        const row = byTag.get(withDefaultTag(tag)) ?? rowFor(tag);
        row.local = localImage;
        if (localImage.used_by.some((imageUser) => imageUser.running)) row.inUse = true;
      }),
    );

    const needle = filter.trim().toLowerCase();
    return [...byImage.values()]
      .filter((row) => !needle || row.image.toLowerCase().includes(needle))
      .sort((left, right) => {
        const [leftCritical, leftHigh, leftUpdate, leftName] = rank(left);
        const [rightCritical, rightHigh, rightUpdate, rightName] = rank(right);
        return (
          leftCritical - rightCritical ||
          leftHigh - rightHigh ||
          leftUpdate - rightUpdate ||
          leftName.localeCompare(rightName)
        );
      });
  }, [scans, updates, running, composeImages, localImages, filter]);

  const remove = useCallback(
    async (removeImage: () => Promise<string>): Promise<void> => {
      setRemoving(true);
      setError(null);
      setNotice(null);
      try {
        setNotice(await removeImage());
      } catch (removeError) {
        setError((removeError as Error).message);
      } finally {
        setRemoving(false);
        loadImages();
      }
    },
    [loadImages],
  );

  const onDelete = useCallback(
    async (row: ImageRow): Promise<void> => {
      const stoppedContainers = (row.local?.used_by ?? []).map((imageUser) => imageUser.name);
      const confirmed = await confirm({
        title: t("Delete image {name}?", { name: row.image }),
        message: stoppedContainers.length
          ? t(
              "Stopped container(s) {names} still use it, so Docker will only untag it. Remove those containers to free the space.",
              { names: stoppedContainers.join(", ") },
            )
          : t("It will need to be pulled again to be used."),
        confirmLabel: t("Delete"),
        tone: "danger",
      });
      if (!confirmed) return;
      remove(async () => {
        await api.deleteImage(row.image, stoppedContainers.length > 0);
        return t("Image \"{name}\" removed.", { name: row.image });
      });
    },
    [remove, confirm, t],
  );

  const onPrune = useCallback(
    async (all: boolean): Promise<void> => {
      const confirmed = await confirm(
        all
          ? {
              title: t("Prune unused images?"),
              message: t(
                "Removes every image no container uses, running or stopped. They will need to be pulled again.",
              ),
              confirmLabel: t("Prune unused"),
              tone: "danger",
            }
          : {
              title: t("Prune dangling images?"),
              message: t("Removes untagged images left behind by pulls and builds."),
              confirmLabel: t("Prune dangling"),
              tone: "danger",
            },
      );
      if (!confirmed) return;
      start(() => api.pruneImages(all));
    },
    [start, confirm, t],
  );

  const openDetail = useCallback(async (scan: ScanSummary): Promise<void> => {
    try {
      setDetail(await api.getScan(scan.id));
    } catch (scanError) {
      setError((scanError as Error).message);
    }
  }, []);

  return (
    <div>
      <div className="row-between">
        <h1>{t("Images")}</h1>
        <div className="button-row inline">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            title={t("Trivy scan of every image used by a running container")}
            onClick={() => start(api.scanRunning)}
          >
            <ShieldCheck size={15} /> {t("Scan running")}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            title={t("Trivy scan of every image referenced by a Compose file")}
            onClick={() => start(api.scanCompose)}
          >
            <ShieldCheck size={15} /> {t("Scan Compose")}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            title={t("Compare local image digests against their registries")}
            onClick={() => start(() => api.checkUpdates())}
          >
            <ArrowUpCircle size={15} /> {t("Check updates")}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={removing || busy}
            title={t("Remove untagged images left behind by pulls and builds")}
            onClick={() => onPrune(false)}
          >
            <Trash2 size={15} /> {t("Prune dangling")}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={removing || busy}
            title={t("Remove every image no container uses")}
            onClick={() => onPrune(true)}
          >
            <Trash2 size={15} /> {t("Prune unused")}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              load();
              loadImages();
            }}
          >
            <RefreshCw size={15} /> {t("Refresh")}
          </button>
        </div>
      </div>

      <JobList jobs={jobs} onDismiss={dismiss} />
      {error && <div className="error">{error}</div>}
      {notice && <div className="output ok" style={{ padding: "0.75rem" }}>{notice}</div>}

      <div className="button-row">
        <input
          placeholder={t("Filter images…")}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
        <span className="muted">
          {rows.length === 1
            ? t("{count} image", { count: rows.length })
            : t("{count} images", { count: rows.length })}
        </span>
      </div>

      {loading ? (
        <div className="empty">{t("Loading…")}</div>
      ) : rows.length === 0 ? (
        <div className="empty">
          {t("No images known yet. Start a stack or add a Compose file to the repo.")}
        </div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>{t("Image")}</th>
              <th>{t("CVEs")}</th>
              <th>{t("Fixable")}</th>
              <th>{t("Update")}</th>
              <th>{t("Last scanned")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.image}>
                <td>
                  <div className="icon-link">{row.image}</div>
                  <div className="muted">
                    {row.inUse && <span className="badge running">{t("running")}</span>}{" "}
                    {row.inCompose && <span className="badge">compose</span>}{" "}
                    {row.local && <span>{formatBytes(row.local.size)}</span>}
                  </div>
                </td>
                <td>
                  <ScanBadge
                    scan={row.scan}
                    pending={false}
                    onScan={() => start(() => api.scanImage(row.image))}
                    onOpen={openDetail}
                  />
                </td>
                <td>{row.scan && !row.scan.error ? row.scan.fixable : "—"}</td>
                <td>
                  <UpdateBadge update={row.update} />
                </td>
                <td className="muted">
                  {formatDate(row.scan?.scanned_at, t("never"))}
                </td>
                <td>
                  <div className="button-row inline">
                    <button
                      type="button"
                      className="secondary small"
                      disabled={busy}
                      onClick={() => start(() => api.scanImage(row.image))}
                    >
                      <ShieldCheck size={14} /> {t("Scan")}
                    </button>
                    <button
                      type="button"
                      className="secondary small"
                      disabled={busy}
                      onClick={() => start(() => api.checkUpdates([row.image]))}
                    >
                      <ArrowUpCircle size={14} /> {t("Check")}
                    </button>
                    {row.local && (
                      <button
                        type="button"
                        className="secondary small"
                        disabled={removing || row.inUse}
                        title={
                          row.inUse
                            ? t("Image is used by a running container")
                            : t("Remove image from the local store")
                        }
                        onClick={() => onDelete(row)}
                      >
                        <Trash2 size={14} /> {t("Delete")}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {detail && <FindingsPanel detail={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function FindingsPanel({ detail, onClose }: { detail: ScanDetail; onClose: () => void }) {
  const t = useT();
  return (
    <div className="drawer">
      <div className="log-header">
        <div>
          <strong>{detail.image}</strong>{" "}
          <span className="muted">
            — {t("scanned {date}", { date: formatDate(detail.scanned_at) })}
          </span>
        </div>
        <button type="button" className="secondary small" onClick={onClose}>
          <X size={15} /> {t("Close")}
        </button>
      </div>

      <div className="drawer-body">
        <ScanFindings detail={detail} />
      </div>
    </div>
  );
}
