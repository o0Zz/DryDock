import { KeyRound, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import type { RegistryCredential } from "../types";
import { useConfirm } from "./ConfirmDialog";

const DOCKER_HUB_KEY = "https://index.docker.io/v1/";

function label(registry: string): string {
  return registry === DOCKER_HUB_KEY ? "Docker Hub" : registry;
}

/** Registry logins for update checks, pulls and scans of private images (admin only). */
export default function RegistryCredentials() {
  const confirm = useConfirm();
  const [registries, setRegistries] = useState<RegistryCredential[]>([]);
  const [registry, setRegistry] = useState("docker.io");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback((): void => {
    api
      .listRegistries()
      .then(setRegistries)
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
      const saved = await api.addRegistry(registry.trim(), username.trim(), password);
      setPassword("");
      setNotice(`Logged in to ${label(saved.registry)} as ${saved.username}.`);
      load();
    } catch (addError) {
      setError((addError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(credential: RegistryCredential): Promise<void> {
    const confirmed = await confirm({
      title: `Remove the login for ${label(credential.registry)}?`,
      message: "Update checks, pulls and scans of its private images will fail.",
      confirmLabel: "Remove",
      tone: "danger",
    });
    if (!confirmed) return;
    try {
      await api.removeRegistry(credential.registry);
      load();
    } catch (removeError) {
      setError((removeError as Error).message);
    }
  }

  return (
    <section className="section">
      <h2>Registry credentials</h2>
      <p className="muted">
        Used for update checks, pulls and scans of private images. DryDock checks a login with
        the registry before it saves it. Use an access token instead of a password where the
        registry offers one.
      </p>
      {error && <div className="error">{error}</div>}
      {notice && (
        <div className="output ok" style={{ padding: "0.75rem" }}>
          {notice}
        </div>
      )}
      {registries.length > 0 && (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Registry</th>
              <th>Username</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {registries.map((credential) => (
              <tr key={credential.registry}>
                <td>{label(credential.registry)}</td>
                <td>{credential.username}</td>
                <td>
                  <button
                    type="button"
                    className="secondary small"
                    onClick={() => remove(credential)}
                  >
                    <Trash2 size={14} /> Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form onSubmit={add}>
        <label className="field">
          Registry
          <input
            value={registry}
            placeholder="docker.io, ghcr.io, registry.lan:5000"
            onChange={(event) => setRegistry(event.target.value)}
          />
        </label>
        <label className="field">
          Username
          <input
            value={username}
            autoComplete="off"
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className="field">
          Password or access token
          <input
            type="password"
            value={password}
            autoComplete="new-password"
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <div className="button-row">
          <button
            type="submit"
            disabled={busy || !registry.trim() || !username.trim() || !password}
          >
            <KeyRound size={15} /> {busy ? "Checking…" : "Save login"}
          </button>
        </div>
      </form>
    </section>
  );
}
