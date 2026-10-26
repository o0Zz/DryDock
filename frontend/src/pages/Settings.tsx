import {
  CalendarClock,
  KeyRound,
  RefreshCw,
  Save,
  Server,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import AiSettings from "../components/AiSettings";
import ApiTokens from "../components/ApiTokens";
import ChangePassword from "../components/ChangePassword";
import GitCredentials from "../components/GitCredentials";
import RegistryCredentials from "../components/RegistryCredentials";
import { formatDate } from "../format";
import { msg, useT } from "../i18n";
import type { AppSettings, Job, SettingsPatch } from "../types";

type Tab = "schedules" | "credentials" | "ai" | "account" | "system";

const TABS: { id: Tab; label: string; icon: ReactNode; adminOnly?: boolean }[] = [
  { id: "schedules", label: msg("Schedules & alerts"), icon: <CalendarClock size={15} /> },
  { id: "credentials", label: msg("Credentials"), icon: <KeyRound size={15} />, adminOnly: true },
  { id: "ai", label: msg("AI assistant"), icon: <Sparkles size={15} />, adminOnly: true },
  { id: "account", label: msg("Account"), icon: <UserRound size={15} /> },
  { id: "system", label: msg("System"), icon: <Server size={15} /> },
];

export default function Settings() {
  const t = useT();
  const { user } = useAuth();
  // In the URL, so a reload or a shared link opens the same tab.
  const [searchParams, setSearchParams] = useSearchParams();
  const tabs = TABS.filter((candidate) => !candidate.adminOnly || user?.is_admin);
  const tab = tabs.find((candidate) => candidate.id === searchParams.get("tab"))?.id ?? "schedules";
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<SettingsPatch>({});
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async (): Promise<void> => {
    try {
      const [currentSettings, recentJobs] = await Promise.all([
        api.getSettings(),
        api.listJobs(10),
      ]);
      setSettings(currentSettings);
      setDraft({});
      setJobs(recentJobs);
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error && !settings) return <div className="error">{t("Failed to load settings: {error}", { error })}</div>;
  if (!settings) return <div>{t("Loading…")}</div>;

  // The draft holds only fields the user touched, so a save is always a patch.
  const formValues = { ...settings, ...draft };
  const dirty = Object.keys(draft).length > 0;

  function edit(patch: SettingsPatch): void {
    setDraft((previous) => ({ ...previous, ...patch }));
    setNotice(null);
  }

  async function runAutoUpdate(): Promise<void> {
    setError(null);
    try {
      await api.runAutoUpdate();
      setNotice(t("Auto-update started. Follow it in the jobs list."));
    } catch (runError) {
      setError((runError as Error).message);
    }
  }

  async function save(event: FormEvent): Promise<void> {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateSettings(draft);
      setSettings(updated);
      setDraft({});
      setNotice(t("Settings saved."));
    } catch (saveError) {
      setError((saveError as Error).message);
    } finally {
      setSaving(false);
    }
  }

  // Split around the placeholder so the inline element stays in place in every language.
  const [notifyBefore, notifyAfter] = t(
    "After a {scheduled} run, DryDock POSTs a JSON summary to this URL. Manual runs never notify.",
  ).split("{scheduled}");
  const [autoBefore, autoAfter] = t(
    "Pulls and recreates each running service labelled {label} when its tag was rebuilt or its git ref moved. A newer version tag is never applied, and services without the label are never touched.",
  ).split("{label}");
  const [envBefore, envAfter] = t(
    "Set with {variables} environment variables; restart to change.",
  ).split("{variables}");

  return (
    <div>
      <div className="row-between">
        <h1>{t("Settings")}</h1>
        <button type="button" className="secondary" onClick={load}>
          <RefreshCw size={15} /> {t("Reload")}
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {notice && (
        <div className="output ok padded">
          {notice}
        </div>
      )}
      <div className="tabs" role="tablist">
        {tabs.map((candidate) => (
          <button
            key={candidate.id}
            type="button"
            role="tab"
            aria-selected={tab === candidate.id}
            className={`tab ${tab === candidate.id ? "active" : ""}`}
            onClick={() => setSearchParams({ tab: candidate.id }, { replace: true })}
          >
            {candidate.icon} {t(candidate.label)}
            {/* The draft survives a tab change: flag it so it is not forgotten. */}
            {candidate.id === "schedules" && dirty && (
              <span className="tab-dot" title={t("Unsaved changes")} />
            )}
          </button>
        ))}
      </div>

      <div className="settings-panel" hidden={tab !== "schedules"}>
        {!user?.is_admin && (
          <p className="muted">
            {t("You are signed in as a standard user — these settings are read-only.")}
          </p>
        )}
        <form onSubmit={save}>
          <section className="section">
            <h2>{t("Schedules")}</h2>
            <div className="subsection">
              <h3>{t("CVE scans")}</h3>
              <p className="muted">
                {t("Runs a Trivy scan across every image used by a running container.")}
              </p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  disabled={!user?.is_admin}
                  checked={formValues.scan_schedule_enabled}
                  onChange={(event) => edit({ scan_schedule_enabled: event.target.checked })}
                />
                {t("Scan automatically")}
              </label>
              <div className="field-row">
                <label>
                  {t("Every (hours)")}
                  <input
                    type="number"
                    min={1}
                    max={720}
                    disabled={!user?.is_admin || !formValues.scan_schedule_enabled}
                    value={formValues.scan_interval_hours}
                    onChange={(event) => edit({ scan_interval_hours: Number(event.target.value) })}
                  />
                </label>
                <div className="muted">
                  {t("Next run: {date}", {
                    date: formatDate(settings.next_scan_run, t("not scheduled")),
                  })}
                </div>
              </div>
            </div>
            <div className="subsection">
              <h3>{t("Update checks")}</h3>
              <p className="muted">
                {t("Compares each image digest against its registry. No layers are downloaded.")}
              </p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  disabled={!user?.is_admin}
                  checked={formValues.update_check_enabled}
                  onChange={(event) => edit({ update_check_enabled: event.target.checked })}
                />
                {t("Check automatically")}
              </label>
              <div className="field-row">
                <label>
                  {t("Every (hours)")}
                  <input
                    type="number"
                    min={1}
                    max={720}
                    disabled={!user?.is_admin || !formValues.update_check_enabled}
                    value={formValues.update_check_interval_hours}
                    onChange={(event) =>
                      edit({ update_check_interval_hours: Number(event.target.value) })
                    }
                  />
                </label>
                <div className="muted">
                  {t("Next run: {date}", {
                    date: formatDate(settings.next_update_run, t("not scheduled")),
                  })}
                </div>
              </div>
            </div>
            <div className="subsection">
              <h3>{t("Auto-update")}</h3>
              <p className="muted">
                {autoBefore}
                <code>drydock.update: auto</code>
                {autoAfter}
              </p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  disabled={!user?.is_admin}
                  checked={formValues.auto_update_enabled}
                  onChange={(event) => edit({ auto_update_enabled: event.target.checked })}
                />
                {t("Update labelled services automatically")}
              </label>
              <div className="field-row">
                <label>
                  {t("Every day at (server time)")}
                  <select
                    disabled={!user?.is_admin || !formValues.auto_update_enabled}
                    value={formValues.auto_update_hour}
                    onChange={(event) => edit({ auto_update_hour: Number(event.target.value) })}
                  >
                    {Array.from({ length: 24 }, (_, hour) => (
                      <option key={hour} value={hour}>
                        {`${String(hour).padStart(2, "0")}:00`}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="muted">
                  {t("Next run: {date}", {
                    date: formatDate(settings.next_auto_update_run, t("not scheduled")),
                  })}
                </div>
                {user?.is_admin && (
                  <button type="button" className="secondary" onClick={runAutoUpdate}>
                    <RefreshCw size={15} /> {t("Run now")}
                  </button>
                )}
              </div>
            </div>
          </section>

          <section className="section">
            <h2>{t("Notifications")}</h2>
            <p className="muted">
              {notifyBefore}
              <em>{t("scheduled")}</em>
              {notifyAfter}
            </p>
            <label className="field">
              {t("Webhook URL")}
              <input
                type="text"
                placeholder="https://example.com/hooks/drydock"
                disabled={!user?.is_admin}
                value={formValues.notify_webhook_url}
                onChange={(event) => edit({ notify_webhook_url: event.target.value })}
              />
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                disabled={!user?.is_admin}
                checked={formValues.notify_on_critical}
                onChange={(event) => edit({ notify_on_critical: event.target.checked })}
              />
              {t("Notify when a scan finds critical CVEs")}
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                disabled={!user?.is_admin}
                checked={formValues.notify_on_update}
                onChange={(event) => edit({ notify_on_update: event.target.checked })}
              />
              {t("Notify when image updates are available")}
            </label>
          </section>

          {user?.is_admin && (
            <div className="button-row settings-save">
              <button type="submit" disabled={!dirty || saving}>
                <Save size={15} /> {saving ? t("Saving…") : t("Save settings")}
              </button>
              {dirty && (
                <button type="button" className="secondary" onClick={() => setDraft({})}>
                  {t("Discard changes")}
                </button>
              )}
            </div>
          )}
        </form>
      </div>

      {user?.is_admin && (
        <div className="settings-panel" hidden={tab !== "credentials"}>
          <RegistryCredentials />
          <GitCredentials />
        </div>
      )}

      {user?.is_admin && tab === "ai" && (
        <div className="settings-panel">
          <AiSettings />
        </div>
      )}

      <div className="settings-panel" hidden={tab !== "account"}>
        <ChangePassword title={t("Your password")} />
        <ApiTokens />
      </div>

      <div className="settings-panel" hidden={tab !== "system"}>
        <section className="section">
          <h2>{t("Environment")}</h2>
          <p className="muted">
            {envBefore}
            <code>DRYDOCK_*</code>
            {envAfter}
          </p>
          <ul className="fact-list">
            <li>
              <span className="muted">{t("Compose repo")}</span>
              <code>{settings.repo_path}</code>
            </li>
            <li>
              <span className="muted">{t("Data directory")}</span>
              <code>{settings.data_path}</code>
            </li>
          </ul>
        </section>

        <section className="section">
          <h2>{t("Recent background jobs")}</h2>
          {jobs.length === 0 ? (
            <div className="empty">{t("Nothing has run yet.")}</div>
          ) : (
            <table className="projects-table">
              <thead>
                <tr>
                  <th>{t("Job")}</th>
                  <th>{t("Status")}</th>
                  <th>{t("Trigger")}</th>
                  <th>{t("Result")}</th>
                  <th>{t("Started")}</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td>{job.label}</td>
                    <td>
                      <span
                        className={`badge ${
                          job.status === "success"
                            ? "running"
                            : job.status === "error"
                              ? "exited"
                              : "paused"
                        }`}
                      >
                        {job.status}
                      </span>
                    </td>
                    <td className="muted">{job.trigger}</td>
                    <td className="muted">{job.error ?? job.message ?? "—"}</td>
                    <td className="muted">
                      {formatDate(job.started_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}
