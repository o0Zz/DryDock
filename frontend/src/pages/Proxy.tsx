import { CheckCircle2, CircleAlert, ExternalLink, Plus, RefreshCw, Save } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { VisibilityBadge } from "../components/ExposurePanel";
import { useT } from "../i18n";
import type { ProxyOverview } from "../types";

/** What Traefik exposes, from the labels in the repo, and whether the proxy runs. */
export default function Proxy() {
  const t = useT();
  const { user } = useAuth();
  const [proxy, setProxy] = useState<ProxyOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    try {
      setProxy(await api.getProxy());
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !proxy) return <div className="error">{t("Failed to load: {error}", { error })}</div>;
  if (!proxy) return <div>{t("Loading…")}</div>;

  return (
    <div>
      <div className="row-between">
        <h1>{t("Proxy")}</h1>
        <button type="button" className="secondary" onClick={() => void load()}>
          <RefreshCw size={15} /> {t("Reload")}
        </button>
      </div>
      <p className="muted">
        {t(
          "Traefik routes https://<name>.<domain> to your containers. Expose a service from its stack page (Expose, beside the Compose editor). DryDock only writes the labels: the traffic never goes through it.",
        )}
      </p>
      {error && <div className="error">{error}</div>}

      <section className="section">
        <h2>{t("Status")}</h2>
        {!proxy.docker_available ? (
          <div className="notice">{t("Docker is unreachable: the proxy state is unknown.")}</div>
        ) : (
          <ul className="fact-list">
            <li>
              <span className="muted">{t("Traefik")}</span>
              <Check ok={proxy.traefik?.running ?? false}>
                {proxy.traefik ? (
                  <Link to={`/containers/${proxy.traefik.id}`}>
                    {proxy.traefik.name}
                    {proxy.traefik.running ? "" : ` (${t("stopped")})`}
                  </Link>
                ) : (
                  t("no container")
                )}
              </Check>
            </li>
            <li>
              <span className="muted">{t("Network")}</span>
              <Check ok={proxy.network_exists ?? false}>
                <code>{proxy.network}</code>
                {!proxy.network_exists && ` (${t("created by the Traefik stack on up")})`}
              </Check>
            </li>
          </ul>
        )}
        {proxy.docker_available && !proxy.traefik && (
          <div className="button-row">
            <Link className="button" to="/projects/new?template=traefik">
              <Plus size={15} /> {t("Create the Traefik stack")}
            </Link>
          </div>
        )}
      </section>

      <ProxySettings proxy={proxy} editable={user?.is_admin ?? false} onSaved={load} />

      <section className="section">
        <h2>
          {t("Exposed services")} <span className="muted">{proxy.routes.length}</span>
        </h2>
        {proxy.routes.length === 0 ? (
          <div className="empty">{t("Nothing is exposed yet.")}</div>
        ) : (
          <table className="projects-table">
            <thead>
              <tr>
                <th>{t("Host")}</th>
                <th>{t("Visibility")}</th>
                <th>{t("Stack")}</th>
                <th>{t("Service")}</th>
                <th>{t("Port")}</th>
                <th>{t("State")}</th>
              </tr>
            </thead>
            <tbody>
              {proxy.routes.map((route) => (
                <tr key={`${route.project_id}/${route.service}`}>
                  <td>
                    {route.hosts.map((host) => (
                      <div key={host}>
                        <a href={`https://${host}`} target="_blank" rel="noreferrer">
                          {host} <ExternalLink size={12} />
                        </a>
                      </div>
                    ))}
                  </td>
                  <td>
                    <VisibilityBadge exposure={route} />
                  </td>
                  <td>
                    <Link to={`/projects/${route.project_id}`}>{route.project_name}</Link>
                  </td>
                  <td>{route.service}</td>
                  <td>{route.port ?? "—"}</td>
                  <td>
                    <span className={`badge ${route.running ? "running" : "exited"}`}>
                      {route.running ? t("running") : t("not running")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Check({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span className={ok ? "diff-added" : "diff-removed"}>
      {ok ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}{" "}
      <span style={{ color: "var(--text)" }}>{children}</span>
    </span>
  );
}

function ProxySettings({
  proxy,
  editable,
  onSaved,
}: {
  proxy: ProxyOverview;
  editable: boolean;
  onSaved: () => Promise<void>;
}) {
  const t = useT();
  const [domain, setDomain] = useState(proxy.domain);
  const [network, setNetwork] = useState(proxy.network);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const dirty = domain !== proxy.domain || network !== proxy.network;

  async function save(event: FormEvent): Promise<void> {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.updateSettings({ proxy_domain: domain.trim(), proxy_network: network.trim() });
      await onSaved();
    } catch (saveError) {
      setError((saveError as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="section">
      <h2>{t("Settings")}</h2>
      <form onSubmit={save}>
        <label className="field">
          {t("Domain")}
          <input
            type="text"
            placeholder="example.org"
            disabled={!editable}
            value={domain}
            onChange={(event) => setDomain(event.target.value)}
          />
          <span className="muted">
            {t(
              "A bare name in the Exposure panel becomes <name>.<domain>. Use the domain of the Traefik stack's wildcard certificate.",
            )}
          </span>
        </label>
        <label className="field">
          {t("Docker network")}
          <input
            type="text"
            disabled={!editable}
            value={network}
            onChange={(event) => setNetwork(event.target.value)}
          />
          <span className="muted">
            {t("Exposed services join it so Traefik can reach them. The Traefik stack creates it.")}
          </span>
        </label>
        {error && <div className="error">{error}</div>}
        {editable && (
          <div className="button-row">
            <button type="submit" disabled={!dirty || saving}>
              <Save size={15} /> {saving ? t("Saving…") : t("Save")}
            </button>
          </div>
        )}
      </form>
    </section>
  );
}
