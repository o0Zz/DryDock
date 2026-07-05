import type {
  ActionResult,
  ComposeContent,
  Container,
  Project,
  PruneResult,
  User,
  Volume,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (res.status === 401) {
    // Let the app drop back to the login screen from anywhere.
    window.dispatchEvent(new Event("harborguard:unauthorized"));
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body?.detail)) {
        // FastAPI validation errors: [{ loc, msg, ... }]
        detail = body.detail
          .map((e: { msg?: string }) => e.msg)
          .filter(Boolean)
          .join("; ");
      }
    } catch {
      // response wasn't JSON — keep the status text
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  // auth
  me: () => request<User>("/api/auth/me"),
  login: (username: string, password: string) =>
    request<User>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/api/auth/password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),

  // users (admin)
  listUsers: () => request<User[]>("/api/users"),
  createUser: (username: string, password: string, is_admin: boolean) =>
    request<User>("/api/users", {
      method: "POST",
      body: JSON.stringify({ username, password, is_admin }),
    }),
  updateUser: (
    id: number,
    patch: { password?: string; is_admin?: boolean; is_active?: boolean },
  ) =>
    request<User>(`/api/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteUser: (id: number) =>
    request<void>(`/api/users/${id}`, { method: "DELETE" }),

  // projects / containers
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  getCompose: (id: string) => request<ComposeContent>(`/api/projects/${id}/compose`),
  putCompose: (id: string, content: string) =>
    request<{ backup_path: string }>(`/api/projects/${id}/compose`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  runAction: (id: string, action: "up" | "down" | "pull" | "restart" | "stop") =>
    request<ActionResult>(`/api/projects/${id}/${action}`, { method: "POST" }),
  listContainers: () => request<Container[]>("/api/containers"),
  containerAction: (id: string, action: "start" | "stop" | "restart") =>
    request<{ status: string; action: string }>(`/api/containers/${id}/${action}`, {
      method: "POST",
    }),

  // volumes
  listVolumes: () => request<Volume[]>("/api/volumes"),
  createVolume: (name: string, driver = "local") =>
    request<Volume>("/api/volumes", {
      method: "POST",
      body: JSON.stringify({ name, driver }),
    }),
  deleteVolume: (name: string, force = false) =>
    request<void>(`/api/volumes/${encodeURIComponent(name)}?force=${force}`, {
      method: "DELETE",
    }),
  pruneVolumes: () => request<PruneResult>("/api/volumes/prune", { method: "POST" }),
};
