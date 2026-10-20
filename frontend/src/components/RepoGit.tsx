import { ArrowDownToLine, ArrowUpFromLine, GitCommitHorizontal } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { msg, useT } from "../i18n";
import { waitForJob } from "../stackActions";
import type { Job, RepoChange, RepoGitStatus } from "../types";

const CHANGE_LABELS: Record<string, string> = {
  "?": msg("new"),
  A: msg("added"),
  M: msg("modified"),
  D: msg("deleted"),
  R: msg("renamed"),
  C: msg("copied"),
  T: msg("modified"),
  U: msg("conflict"),
};

function changeLabel(change: RepoChange): string {
  // The work tree letter, else the index one: " M" and "M " are both a modification.
  const letter = change.status.trim()[0] ?? "M";
  return CHANGE_LABELS[letter] ?? change.status;
}

/** Commit, push and pull the repo folder when it is in a git repository (admin only). */
export default function RepoGit({ onPulled }: { onPulled: () => void }) {
  const t = useT();
  const [state, setState] = useState<RepoGitStatus | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback((): void => {
    api
      .repoGitStatus()
      .then(setState)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(queue: () => Promise<Job>, after?: () => void): Promise<void> {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const job = await waitForJob(await queue());
      setNotice(job.output || job.message);
      after?.();
    } catch (runError) {
      setError((runError as Error).message);
    } finally {
      setBusy(false);
      load();
    }
  }

  function commit(event: FormEvent): void {
    event.preventDefault();
    void run(
      () => api.commitRepo(message.trim(), state?.upstream != null),
      () => setMessage(""),
    );
  }

  if (!state) return error ? <div className="error">{error}</div> : null;
  if (!state.supported) {
    return <p className="muted">{t("Git: {reason}", { reason: state.reason ?? "" })}</p>;
  }

  const httpsRemote = state.remote_url?.startsWith("https://") ?? false;
  return (
    <section className="section">
      <div className="row-between">
        <h2>{t("Git")}</h2>
        <div className="button-row inline">
          <button
            type="button"
            className="secondary small"
            disabled={busy || !state.upstream}
            onClick={() => run(api.pullRepo, onPulled)}
          >
            <ArrowDownToLine size={14} /> {t("Pull")}
          </button>
          {state.ahead > 0 && (
            <button
              type="button"
              className="secondary small"
              disabled={busy}
              onClick={() => run(api.pushRepo)}
            >
              <ArrowUpFromLine size={14} /> {t("Push")}
            </button>
          )}
        </div>
      </div>
      <p className="muted">
        {state.branch ? <code>{state.branch}</code> : t("detached HEAD")}
        {state.upstream && (
          <>
            {" → "}
            <code>{state.upstream}</code>
          </>
        )}
        {state.ahead > 0 && " · " + t("ahead {count}", { count: state.ahead })}
        {state.behind > 0 && " · " + t("behind {count}", { count: state.behind })}
        {state.remote_url && (
          <>
            {" · "}
            <code>{state.remote_url}</code>
          </>
        )}
      </p>
      {!state.upstream && (
        <p className="muted">{t("This branch has no upstream: push and pull are off.")}</p>
      )}
      {httpsRemote && !state.has_login && (
        <p className="muted">
          {t("No git login for this remote. Add one in Settings if the repo is private.")}
        </p>
      )}
      {error && <div className="error">{error}</div>}
      {notice && (
        <div className="output ok">
          <pre>{notice}</pre>
        </div>
      )}
      {state.changes.length === 0 ? (
        <p className="muted">{t("No changes to commit.")}</p>
      ) : (
        <>
          <table className="projects-table compact">
            <tbody>
              {state.changes.map((change) => (
                <tr key={change.path}>
                  <td>
                    <span className="badge">{t(changeLabel(change))}</span>
                  </td>
                  <td>
                    <code>{change.path}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <form onSubmit={commit}>
            <p className="muted">
              {t(
                "Every change listed is committed, .env files included unless .gitignore lists them.",
              )}
            </p>
            <label className="field">
              {t("Commit message")}
              <input value={message} onChange={(event) => setMessage(event.target.value)} />
            </label>
            <div className="button-row">
              <button type="submit" disabled={busy || !message.trim()}>
                <GitCommitHorizontal size={15} />{" "}
                {state.upstream ? t("Commit & push") : t("Commit")}
              </button>
            </div>
          </form>
        </>
      )}
    </section>
  );
}
