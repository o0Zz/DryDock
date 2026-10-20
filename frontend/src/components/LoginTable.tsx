import { Plus, Save, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import { useT } from "../i18n";
import { useConfirm } from "./ConfirmDialog";

/** A stored login as the API lists it: `id` is what the API knows it by. */
export interface StoredLogin {
  id: string;
  host: string;
  username: string;
}

interface Draft {
  host: string;
  username: string;
  secret: string;
}

const EMPTY: Draft = { host: "", username: "", secret: "" };

interface Props {
  title: string;
  description: string;
  hostLabel: string;
  hostPlaceholder: string;
  list: () => Promise<StoredLogin[]>;
  add: (draft: Draft) => Promise<StoredLogin>;
  /** An empty `secret` keeps the stored one. */
  update: (login: StoredLogin, draft: Draft) => Promise<StoredLogin>;
  remove: (login: StoredLogin) => Promise<void>;
  removeTitle: (login: StoredLogin) => string;
  removeMessage: string;
  savedNotice: (login: StoredLogin) => string;
}

/**
 * Logins as an editable table: every field of a stored row can change, its
 * password shows as dots and stays as is when left empty, and the last row adds one.
 */
export default function LoginTable(props: Props) {
  const t = useT();
  const confirm = useConfirm();
  const { list } = props;
  const [logins, setLogins] = useState<StoredLogin[]>([]);
  // Edits of stored rows, by id; a row without one shows what is stored.
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [added, setAdded] = useState<Draft>(EMPTY);
  // The row being saved: a login id, or "new".
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback((): void => {
    list()
      .then(setLogins)
      .catch((loadError: Error) => setError(loadError.message));
  }, [list]);

  useEffect(() => {
    load();
  }, [load]);

  function draftOf(login: StoredLogin): Draft {
    return drafts[login.id] ?? { host: login.host, username: login.username, secret: "" };
  }

  function changed(login: StoredLogin): boolean {
    const draft = draftOf(login);
    return draft.host !== login.host || draft.username !== login.username || draft.secret !== "";
  }

  function editRow(login: StoredLogin, patch: Partial<Draft>): void {
    setDrafts((previous) => ({ ...previous, [login.id]: { ...draftOf(login), ...patch } }));
  }

  function forget(id: string): void {
    setDrafts(({ [id]: _dropped, ...rest }) => rest);
  }

  async function run(row: string, action: () => Promise<StoredLogin>): Promise<void> {
    setBusy(row);
    setError(null);
    setNotice(null);
    try {
      const saved = await action();
      setNotice(props.savedNotice(saved));
      load();
    } catch (saveError) {
      setError((saveError as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function save(login: StoredLogin): void {
    const draft = draftOf(login);
    void run(login.id, async () => {
      const saved = await props.update(login, {
        host: draft.host.trim(),
        username: draft.username.trim(),
        secret: draft.secret,
      });
      forget(login.id);
      return saved;
    });
  }

  function add(): void {
    void run("new", async () => {
      const saved = await props.add({
        host: added.host.trim(),
        username: added.username.trim(),
        secret: added.secret,
      });
      setAdded(EMPTY);
      return saved;
    });
  }

  async function remove(login: StoredLogin): Promise<void> {
    const confirmed = await confirm({
      title: props.removeTitle(login),
      message: props.removeMessage,
      confirmLabel: t("Remove"),
      tone: "danger",
    });
    if (!confirmed) return;
    setError(null);
    setNotice(null);
    try {
      await props.remove(login);
      forget(login.id);
      load();
    } catch (removeError) {
      setError((removeError as Error).message);
    }
  }

  const canAdd = added.host.trim() !== "" && added.username.trim() !== "" && added.secret !== "";

  // Enter in a row saves that row, like a form would.
  function onEnter(event: KeyboardEvent, action: () => void, enabled: boolean): void {
    if (event.key === "Enter" && enabled) {
      event.preventDefault();
      action();
    }
  }

  return (
    <section className="section">
      <h2>{props.title}</h2>
      <p className="muted">{props.description}</p>
      {error && <div className="error">{error}</div>}
      {notice && <div className="output ok padded">{notice}</div>}
      <table className="projects-table login-table">
        <thead>
          <tr>
            <th>{props.hostLabel}</th>
            <th>{t("Username")}</th>
            <th>{t("Password or access token")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {logins.map((login) => {
            const draft = draftOf(login);
            const dirty = changed(login);
            const ready = dirty && draft.host.trim() !== "" && draft.username.trim() !== "";
            const keys = (event: KeyboardEvent) => onEnter(event, () => save(login), ready);
            return (
              <tr key={login.id}>
                <td>
                  <input
                    type="text"
                    aria-label={props.hostLabel}
                    value={draft.host}
                    onChange={(event) => editRow(login, { host: event.target.value })}
                    onKeyDown={keys}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    aria-label={t("Username")}
                    autoComplete="off"
                    value={draft.username}
                    onChange={(event) => editRow(login, { username: event.target.value })}
                    onKeyDown={keys}
                  />
                </td>
                <td>
                  <input
                    type="password"
                    aria-label={t("Password or access token")}
                    autoComplete="new-password"
                    // Never sent to the browser: empty means "keep the stored one".
                    placeholder="••••••••"
                    title={t("Leave empty to keep the stored one")}
                    value={draft.secret}
                    onChange={(event) => editRow(login, { secret: event.target.value })}
                    onKeyDown={keys}
                  />
                </td>
                <td>
                  <div className="button-row inline">
                    <button
                      type="button"
                      className="small"
                      disabled={!ready || busy !== null}
                      onClick={() => save(login)}
                    >
                      <Save size={14} /> {busy === login.id ? t("Checking…") : t("Save")}
                    </button>
                    {dirty && (
                      <button
                        type="button"
                        className="secondary small icon-only"
                        title={t("Undo changes")}
                        aria-label={t("Undo changes")}
                        onClick={() => forget(login.id)}
                      >
                        <Undo2 size={14} />
                      </button>
                    )}
                    <button
                      type="button"
                      className="secondary small icon-only"
                      title={t("Remove")}
                      aria-label={t("Remove")}
                      disabled={busy !== null}
                      onClick={() => remove(login)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
          <tr className="login-new">
            <td>
              <input
                type="text"
                aria-label={props.hostLabel}
                placeholder={props.hostPlaceholder}
                value={added.host}
                onChange={(event) => setAdded({ ...added, host: event.target.value })}
                onKeyDown={(event) => onEnter(event, add, canAdd)}
              />
            </td>
            <td>
              <input
                type="text"
                aria-label={t("Username")}
                autoComplete="off"
                value={added.username}
                onChange={(event) => setAdded({ ...added, username: event.target.value })}
                onKeyDown={(event) => onEnter(event, add, canAdd)}
              />
            </td>
            <td>
              <input
                type="password"
                aria-label={t("Password or access token")}
                autoComplete="new-password"
                value={added.secret}
                onChange={(event) => setAdded({ ...added, secret: event.target.value })}
                onKeyDown={(event) => onEnter(event, add, canAdd)}
              />
            </td>
            <td>
              <button
                type="button"
                className="small"
                disabled={!canAdd || busy !== null}
                onClick={add}
              >
                <Plus size={14} /> {busy === "new" ? t("Checking…") : t("Add")}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}
