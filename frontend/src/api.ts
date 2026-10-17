import type {
  ActionResult,
  AppSettings,
  ComposeContent,
  Container,
  ContainerDetail,
  ContainerStats,
  DashboardStats,
  Job,
  LocalImage,
  Project,
  PruneResult,
  ScanDetail,
  ScanSummary,
  SettingsPatch,
  UpdateSummary,
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
    window.dispatchEvent(new Event("drydock:unauthorized"));
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

  // dashboard
  dashboard: () => request<DashboardStats>("/api/dashboard"),

  // projects / containers
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (name: string, content: string) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, content }),
    }),
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
  containerStats: () => request<ContainerStats[]>("/api/containers/stats"),
  inspectContainer: (id: string) =>
    request<ContainerDetail>(`/api/containers/${encodeURIComponent(id)}/inspect`),
  containerAction: (id: string, action: "start" | "stop" | "restart") =>
    request<{ status: string; action: string }>(`/api/containers/${id}/${action}`, {
      method: "POST",
    }),

  // CVE scans — the POSTs queue a background job and return it immediately
  listScans: () => request<ScanSummary[]>("/api/scans"),
  scanHistory: (image: string) =>
    request<ScanSummary[]>(`/api/scans?image=${encodeURIComponent(image)}`),
  getScan: (id: number) => request<ScanDetail>(`/api/scans/${id}`),
  scanImage: (image: string) =>
    request<Job>("/api/scans/image", {
      method: "POST",
      body: JSON.stringify({ image }),
    }),
  scanRunning: () => request<Job>("/api/scans/running", { method: "POST" }),
  scanCompose: () => request<Job>("/api/scans/compose", { method: "POST" }),

  // update checks
  listUpdates: () => request<UpdateSummary[]>("/api/updates"),
  checkUpdates: (images?: string[]) =>
    request<Job>("/api/updates/check", {
      method: "POST",
      body: JSON.stringify({ images: images ?? null }),
    }),

  // background jobs
  listJobs: (limit = 25) => request<Job[]>(`/api/jobs?limit=${limit}`),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),

  // settings
  getSettings: () => request<AppSettings>("/api/settings"),
  updateSettings: (patch: SettingsPatch) =>
    request<AppSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(patch),
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

  // local images
  listImages: () => request<LocalImage[]>("/api/images"),
  deleteImage: (image: string, force = false) =>
    request<void>(`/api/images?image=${encodeURIComponent(image)}&force=${force}`, {
      method: "DELETE",
    }),
  pruneImages: (all = false) =>
    request<PruneResult>(`/api/images/prune?all=${all}`, { method: "POST" }),
};
