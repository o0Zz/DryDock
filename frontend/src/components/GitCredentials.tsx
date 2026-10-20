import { KeyRound, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import type { GitCredential } from "../types";
import { useConfirm } from "./ConfirmDialog";

/** Git logins for private repos: builds, update checks, push and pull (admin only). */
export default function GitCredentials() {
  const t = useT();
  const confirm = useConfirm();
  const [logins, setLogins] = useState<GitCredential[]>([]);
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback((): void => {
    api
      .listGitCredentials()
      .then(setLogins)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function add(event: FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await api.addGitCredential(url.trim(), username.trim(), token);
      setToken("");
      setNotice(
        t("Saved the git login for {host} ({username}).", {
          host: saved.host,
          username: saved.username,
        }),
      );
      load();
    } catch (addError) {
      setError((addError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(login: GitCredential): Promise<void> {
    const confirmed = await confirm({
      title: t("Remove the git login for {host}?", { host: login.host }),
      message: t("Builds, update checks, pushes and pulls of its private repos will fail."),
      confirmLabel: t("Remove"),
      tone: "danger",
    });
    if (!confirmed) return;
    try {
      await api.removeGitCredential(login.host);
      load();
    } catch (removeError) {
      setError((removeError as Error).message);
    }
  }

  return (
    <section className="section">
      <h2>{t("Git logins")}</h2>
      <p className="muted">
        {t(
          "Used for private git repos over https: builds from a git URL, their update checks, and push and pull of the repo folder. Enter a repo URL to check the login before it is saved, or only a host. Use an access token instead of a password.",
        )}
      </p>
      {error && <div className="error">{error}</div>}
      {notice && <div className="output ok padded">{notice}</div>}
      {logins.length > 0 && (
        <table className="projects-table">
          <thead>
            <tr>
              <th>{t("Host")}</th>
              <th>{t("Username")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {logins.map((login) => (
              <tr key={login.host}>
                <td className="row-name">{login.host}</td>
                <td>{login.username}</td>
                <td>
                  <button type="button" className="secondary small" onClick={() => remove(login)}>
                    <Trash2 size={14} /> {t("Remove")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form onSubmit={add}>
        <label className="field">
          {t("Repo URL or host")}
          <input
            value={url}
            placeholder="https://github.com/me/app.git, git.lan:3000"
            onChange={(event) => setUrl(event.target.value)}
          />
        </label>
        <label className="field">
          {t("Username")}
          <input
            value={username}
            autoComplete="off"
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className="field">
          {t("Password or access token")}
          <input
            type="password"
            value={token}
            autoComplete="new-password"
            onChange={(event) => setToken(event.target.value)}
          />
        </label>
        <div className="button-row">
          <button type="submit" disabled={busy || !url.trim() || !username.trim() || !token}>
            <KeyRound size={15} /> {busy ? t("Checking…") : t("Save login")}
          </button>
        </div>
      </form>
    </section>
  );
}
