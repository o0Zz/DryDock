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
import type { User } from "../types";

export default function Users() {
  const confirm = useConfirm();
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
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
      setError(loadError instanceof Error ? loadError.message : "Failed to load users");
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
      setError(actionError instanceof Error ? actionError.message : "Action failed");
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
    const newPassword = window.prompt(`New password for "${user.username}" (min 6 chars):`);
    if (newPassword == null) return;
    if (newPassword.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    run(() => api.updateUser(user.id, { password: newPassword }));
  }

  async function remove(user: User): Promise<void> {
    const confirmed = await confirm({
      title: `Delete user ${user.username}?`,
      message: "This cannot be undone.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!confirmed) return;
    run(() => api.deleteUser(user.id));
  }

  return (
    <div>
      <h1>Users</h1>
      {error && <div className="error">{error}</div>}

      <div className="section">
        <h2>Add user</h2>
        <form className="button-row" onSubmit={onCreate}>
          <input
            placeholder="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <input
            type="password"
            placeholder="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={isAdmin}
              onChange={(event) => setIsAdmin(event.target.checked)}
            />
            Admin
          </label>
          <button type="submit" disabled={creating || !username || password.length < 6}>
            <UserPlus size={15} /> {creating ? "Adding…" : "Add user"}
          </button>
        </form>
      </div>

      {loading ? (
        <div className="empty">Loading…</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Status</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const isSelf = user.id === currentUser?.id;
              return (
                <tr key={user.id}>
                  <td>
                    {user.username}
                    {isSelf && <span className="muted"> (you)</span>}
                  </td>
                  <td>
                    <span className={`badge ${user.is_admin ? "admin-badge" : ""}`}>
                      {user.is_admin ? <ShieldCheck size={12} /> : <UserIcon size={12} />}
                      {user.is_admin ? "admin" : "user"}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${user.is_active ? "running" : "exited"}`}>
                      <Circle size={8} fill="currentColor" />
                      {user.is_active ? "active" : "disabled"}
                    </span>
                  </td>
                  <td className="muted">{new Date(user.created_at).toLocaleDateString()}</td>
                  <td>
                    <div className="button-row">
                      <button
                        className="secondary small"
                        onClick={() => resetPassword(user)}
                      >
                        <KeyRound size={14} /> Reset password
                      </button>
                      <button
                        className="secondary small"
                        disabled={isSelf}
                        onClick={() =>
                          run(() => api.updateUser(user.id, { is_admin: !user.is_admin }))
                        }
                      >
                        {user.is_admin ? <ShieldOff size={14} /> : <ShieldCheck size={14} />}
                        {user.is_admin ? "Revoke admin" : "Make admin"}
                      </button>
                      <button
                        className="secondary small"
                        disabled={isSelf}
                        onClick={() =>
                          run(() => api.updateUser(user.id, { is_active: !user.is_active }))
                        }
                      >
                        <Power size={14} /> {user.is_active ? "Disable" : "Enable"}
                      </button>
                      <button
                        className="secondary small"
                        disabled={isSelf}
                        onClick={() => remove(user)}
                      >
                        <Trash2 size={14} /> Delete
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
