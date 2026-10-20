import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useT } from "../i18n";

/** Current, new and confirmed password. `onChanged` runs after a successful change. */
export default function ChangePassword({
  title,
  onChanged,
}: {
  /** Section heading; without one the form is bare, e.g. inside a card. */
  title?: string;
  onChanged?: () => void;
}) {
  const t = useT();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (newPassword !== confirmPassword) {
      setError(t("The new passwords do not match."));
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setNotice(t("Password changed."));
      onChanged?.();
    } catch (changeError) {
      setError((changeError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={title ? "section" : undefined}>
      {title && <h2>{title}</h2>}
      {error && <div className="error">{error}</div>}
      {notice && (
        <div className="output ok padded">
          {notice}
        </div>
      )}
      <form onSubmit={submit}>
        <label className="field">
          {t("Current password")}
          <input
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        <label className="field">
          {t("New password")}
          <input
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            autoComplete="new-password"
          />
        </label>
        <label className="field">
          {t("Confirm new password")}
          <input
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            autoComplete="new-password"
          />
        </label>
        <div className="button-row">
          <button type="submit" disabled={busy || !currentPassword || newPassword.length < 6}>
            <KeyRound size={15} /> {busy ? t("Saving…") : t("Change password")}
          </button>
        </div>
      </form>
    </section>
  );
}
