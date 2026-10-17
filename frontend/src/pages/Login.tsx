import { Anchor, LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { useT } from "../i18n";

export default function Login() {
  const { login } = useAuth();
  const t = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : t("Login failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={onSubmit}>
        <div className="brand login-brand">
          <Anchor size={24} />
          DryDock
        </div>
        <p className="muted">{t("Sign in to manage your stacks")}</p>
        <label>
          {t("Username")}
          <input
            autoFocus
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
          />
        </label>
        <label>
          {t("Password")}
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={busy || !username || !password}>
          <LogIn size={16} /> {busy ? t("Signing in…") : t("Sign in")}
        </button>
      </form>
    </div>
  );
}
