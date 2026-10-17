import type {
  ApiErrorBody,
  ApiToken,
  ApiTokenCreated,
  AppSettings,
  ComposeContent,
  ComposeSaveResult,
  Container,
  ContainerAction,
  ContainerActionResult,
  ContainerDetail,
  ContainerStats,
  DashboardStats,
  EnvContent,
  EnvSaveResult,
  HostUsage,
  Job,
  LocalImage,
  Project,
  ProjectAction,
  RegistryCredential,
  ScanDetail,
  ScanSummary,
  SettingsPatch,
  UpdateSummary,
  User,
  UserPatch,
  Volume,
  VolumeListing,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (response.status === 401) {
    // Let the app drop back to the login screen from anywhere.
    window.dispatchEvent(new Event("drydock:unauthorized"));
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as ApiErrorBody | null;
      const detail = body?.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        // FastAPI validation errors: [{ loc, msg, ... }]
        message = detail
          .map((issue) => issue.msg)
          .filter(Boolean)
          .join("; ");
      }
    } catch {
      // response wasn't JSON — keep the status text
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
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
  updateUser: (id: number, patch: UserPatch) =>
    request<User>(`/api/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteUser: (id: number) =>
    request<void>(`/api/users/${id}`, { method: "DELETE" }),

  // dashboard
  dashboard: () => request<DashboardStats>("/api/dashboard"),
  hostUsage: () => request<HostUsage>("/api/dashboard/host"),

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
    request<ComposeSaveResult>(`/api/projects/${id}/compose`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  getEnv: (id: string) => request<EnvContent>(`/api/projects/${id}/env`),
  putEnv: (id: string, content: string) =>
    request<EnvSaveResult>(`/api/projects/${id}/env`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  // Compose actions, like prunes below, queue a job and return it at once
  runAction: (id: string, action: ProjectAction) =>
    request<Job>(`/api/projects/${id}/${action}`, { method: "POST" }),
  listContainers: () => request<Container[]>("/api/containers"),
  containerStats: () => request<ContainerStats[]>("/api/containers/stats"),
  inspectContainer: (id: string) =>
    request<ContainerDetail>(`/api/containers/${encodeURIComponent(id)}/inspect`),
  containerAction: (id: string, action: ContainerAction) =>
    request<ContainerActionResult>(`/api/containers/${id}/${action}`, {
      method: "POST",
    }),
  renameContainer: (id: string, name: string) =>
    request<Container>(`/api/containers/${id}/rename`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  deleteContainer: (id: string) => request<void>(`/api/containers/${id}`, { method: "DELETE" }),
  // Pull the image and recreate the Compose service — queued as a job
  updateContainer: (id: string) =>
    request<Job>(`/api/containers/${id}/update`, { method: "POST" }),

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
  listActiveJobs: () => request<Job[]>("/api/jobs?active=true"),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),

  // settings
  getSettings: () => request<AppSettings>("/api/settings"),
  updateSettings: (patch: SettingsPatch) =>
    request<AppSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),

  // API tokens (the signed-in user's own)
  listTokens: () => request<ApiToken[]>("/api/tokens"),
  createToken: (name: string) =>
    request<ApiTokenCreated>("/api/tokens", { method: "POST", body: JSON.stringify({ name }) }),
  deleteToken: (id: number) => request<void>(`/api/tokens/${id}`, { method: "DELETE" }),

  // registry credentials (admin)
  listRegistries: () => request<RegistryCredential[]>("/api/registries"),
  addRegistry: (registry: string, username: string, password: string) =>
    request<RegistryCredential>("/api/registries", {
      method: "POST",
      body: JSON.stringify({ registry, username, password }),
    }),
  removeRegistry: (registry: string) =>
    request<void>(`/api/registries?registry=${encodeURIComponent(registry)}`, {
      method: "DELETE",
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
  pruneVolumes: () => request<Job>("/api/volumes/prune", { method: "POST" }),
  listVolumeFiles: (name: string, path: string) =>
    request<VolumeListing>(
      `/api/volumes/${encodeURIComponent(name)}/files?path=${encodeURIComponent(path)}`,
    ),
  /** A plain link target: the browser downloads it with the session cookie. */
  volumeFileUrl: (name: string, path: string) =>
    `/api/volumes/${encodeURIComponent(name)}/files/download?path=${encodeURIComponent(path)}`,

  // local images
  listImages: () => request<LocalImage[]>("/api/images"),
  deleteImage: (image: string, force = false) =>
    request<void>(`/api/images?image=${encodeURIComponent(image)}&force=${force}`, {
      method: "DELETE",
    }),
  pruneImages: (all = false) =>
    request<Job>(`/api/images/prune?all=${all}`, { method: "POST" }),
};
