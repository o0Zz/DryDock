import { Copy, KeyRound, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { formatDate } from "../format";
import { useT } from "../i18n";
import type { ApiToken, ApiTokenCreated } from "../types";
import { useConfirm } from "./ConfirmDialog";

/** The signed-in user's API tokens, for scripts and CI. */
export default function ApiTokens() {
  const t = useT();
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
      title: t("Revoke token {name}?", { name: token.name }),
      message: t("Scripts that use it stop working at once."),
      confirmLabel: t("Revoke"),
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

  // Split around the placeholder so the header stays in place in every language.
  const [introBefore, introAfter] = t(
    "For scripts and CI: send {header}. A token has your rights.",
  ).split("{header}");

  return (
    <section className="section">
      <h2>{t("API tokens")}</h2>
      <p className="muted">
        {introBefore}
        <code>Authorization: Bearer &lt;token&gt;</code>
        {introAfter}
      </p>
      {error && <div className="error">{error}</div>}
      {created && (
        <div className="output ok padded">
          <div>{t("Copy the token now. It is not shown again.")}</div>
          <div className="button-row">
            <code style={{ overflowWrap: "anywhere" }}>{created.token}</code>
            <button
              type="button"
              className="secondary small"
              onClick={() => navigator.clipboard?.writeText(created.token)}
            >
              <Copy size={14} /> {t("Copy")}
            </button>
          </div>
        </div>
      )}
      <form className="button-row" onSubmit={create}>
        <input
          placeholder={t("token name, e.g. ci")}
          value={name}
          maxLength={100}
          onChange={(event) => setName(event.target.value)}
        />
        <button type="submit" disabled={busy || !name.trim()}>
          <KeyRound size={15} /> {t("Create token")}
        </button>
      </form>
      {tokens.length > 0 && (
        <table className="projects-table">
          <thead>
            <tr>
              <th>{t("Name")}</th>
              <th>{t("Token")}</th>
              <th>{t("Created")}</th>
              <th>{t("Last used")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tokens.map((token) => (
              <tr key={token.id}>
                <td className="row-name">{token.name}</td>
                <td>
                  <code>{token.prefix}…</code>
                </td>
                <td className="muted">{formatDate(token.created_at)}</td>
                <td className="muted">{formatDate(token.last_used_at, t("never"))}</td>
                <td>
                  <button type="button" className="secondary small" onClick={() => revoke(token)}>
                    <Trash2 size={14} /> {t("Revoke")}
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
