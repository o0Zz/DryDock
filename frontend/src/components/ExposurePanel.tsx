import { Check, ExternalLink, Globe, Lock, RefreshCw, Trash2, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useT } from "../i18n";
import type { ProxyOverview, ServiceExposure } from "../types";
import DiffView from "./DiffView";

/**
 * Beside the Compose editor: give a service a host name behind the reverse proxy,
 * private (an IP allowlist) or public. Each change rewrites the editor's content;
 * saving and `up` stay with the editor.
 */
export default function ExposurePanel({
  projectId,
  content,
  onApply,
  onClose,
}: {
  projectId: string;
  content: string;
  onApply: (next: string) => void;
  onClose: () => void;
}) {
  const t = useT();
  const [proxy, setProxy] = useState<ProxyOverview | null>(null);
  const [services, setServices] = useState<ServiceExposure[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [lastChange, setLastChange] = useState<{ before: string; after: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .getProxy()
      .then(setProxy)
      .catch(() => undefined);
  }, []);

  // The editor may hold half-typed YAML: wait for a pause, keep the last good list.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      api
        .exposureServices(projectId, content)
        .then((list) => {
          setServices(list);
          setError(null);
        })
        .catch((loadError: Error) => setError(loadError.message));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [projectId, content]);

  async function change(run: () => Promise<{ content: string }>): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const result = await run();
      setLastChange({ before: content, after: result.content });
      onApply(result.content);
      return true;
    } catch (changeError) {
      setError((changeError as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  // Either one down means a change here never reaches the proxy.
  const notRunning =
    proxy?.docker_available && (!proxy.container?.running || !proxy.sync?.running);

  return (
    <aside className="assistant">
      <div className="assistant-header">
        <strong>
          <Globe size={15} /> {t("Exposure")}
        </strong>
        <div className="button-row inline">
          <button
            type="button"
            className="secondary small icon-only"
            title={t("Close")}
            onClick={onClose}
          >
            <X size={14} />
          </button>
        </div>
      </div>

      <div className="assistant-body">
        {notRunning && (
          <div className="notice">
            {t("The proxy or its sync is not running: exposed services are not reachable yet.")}{" "}
            <Link to="/proxy">{t("Set up the proxy")}</Link>
          </div>
        )}
        {services === null && !error && <div className="muted">{t("Loading…")}</div>}
        {services?.map((exposure) =>
          editing === exposure.service ? (
            <ExposeForm
              key={exposure.service}
              exposure={exposure}
              domain={proxy?.domain ?? ""}
              busy={busy}
              onCancel={() => setEditing(null)}
              onSubmit={async (request) => {
                const done = await change(() =>
                  api.exposeService(projectId, content, { service: exposure.service, ...request }),
                );
                if (done) setEditing(null);
              }}
            />
          ) : (
            <ServiceRow
              key={exposure.service}
              exposure={exposure}
              busy={busy}
              onEdit={() => setEditing(exposure.service)}
              onRemove={() =>
                void change(() => api.unexposeService(projectId, content, exposure.service))
              }
            />
          ),
        )}
        {error && <div className="error">{error}</div>}
        {lastChange && <LastChange {...lastChange} current={content} />}
      </div>
    </aside>
  );
}

function ServiceRow({
  exposure,
  busy,
  onEdit,
  onRemove,
}: {
  exposure: ServiceExposure;
  busy: boolean;
  onEdit: () => void;
  onRemove: () => void;
}) {
  const t = useT();
  return (
    <div className="exposure-row">
      <div className="exposure-row-header">
        <strong>{exposure.service}</strong>
        <VisibilityBadge exposure={exposure} />
      </div>
      {exposure.hosts.map((host) => (
        <a key={host} href={`https://${host}`} target="_blank" rel="noreferrer">
          {host} <ExternalLink size={12} />
        </a>
      ))}
      {exposure.exposed && exposure.port !== null && (
        <span className="muted">{t("to container port {port}", { port: exposure.port })}</span>
      )}
      {exposure.legacy && (
        <span className="notice">
          {t("Has labels of an older proxy setup (traefik.*, swag). Expose replaces them.")}
        </span>
      )}
      {exposure.blocked ? (
        <span className="muted">{t("Cannot be exposed: {reason}", { reason: exposure.blocked })}</span>
      ) : (
        <div className="button-row inline">
          <button type="button" className="small" disabled={busy} onClick={onEdit}>
            {exposure.exposed ? t("Change") : t("Expose")}
          </button>
          {exposure.exposed && (
            <button type="button" className="secondary small" disabled={busy} onClick={onRemove}>
              <Trash2 size={13} /> {t("Remove")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function VisibilityBadge({ exposure }: { exposure: { exposed?: boolean; public: boolean } }) {
  const t = useT();
  if (exposure.exposed === false) return <span className="badge">{t("Not exposed")}</span>;
  return exposure.public ? (
    <span className="badge paused" title={t("Reachable from the internet")}>
      <Globe size={12} /> {t("Public")}
    </span>
  ) : (
    <span className="badge running" title={t("Allowed IPs only: LAN, public IP, trusted IPs")}>
      <Lock size={12} /> {t("Private")}
    </span>
  );
}

function ExposeForm({
  exposure,
  domain,
  busy,
  onCancel,
  onSubmit,
}: {
  exposure: ServiceExposure;
  domain: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (request: { host: string; port: number; public: boolean }) => Promise<void>;
}) {
  const t = useT();
  const suffix = domain ? `.${domain}` : "";
  const currentHost = exposure.hosts[0] ?? "";
  // Shown without the proxy domain when it ends with it.
  const [host, setHost] = useState(
    suffix && currentHost.endsWith(suffix)
      ? currentHost.slice(0, -suffix.length)
      : currentHost || exposure.service,
  );
  const [port, setPort] = useState(String(exposure.port ?? exposure.ports[0] ?? ""));
  const [isPublic, setPublic] = useState(exposure.exposed && exposure.public);
  const fullHost = host.includes(".") || !domain ? host : `${host}${suffix}`;
  const portNumber = Number(port);
  const valid = host.trim() !== "" && Number.isInteger(portNumber) && portNumber > 0;

  function submit(event: FormEvent): void {
    event.preventDefault();
    if (valid) void onSubmit({ host: host.trim(), port: portNumber, public: isPublic });
  }

  return (
    <form className="exposure-row" onSubmit={submit}>
      <div className="exposure-row-header">
        <strong>{exposure.service}</strong>
      </div>
      <label>
        {t("Host name")}
        <div className="exposure-host">
          <input
            type="text"
            value={host}
            autoFocus
            onChange={(event) => setHost(event.target.value)}
          />
          {suffix && !host.includes(".") && <span className="muted">{suffix}</span>}
        </div>
      </label>
      {!domain && (
        <span className="muted">
          {t("No proxy domain set: type the full host name, or set the domain on the Proxy page.")}
        </span>
      )}
      <label>
        {t("Container port")}
        <input
          type="number"
          min={1}
          max={65535}
          list={`ports-${exposure.service}`}
          value={port}
          onChange={(event) => setPort(event.target.value)}
        />
        <datalist id={`ports-${exposure.service}`}>
          {exposure.ports.map((candidate) => (
            <option key={candidate} value={candidate} />
          ))}
        </datalist>
      </label>
      <fieldset className="exposure-visibility">
        <label className="checkbox-label">
          <input type="radio" checked={!isPublic} onChange={() => setPublic(false)} />
          <Lock size={13} /> {t("Private: allowed IPs only")}
        </label>
        <label className="checkbox-label">
          <input type="radio" checked={isPublic} onChange={() => setPublic(true)} />
          <Globe size={13} /> {t("Public: reachable from the internet")}
        </label>
      </fieldset>
      {isPublic && (
        <span className="muted">
          {t("Anyone who knows {host} can reach it. Make sure the app has its own login.", {
            host: fullHost || "…",
          })}
        </span>
      )}
      <div className="button-row inline">
        <button type="submit" className="small" disabled={!valid || busy}>
          {busy ? <RefreshCw size={13} className="spin" /> : <Check size={13} />}{" "}
          {t("Apply to editor")}
        </button>
        <button type="button" className="secondary small" onClick={onCancel}>
          {t("Cancel")}
        </button>
      </div>
    </form>
  );
}

/** The editor change the last action made, since the rewrite may touch formatting too. */
function LastChange({ before, after, current }: { before: string; after: string; current: string }) {
  const t = useT();
  if (before === after) return null;
  return (
    <div className="assistant-proposal">
      <div className="assistant-proposal-header">
        <span>{t("Last change")}</span>
        {current === after && (
          <span className="muted">
            <Check size={14} /> {t("In the editor, not saved yet")}
          </span>
        )}
      </div>
      <DiffView before={before} after={after} />
    </div>
  );
}
