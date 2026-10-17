import { ChevronLeft, Download, File, FileSymlink, Folder, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { formatBytes, formatDate } from "../format";
import { useT } from "../i18n";
import type { VolumeEntry, VolumeListing } from "../types";

const ENTRY_ICONS = { dir: Folder, file: File, link: FileSymlink, other: File };

function joinPath(folder: string, name: string): string {
  return folder === "/" ? `/${name}` : `${folder}/${name}`;
}

export default function VolumeFiles() {
  const t = useT();
  const { name = "" } = useParams();
  // The folder lives in the URL, so back/forward and reloads keep it.
  const [searchParams, setSearchParams] = useSearchParams();
  const path = searchParams.get("path") || "/";
  const [listing, setListing] = useState<VolumeListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback((): void => {
    setLoading(true);
    api
      .listVolumeFiles(name, path)
      .then((result) => {
        setListing(result);
        setError(null);
      })
      .catch((loadError: Error) => setError(loadError.message))
      .finally(() => setLoading(false));
  }, [name, path]);

  useEffect(() => {
    load();
  }, [load]);

  function open(folder: string): void {
    setSearchParams(folder === "/" ? {} : { path: folder });
  }

  const segments = path.split("/").filter(Boolean);

  function renderName(entry: VolumeEntry) {
    const Icon = ENTRY_ICONS[entry.type];
    const label = (
      <>
        <Icon size={15} /> {entry.name}
      </>
    );
    if (entry.type === "dir") {
      return (
        <button
          type="button"
          className="linklike"
          style={{ fontSize: "inherit" }}
          onClick={() => open(joinPath(listing?.path ?? path, entry.name))}
        >
          {label}
        </button>
      );
    }
    return <span className="icon-link">{label}</span>;
  }

  return (
    <div>
      <div className="crumb">
        <Link to="/volumes">
          <ChevronLeft size={15} /> {t("Volumes")}
        </Link>
      </div>
      <div className="row-between">
        <h1>
          {name} <span className="badge">{t("read-only")}</span>
        </h1>
        <div className="button-row inline">
          <button type="button" className="secondary" disabled={loading} onClick={load}>
            <RefreshCw size={15} /> {t("Refresh")}
          </button>
        </div>
      </div>

      <div className="muted" style={{ marginBottom: "0.75rem" }}>
        <button type="button" className="linklike" onClick={() => open("/")}>
          {name}
        </button>
        {segments.map((segment, index) => (
          <span key={index}>
            {" / "}
            <button
              type="button"
              className="linklike"
              onClick={() => open(`/${segments.slice(0, index + 1).join("/")}`)}
            >
              {segment}
            </button>
          </span>
        ))}
      </div>

      {error && <div className="error">{error}</div>}
      {listing?.truncated && (
        <div className="muted">
          {t("Showing the first {count} entries only.", { count: listing.entries.length })}
        </div>
      )}

      {!listing ? (
        !error && <div className="empty">{t("Loading…")}</div>
      ) : listing.entries.length === 0 ? (
        <div className="empty">{t("This folder is empty.")}</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>{t("Name")}</th>
              <th>{t("Size")}</th>
              <th>{t("Modified")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {listing.entries.map((entry) => (
              <tr key={entry.name}>
                <td>{renderName(entry)}</td>
                <td className="muted">{entry.type === "file" ? formatBytes(entry.size) : "—"}</td>
                <td className="muted">{formatDate(entry.modified_at)}</td>
                <td>
                  {entry.type === "file" && (
                    <a
                      className="button secondary small"
                      href={api.volumeFileUrl(name, joinPath(listing.path, entry.name))}
                      download={entry.name}
                    >
                      <Download size={14} /> {t("Download")}
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
