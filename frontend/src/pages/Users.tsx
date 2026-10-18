import {
  Circle,
  KeyRound,
  Power,
  ShieldCheck,
  ShieldOff,
  Trash2,
  User as UserIcon,
  UserPlus,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useConfirm } from "../components/ConfirmDialog";
import SortHeader from "../components/SortHeader";
import { useSort } from "../hooks/useSort";
import { useT } from "../i18n";
import type { User } from "../types";

export default function Users() {
  const t = useT();
  const confirm = useConfirm();
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const sorting = useSort(users, {
    storageKey: "drydock.sort.users",
    columns: {
      username: (user) => user.username,
      role: (user) => (user.is_admin ? 0 : 1),
      status: (user) => (user.is_active ? 0 : 1),
      created: (user) => Date.parse(user.created_at),
    },
    initial: { column: "username", descending: false },
    descendingFirst: ["created"],
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // new-user form
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [creating, setCreating] = useState(false);

  async function load(): Promise<void> {
    try {
      setUsers(await api.listUsers());
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t("Failed to load users"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function run(action: () => Promise<unknown>): Promise<void> {
    try {
      await action();
      await load();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : t("Action failed"));
    }
  }

  async function onCreate(event: FormEvent): Promise<void> {
    event.preventDefault();
    setCreating(true);
    await run(async () => {
      await api.createUser(username, password, isAdmin);
      setUsername("");
      setPassword("");
      setIsAdmin(false);
    });
    setCreating(false);
  }

  function resetPassword(user: User): void {
    const newPassword = window.prompt(
      t("New password for \"{name}\" (min 6 chars):", { name: user.username }),
    );
    if (newPassword == null) return;
    if (newPassword.length < 6) {
      setError(t("Password must be at least 6 characters"));
      return;
    }
    run(() => api.updateUser(user.id, { password: newPassword }));
  }

  async function remove(user: User): Promise<void> {
    const confirmed = await confirm({
      title: t("Delete user {name}?", { name: user.username }),
      message: t("This cannot be undone."),
      confirmLabel: t("Delete"),
      tone: "danger",
    });
    if (!confirmed) return;
    run(() => api.deleteUser(user.id));
  }

  return (
    <div>
      <h1>{t("Users")}</h1>
      {error && <div className="error">{error}</div>}

      <div className="section">
        <h2>{t("Add user")}</h2>
        <form className="button-row" onSubmit={onCreate}>
          <input
            placeholder={t("username")}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <input
            type="password"
            placeholder={t("password")}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={isAdmin}
              onChange={(event) => setIsAdmin(event.target.checked)}
            />
            {t("Admin")}
          </label>
          <button type="submit" disabled={creating || !username || password.length < 6}>
            <UserPlus size={15} /> {creating ? t("Adding…") : t("Add user")}
          </button>
        </form>
      </div>

      {loading ? (
        <div className="empty">{t("Loading…")}</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <SortHeader sorting={sorting} column="username">
                {t("Username")}
              </SortHeader>
              <SortHeader sorting={sorting} column="role">
                {t("Role")}
              </SortHeader>
              <SortHeader sorting={sorting} column="status">
                {t("Status")}
              </SortHeader>
              <SortHeader sorting={sorting} column="created">
                {t("Created")}
              </SortHeader>
              <th>{t("Actions")}</th>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((user) => {
              const isSelf = user.id === currentUser?.id;
              return (
                <tr key={user.id}>
                  <td>
                    <span className="row-name">{user.username}</span>
                    {isSelf && <span className="muted"> {t("(you)")}</span>}
                  </td>
                  <td>
                    <span className={`badge ${user.is_admin ? "admin-badge" : ""}`}>
                      {user.is_admin ? <ShieldCheck size={12} /> : <UserIcon size={12} />}
                      {user.is_admin ? t("admin") : t("user")}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${user.is_active ? "running" : "exited"}`}>
                      <Circle size={8} fill="currentColor" />
                      {user.is_active ? t("active") : t("disabled")}
                    </span>
                  </td>
                  <td className="muted">{new Date(user.created_at).toLocaleDateString()}</td>
                  <td>
                    <div className="button-row">
                      <button
                        className="secondary small"
                        onClick={() => resetPassword(user)}
                      >
                        <KeyRound size={14} /> {t("Reset password")}
                      </button>
                      <button
                        className="secondary small"
                        disabled={isSelf}
                        onClick={() =>
                          run(() => api.updateUser(user.id, { is_admin: !user.is_admin }))
                        }
                      >
                        {user.is_admin ? <ShieldOff size={14} /> : <ShieldCheck size={14} />}
                        {user.is_admin ? t("Revoke admin") : t("Make admin")}
                      </button>
                      <button
                        className="secondary small"
                        disabled={isSelf}
                        onClick={() =>
                          run(() => api.updateUser(user.id, { is_active: !user.is_active }))
                        }
                      >
                        <Power size={14} /> {user.is_active ? t("Disable") : t("Enable")}
                      </button>
                      <button
                        className="secondary small"
                        disabled={isSelf}
                        onClick={() => remove(user)}
                      >
                        <Trash2 size={14} /> {t("Delete")}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
