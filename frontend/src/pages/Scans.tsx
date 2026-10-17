import {
  ArrowUpCircle,
  CheckCircle2,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import JobList from "../components/JobList";
import ScanBadge from "../components/ScanBadge";
import { useJobs } from "../hooks/useJobs";
import type { Job, LocalImage, ScanDetail, ScanSummary, UpdateSummary } from "../types";

interface Row {
  image: string;
  scan?: ScanSummary;
  update?: UpdateSummary;
  /** Present when the image exists in the local Docker image store. */
  local?: LocalImage;
  inUse: boolean;
  inCompose: boolean;
}

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"];

function severityClass(severity: string): string {
  if (severity === "CRITICAL") return "exited";
  if (severity === "HIGH") return "paused";
  return "";
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/** "nginx" and "nginx:latest" name the same image; Docker always lists the latter. */
function withDefaultTag(image: string): string {
  if (image.includes("@")) return image;
  return image.slice(image.lastIndexOf("/") + 1).includes(":") ? image : `${image}:latest`;
}

/** Sort worst first: criticals, then highs, then pending updates, then name. */
function rank(row: Row): [number, number, number, string] {
  return [
    row.scan?.critical ? 0 : 1,
    row.scan?.high ? 0 : 1,
    row.update?.update_available || row.update?.newest_tag ? 0 : 1,
    row.image,
  ];
}

export default function Scans() {
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

  const load = useCallback(async () => {
    try {
      const [scanList, updateList] = await Promise.all([api.listScans(), api.listUpdates()]);
      setScans(scanList);
      setUpdates(updateList);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadImages = useCallback(async () => {
    // Images worth listing even when never scanned: anything running, plus
    // anything a Compose file references. Docker being down is not fatal here.
    const [containers, projects, images] = await Promise.all([
      api.listContainers().catch(() => []),
      api.listProjects().catch(() => []),
      api.listImages().catch(() => []),
    ]);
    setLocalImages(images);
    setRunning(new Set(containers.filter((c) => c.state === "running").map((c) => c.image)));
    setComposeImages(
      new Set(
        projects.flatMap(
          (p) => p.services.map((s) => s.image).filter(Boolean) as string[],
        ),
      ),
    );
  }, []);

  const { jobs, track, dismiss, busy } = useJobs(load);

  useEffect(() => {
    load();
    loadImages();
  }, [load, loadImages]);

  const rows = useMemo(() => {
    const byImage = new Map<string, Row>();
    const ensure = (image: string): Row => {
      let row = byImage.get(image);
      if (!row) {
        row = { image, inUse: running.has(image), inCompose: composeImages.has(image) };
        byImage.set(image, row);
      }
      return row;
    };
    running.forEach((i) => ensure(i));
    composeImages.forEach((i) => ensure(i));
    scans.forEach((s) => {
      ensure(s.image).scan = s;
    });
    updates.forEach((u) => {
      ensure(u.image).update = u;
    });
    // Attach local images to the rows that name them, and list the ones
    // nothing else mentions — those are the usual cleanup candidates.
    const byTag = new Map<string, Row>();
    byImage.forEach((row) => byTag.set(withDefaultTag(row.image), row));
    localImages.forEach((img) =>
      img.tags.forEach((tag) => {
        const row = byTag.get(withDefaultTag(tag)) ?? ensure(tag);
        row.local = img;
        if (img.used_by.some((u) => u.running)) row.inUse = true;
      }),
    );

    const needle = filter.trim().toLowerCase();
    return [...byImage.values()]
      .filter((r) => !needle || r.image.toLowerCase().includes(needle))
      .sort((a, b) => {
        const [ac, ah, au, an] = rank(a);
        const [bc, bh, bu, bn] = rank(b);
        return ac - bc || ah - bh || au - bu || an.localeCompare(bn);
      });
  }, [scans, updates, running, composeImages, localImages, filter]);

  const start = useCallback(
    async (fn: () => Promise<Job>) => {
      setError(null);
      try {
        track(await fn());
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [track],
  );

  const remove = useCallback(
    async (fn: () => Promise<string>) => {
      setRemoving(true);
      setError(null);
      setNotice(null);
      try {
        setNotice(await fn());
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setRemoving(false);
        loadImages();
      }
    },
    [loadImages],
  );

  const onDelete = useCallback(
    (row: Row) => {
      const stopped = (row.local?.used_by ?? []).map((u) => u.name);
      const message = stopped.length
        ? `Delete image "${row.image}"? Stopped container(s) ${stopped.join(", ")} ` +
          "still use it, so Docker will only untag it. Remove those containers to free the space."
        : `Delete image "${row.image}"?`;
      if (!window.confirm(message)) return;
      remove(async () => {
        await api.deleteImage(row.image, stopped.length > 0);
        return `Image "${row.image}" removed.`;
      });
    },
    [remove],
  );

  const onPrune = useCallback(
    (all: boolean) => {
      const message = all
        ? "Remove every image not used by a container (running or stopped)? " +
          "They will need to be pulled again."
        : "Remove dangling (untagged) images?";
      if (!window.confirm(message)) return;
      remove(async () => {
        const res = await api.pruneImages(all);
        return `Pruned ${res.deleted.length} image(s), reclaimed ${formatBytes(res.space_reclaimed)}.`;
      });
    },
    [remove],
  );

  const openDetail = useCallback(async (scan: ScanSummary) => {
    try {
      setDetail(await api.getScan(scan.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  return (
    <div>
      <div className="row-between">
        <h1>Scans &amp; updates</h1>
        <div className="button-row inline">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            title="Trivy scan of every image used by a running container"
            onClick={() => start(api.scanRunning)}
          >
            <ShieldCheck size={15} /> Scan running
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            title="Trivy scan of every image referenced by a Compose file"
            onClick={() => start(api.scanCompose)}
          >
            <ShieldCheck size={15} /> Scan Compose
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            title="Compare local image digests against their registries"
            onClick={() => start(() => api.checkUpdates())}
          >
            <ArrowUpCircle size={15} /> Check updates
          </button>
          <button
            type="button"
            className="secondary"
            disabled={removing}
            title="Remove untagged images left behind by pulls and builds"
            onClick={() => onPrune(false)}
          >
            <Trash2 size={15} /> Prune dangling
          </button>
          <button
            type="button"
            className="secondary"
            disabled={removing}
            title="Remove every image no container uses"
            onClick={() => onPrune(true)}
          >
            <Trash2 size={15} /> Prune unused
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              load();
              loadImages();
            }}
          >
            <RefreshCw size={15} /> Refresh
          </button>
        </div>
      </div>

      <JobList jobs={jobs} onDismiss={dismiss} />
      {error && <div className="error">{error}</div>}
      {notice && <div className="output ok" style={{ padding: "0.75rem" }}>{notice}</div>}

      <div className="button-row">
        <input
          placeholder="Filter images…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <span className="muted">
          {rows.length} image{rows.length === 1 ? "" : "s"}
        </span>
      </div>

      {loading ? (
        <div className="empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="empty">
          No images known yet. Start a stack or add a Compose file to the repo.
        </div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Image</th>
              <th>CVEs</th>
              <th>Fixable</th>
              <th>Update</th>
              <th>Last scanned</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.image}>
                <td>
                  <div className="icon-link">{row.image}</div>
                  <div className="muted">
                    {row.inUse && <span className="badge running">running</span>}{" "}
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
                  <UpdateCell update={row.update} />
                </td>
                <td className="muted">
                  {row.scan ? new Date(row.scan.scanned_at).toLocaleString() : "never"}
                </td>
                <td>
                  <div className="button-row inline">
                    <button
                      type="button"
                      className="secondary small"
                      disabled={busy}
                      onClick={() => start(() => api.scanImage(row.image))}
                    >
                      <ShieldCheck size={14} /> Scan
                    </button>
                    <button
                      type="button"
                      className="secondary small"
                      disabled={busy}
                      onClick={() => start(() => api.checkUpdates([row.image]))}
                    >
                      <ArrowUpCircle size={14} /> Check
                    </button>
                    {row.local && (
                      <button
                        type="button"
                        className="secondary small"
                        disabled={removing || row.inUse}
                        title={
                          row.inUse
                            ? "Image is used by a running container"
                            : "Remove image from the local store"
                        }
                        onClick={() => onDelete(row)}
                      >
                        <Trash2 size={14} /> Delete
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

function UpdateCell({ update }: { update: UpdateSummary | undefined }) {
  if (!update) return <span className="muted">not checked</span>;
  const checked = new Date(update.checked_at).toLocaleString();
  // A newer version tag wins over digest status: it is what a pinned tag needs,
  // and it is known even when the image is not pulled locally.
  if (update.newest_tag) {
    const lines = [`Checked ${checked}`, `Newest tag: ${update.newest_tag}`];
    if (update.newest_same_major_tag) {
      lines.push(`Newest in current major: ${update.newest_same_major_tag}`);
    }
    if (update.update_available) lines.push("Current tag was also rebuilt (run pull).");
    lines.push("Change the image tag in the compose file to upgrade.");
    return (
      <span className="badge paused" title={lines.join("\n")}>
        <ArrowUpCircle size={12} /> {update.newest_tag}
        {update.newest_same_major_tag && ` · ${update.newest_same_major_tag}`}
      </span>
    );
  }
  if (update.error) {
    return (
      <span className="badge" title={update.error}>
        unknown
      </span>
    );
  }
  if (!update.update_available) {
    const tagNote = update.tag_error
      ? `\nTag check failed: ${update.tag_error}`
      : "\nNo newer version tag found.";
    return (
      <span className="badge running" title={`Checked ${checked}${tagNote}`}>
        <CheckCircle2 size={12} /> up to date
      </span>
    );
  }
  return (
    <span
      className="badge paused"
      title={
        `Checked ${checked}\nlocal  ${update.local_digest}\n` +
        `remote ${update.remote_digest}\nSame tag was rebuilt. Run "pull" on the project to update.`
      }
    >
      <ArrowUpCircle size={12} /> available
    </span>
  );
}

function FindingsPanel({ detail, onClose }: { detail: ScanDetail; onClose: () => void }) {
  const [severity, setSeverity] = useState<string>("ALL");

  const findings = useMemo(
    () =>
      severity === "ALL"
        ? detail.findings
        : detail.findings.filter((f) => f.severity === severity),
    [detail.findings, severity],
  );

  return (
    <div className="drawer">
      <div className="log-header">
        <div>
          <strong>{detail.image}</strong>{" "}
          <span className="muted">
            — scanned {new Date(detail.scanned_at).toLocaleString()}
          </span>
        </div>
        <button type="button" className="secondary small" onClick={onClose}>
          <X size={15} /> Close
        </button>
      </div>

      <div className="drawer-body">
        {detail.error ? (
          <div className="error">{detail.error}</div>
        ) : (
          <>
            <div className="button-row">
              {["ALL", ...SEVERITY_ORDER].map((level) => (
                <button
                  key={level}
                  type="button"
                  className={severity === level ? "small" : "secondary small"}
                  onClick={() => setSeverity(level)}
                >
                  {level.toLowerCase()}
                </button>
              ))}
            </div>
            {detail.truncated && (
              <div className="muted">
                Showing the most severe findings only — the full list was capped.
              </div>
            )}
            {findings.length === 0 ? (
              <div className="empty">No vulnerabilities at this level.</div>
            ) : (
              <table className="projects-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>CVE</th>
                    <th>Package</th>
                    <th>Installed</th>
                    <th>Fixed in</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map((f, i) => (
                    <tr key={`${f.vulnerability_id}-${f.package_name}-${i}`}>
                      <td>
                        <span className={`badge ${severityClass(f.severity)}`}>
                          {f.severity.toLowerCase()}
                        </span>
                      </td>
                      <td>
                        {f.primary_url ? (
                          <a
                            className="icon-link"
                            href={f.primary_url}
                            target="_blank"
                            rel="noreferrer"
                            title={f.title ?? undefined}
                          >
                            {f.vulnerability_id} <ExternalLink size={13} />
                          </a>
                        ) : (
                          <span title={f.title ?? undefined}>{f.vulnerability_id}</span>
                        )}
                      </td>
                      <td>
                        {f.package_name}
                        {f.target && <div className="muted">{f.target}</div>}
                      </td>
                      <td className="muted">{f.installed_version ?? "—"}</td>
                      <td>
                        {f.fixed_version ? (
                          <span className="badge running">{f.fixed_version}</span>
                        ) : (
                          <span className="muted">no fix</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </div>
  );
}
