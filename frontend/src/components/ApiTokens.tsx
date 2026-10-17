import { Copy, KeyRound, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { formatDate } from "../format";
import type { ApiToken, ApiTokenCreated } from "../types";
import { useConfirm } from "./ConfirmDialog";

/** The signed-in user's API tokens, for scripts and CI. */
export default function ApiTokens() {
  const confirm = useConfirm();
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback((): void => {
    api
      .listTokens()
      .then(setTokens)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function create(event: FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setCreated(await api.createToken(name.trim()));
      setName("");
      load();
    } catch (createError) {
      setError((createError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(token: ApiToken): Promise<void> {
    const confirmed = await confirm({
      title: `Revoke token ${token.name}?`,
      message: "Scripts that use it stop working at once.",
      confirmLabel: "Revoke",
      tone: "danger",
    });
    if (!confirmed) return;
    try {
      await api.deleteToken(token.id);
      if (created?.id === token.id) setCreated(null);
      load();
    } catch (deleteError) {
      setError((deleteError as Error).message);
    }
  }

  return (
    <section className="section">
      <h2>API tokens</h2>
      <p className="muted">
        For scripts and CI: send <code>Authorization: Bearer &lt;token&gt;</code>. A token has
        your rights.
      </p>
      {error && <div className="error">{error}</div>}
      {created && (
        <div className="output ok" style={{ padding: "0.75rem" }}>
          <div>Copy the token now. It is not shown again.</div>
          <div className="button-row">
            <code style={{ overflowWrap: "anywhere" }}>{created.token}</code>
            <button
              type="button"
              className="secondary small"
              onClick={() => navigator.clipboard?.writeText(created.token)}
            >
              <Copy size={14} /> Copy
            </button>
          </div>
        </div>
      )}
      <form className="button-row" onSubmit={create}>
        <input
          placeholder="token name, e.g. ci"
          value={name}
          maxLength={100}
          onChange={(event) => setName(event.target.value)}
        />
        <button type="submit" disabled={busy || !name.trim()}>
          <KeyRound size={15} /> Create token
        </button>
      </form>
      {tokens.length > 0 && (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Token</th>
              <th>Created</th>
              <th>Last used</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tokens.map((token) => (
              <tr key={token.id}>
                <td>{token.name}</td>
                <td>
                  <code>{token.prefix}…</code>
                </td>
                <td className="muted">{formatDate(token.created_at)}</td>
                <td className="muted">{formatDate(token.last_used_at, "never")}</td>
                <td>
                  <button type="button" className="secondary small" onClick={() => revoke(token)}>
                    <Trash2 size={14} /> Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
