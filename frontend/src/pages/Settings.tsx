import { KeyRound, RefreshCw, Save } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { formatDate } from "../format";
import type { AppSettings, Job, SettingsPatch } from "../types";

export default function Settings() {
  const { user } = useAuth();
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<SettingsPatch>({});
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [current, jobList] = await Promise.all([api.getSettings(), api.listJobs(10)]);
      setSettings(current);
      setDraft({});
      setJobs(jobList);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error && !settings) return <div className="error">Failed to load settings: {error}</div>;
  if (!settings) return <div>Loading…</div>;

  // The draft holds only fields the user touched, so a save is always a patch.
  const value = { ...settings, ...draft };
  const dirty = Object.keys(draft).length > 0;

  function edit(patch: SettingsPatch) {
    setDraft((prev) => ({ ...prev, ...patch }));
    setNotice(null);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateSettings(draft);
      setSettings(updated);
      setDraft({});
      setNotice("Settings saved.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="row-between">
        <h1>Settings</h1>
        <button type="button" className="secondary" onClick={load}>
          <RefreshCw size={15} /> Reload
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {notice && (
        <div className="output ok" style={{ padding: "0.75rem" }}>
          {notice}
        </div>
      )}
      {!user?.is_admin && (
        <div className="muted">
          You are signed in as a standard user — these settings are read-only.
        </div>
      )}

      <form onSubmit={save}>
        <section className="section">
          <h2>Scheduled CVE scans</h2>
          <p className="muted">
            Runs a Trivy scan across every image used by a running container.
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              disabled={!user?.is_admin}
              checked={value.scan_schedule_enabled}
              onChange={(e) => edit({ scan_schedule_enabled: e.target.checked })}
            />
            Scan automatically
          </label>
          <div className="field-row">
            <label>
              Every (hours)
              <input
                type="number"
                min={1}
                max={720}
                disabled={!user?.is_admin || !value.scan_schedule_enabled}
                value={value.scan_interval_hours}
                onChange={(e) => edit({ scan_interval_hours: Number(e.target.value) })}
              />
            </label>
            <div className="muted">Next run: {formatDate(settings.next_scan_run, "not scheduled")}</div>
          </div>
        </section>

        <section className="section">
          <h2>Scheduled update checks</h2>
          <p className="muted">
            Compares each image digest against its registry. No layers are downloaded.
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              disabled={!user?.is_admin}
              checked={value.update_check_enabled}
              onChange={(e) => edit({ update_check_enabled: e.target.checked })}
            />
            Check automatically
          </label>
          <div className="field-row">
            <label>
              Every (hours)
              <input
                type="number"
                min={1}
                max={720}
                disabled={!user?.is_admin || !value.update_check_enabled}
                value={value.update_check_interval_hours}
                onChange={(e) => edit({ update_check_interval_hours: Number(e.target.value) })}
              />
            </label>
            <div className="muted">Next run: {formatDate(settings.next_update_run, "not scheduled")}</div>
          </div>
        </section>

        <section className="section">
          <h2>Notifications</h2>
          <p className="muted">
            After a <em>scheduled</em> run, DryDock POSTs a JSON summary to this URL. Manual
            runs never notify.
          </p>
          <label className="field">
            Webhook URL
            <input
              type="text"
              placeholder="https://example.com/hooks/drydock"
              disabled={!user?.is_admin}
              value={value.notify_webhook_url}
              onChange={(e) => edit({ notify_webhook_url: e.target.value })}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              disabled={!user?.is_admin}
              checked={value.notify_on_critical}
              onChange={(e) => edit({ notify_on_critical: e.target.checked })}
            />
            Notify when a scan finds critical CVEs
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              disabled={!user?.is_admin}
              checked={value.notify_on_update}
              onChange={(e) => edit({ notify_on_update: e.target.checked })}
            />
            Notify when image updates are available
          </label>
        </section>

        {user?.is_admin && (
          <div className="button-row">
            <button type="submit" disabled={!dirty || saving}>
              <Save size={15} /> {saving ? "Saving…" : "Save settings"}
            </button>
            {dirty && (
              <button type="button" className="secondary" onClick={() => setDraft({})}>
                Discard changes
              </button>
            )}
          </div>
        )}
      </form>

      <ChangePassword />

      <section className="section">
        <h2>Environment</h2>
        <p className="muted">
          Set with <code>DRYDOCK_*</code> environment variables; restart to change.
        </p>
        <ul className="fact-list">
          <li>
            <span className="muted">Compose repo</span>
            <code>{settings.repo_path}</code>
          </li>
          <li>
            <span className="muted">Data directory</span>
            <code>{settings.data_path}</code>
          </li>
        </ul>
      </section>

      <section className="section">
        <h2>Recent background jobs</h2>
        {jobs.length === 0 ? (
          <div className="empty">Nothing has run yet.</div>
        ) : (
          <table className="projects-table">
            <thead>
              <tr>
                <th>Job</th>
                <th>Status</th>
                <th>Trigger</th>
                <th>Result</th>
                <th>Started</th>
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
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (next !== confirm) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setNotice("Password changed.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="section">
      <h2>Your password</h2>
      {error && <div className="error">{error}</div>}
      {notice && (
        <div className="output ok" style={{ padding: "0.75rem" }}>
          {notice}
        </div>
      )}
      <form onSubmit={submit}>
        <label className="field">
          Current password
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
          />
        </label>
        <label className="field">
          New password
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
          />
        </label>
        <label className="field">
          Confirm new password
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        </label>
        <div className="button-row">
          <button type="submit" disabled={busy || !current || next.length < 6}>
            <KeyRound size={15} /> {busy ? "Saving…" : "Change password"}
          </button>
        </div>
      </form>
    </section>
  );
}
