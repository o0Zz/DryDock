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
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // new-user form
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [creating, setCreating] = useState(false);

  async function load() {
    try {
      setUsers(await api.listUsers());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function run(fn: () => Promise<unknown>) {
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    }
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    await run(async () => {
      await api.createUser(username, password, isAdmin);
      setUsername("");
      setPassword("");
      setIsAdmin(false);
    });
    setCreating(false);
  }

  function resetPassword(u: User) {
    const pw = window.prompt(`New password for "${u.username}" (min 6 chars):`);
    if (pw == null) return;
    if (pw.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    run(() => api.updateUser(u.id, { password: pw }));
  }

  async function remove(u: User) {
    const ok = await confirm({
      title: `Delete user ${u.username}?`,
      message: "This cannot be undone.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    run(() => api.deleteUser(u.id));
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
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            type="password"
            placeholder="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={isAdmin}
              onChange={(e) => setIsAdmin(e.target.checked)}
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
            {users.map((u) => {
              const self = u.id === me?.id;
              return (
                <tr key={u.id}>
                  <td>
                    {u.username}
                    {self && <span className="muted"> (you)</span>}
                  </td>
                  <td>
                    <span className={`badge ${u.is_admin ? "admin-badge" : ""}`}>
                      {u.is_admin ? <ShieldCheck size={12} /> : <UserIcon size={12} />}
                      {u.is_admin ? "admin" : "user"}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${u.is_active ? "running" : "exited"}`}>
                      <Circle size={8} fill="currentColor" />
                      {u.is_active ? "active" : "disabled"}
                    </span>
                  </td>
                  <td className="muted">{new Date(u.created_at).toLocaleDateString()}</td>
                  <td>
                    <div className="button-row">
                      <button
                        className="secondary small"
                        onClick={() => resetPassword(u)}
                      >
                        <KeyRound size={14} /> Reset password
                      </button>
                      <button
                        className="secondary small"
                        disabled={self}
                        onClick={() => run(() => api.updateUser(u.id, { is_admin: !u.is_admin }))}
                      >
                        {u.is_admin ? <ShieldOff size={14} /> : <ShieldCheck size={14} />}
                        {u.is_admin ? "Revoke admin" : "Make admin"}
                      </button>
                      <button
                        className="secondary small"
                        disabled={self}
                        onClick={() => run(() => api.updateUser(u.id, { is_active: !u.is_active }))}
                      >
                        <Power size={14} /> {u.is_active ? "Disable" : "Enable"}
                      </button>
                      <button className="secondary small" disabled={self} onClick={() => remove(u)}>
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
