import type {
  AiConfig,
  AiMessage,
  AiProviderId,
  AiProviderPatch,
  ApiErrorBody,
  ApiToken,
  ApiTokenCreated,
  AppSettings,
  ComposeAssistReply,
  ComposeContent,
  ComposeSaveResult,
  Container,
  ContainerAction,
  ContainerActionResult,
  ContainerDetail,
  ContainerStats,
  CopilotDevice,
  CopilotPoll,
  DashboardStats,
  DockerNetwork,
  EnvContent,
  EnvSaveResult,
  ExposeRequest,
  Fail2banEdit,
  Fail2banJailConfig,
  Fail2banJails,
  Fail2banNewJail,
  Fail2banPlan,
  Fail2banReport,
  Fail2banTestRequest,
  Fail2banTestResult,
  GitCredential,
  HostUpdates,
  HostUsage,
  IpBlocklistCheck,
  IpBlocklistConfig,
  IpBlocklistRead,
  Job,
  LocalImage,
  Project,
  ProjectAction,
  ProxyOverview,
  RegistryCredential,
  RepoGitStatus,
  ScanDetail,
  ScanSummary,
  ServiceExposure,
  SettingsPatch,
  StackChangeAccepted,
  StatsSample,
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

  // host OS updates and fail2ban (admin)
  hostUpdates: () => request<HostUpdates | null>("/api/host/updates"),
  checkHostUpdates: () => request<Job>("/api/host/updates/check", { method: "POST" }),
  fail2ban: () => request<Fail2banReport>("/api/host/fail2ban"),
  fail2banJails: () => request<Fail2banJails>("/api/host/fail2ban/jails"),
  newFail2banJail: (jail: Fail2banNewJail) =>
    request<Fail2banJailConfig>("/api/host/fail2ban/new", {
      method: "POST",
      body: JSON.stringify(jail),
    }),
  planFail2ban: (edit: Fail2banEdit) =>
    request<Fail2banPlan>("/api/host/fail2ban/plan", {
      method: "POST",
      body: JSON.stringify(edit),
    }),
  applyFail2ban: (edit: Fail2banEdit) =>
    request<Job>("/api/host/fail2ban/apply", { method: "POST", body: JSON.stringify(edit) }),
  testFail2ban: (test: Fail2banTestRequest) =>
    request<Fail2banTestResult>("/api/host/fail2ban/test", {
      method: "POST",
      body: JSON.stringify(test),
    }),
  getBlocklist: () => request<IpBlocklistRead>("/api/host/blocklist"),
  saveBlocklist: (config: IpBlocklistConfig) =>
    request<IpBlocklistRead>("/api/host/blocklist", {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  applyBlocklist: () => request<Job>("/api/host/blocklist/apply", { method: "POST" }),
  checkBlocklist: (ip: string) =>
    request<IpBlocklistCheck>(`/api/host/blocklist/check?ip=${encodeURIComponent(ip)}`),

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
  // Stack changes queue a job: `down` comes first, and a folder copy can take a while.
  deleteProject: (id: string, removeVolumes: boolean) =>
    request<Job>(`/api/projects/${id}?remove_volumes=${removeVolumes}`, { method: "DELETE" }),
  renameProject: (id: string, name: string) =>
    request<StackChangeAccepted>(`/api/projects/${id}/rename`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  duplicateProject: (id: string, name: string) =>
    request<StackChangeAccepted>(`/api/projects/${id}/duplicate`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  // Compose actions, like prunes below, queue a job and return it at once
  runAction: (id: string, action: ProjectAction) =>
    request<Job>(`/api/projects/${id}/${action}`, { method: "POST" }),
  listContainers: () => request<Container[]>("/api/containers"),
  containerStats: () => request<ContainerStats[]>("/api/containers/stats"),
  containerStatsHistory: () =>
    request<Record<string, StatsSample[]>>("/api/containers/stats/history"),
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
  runAutoUpdate: () => request<Job>("/api/updates/auto", { method: "POST" }),

  // background jobs
  listJobs: (limit: number) => request<Job[]>(`/api/jobs?limit=${limit}`),
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
  /** An empty password keeps the stored one. */
  updateRegistry: (current: string, registry: string, username: string, password: string) =>
    request<RegistryCredential>(`/api/registries?registry=${encodeURIComponent(current)}`, {
      method: "PUT",
      body: JSON.stringify({ registry, username, password }),
    }),
  removeRegistry: (registry: string) =>
    request<void>(`/api/registries?registry=${encodeURIComponent(registry)}`, {
      method: "DELETE",
    }),

  // git logins and the repo's git (admin)
  listGitCredentials: () => request<GitCredential[]>("/api/git/credentials"),
  addGitCredential: (url: string, username: string, token: string) =>
    request<GitCredential>("/api/git/credentials", {
      method: "POST",
      body: JSON.stringify({ url, username, token }),
    }),
  /** An empty token keeps the stored one. */
  updateGitCredential: (host: string, url: string, username: string, token: string) =>
    request<GitCredential>(`/api/git/credentials?host=${encodeURIComponent(host)}`, {
      method: "PUT",
      body: JSON.stringify({ url, username, token }),
    }),
  removeGitCredential: (host: string) =>
    request<void>(`/api/git/credentials?host=${encodeURIComponent(host)}`, { method: "DELETE" }),
  repoGitStatus: () => request<RepoGitStatus>("/api/git/repo"),
  commitRepo: (message: string, push: boolean) =>
    request<Job>("/api/git/repo/commit", {
      method: "POST",
      body: JSON.stringify({ message, push }),
    }),
  pushRepo: () => request<Job>("/api/git/repo/push", { method: "POST" }),
  pullRepo: () => request<Job>("/api/git/repo/pull", { method: "POST" }),

  // AI assistant: provider setup (admin) and the Compose editor's chat
  getAi: () => request<AiConfig>("/api/ai"),
  setAiActive: (provider: AiProviderId | null) =>
    request<AiConfig>("/api/ai/active", { method: "PUT", body: JSON.stringify({ provider }) }),
  setAiProvider: (provider: AiProviderId, patch: AiProviderPatch) =>
    request<AiConfig>(`/api/ai/providers/${provider}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  removeAiProvider: (provider: AiProviderId) =>
    request<AiConfig>(`/api/ai/providers/${provider}`, { method: "DELETE" }),
  listAiModels: (provider: AiProviderId) =>
    request<string[]>(`/api/ai/providers/${provider}/models`),
  startCopilotSignIn: () => request<CopilotDevice>("/api/ai/copilot/device", { method: "POST" }),
  pollCopilotSignIn: () => request<CopilotPoll>("/api/ai/copilot/poll", { method: "POST" }),
  assistCompose: (content: string, messages: AiMessage[]) =>
    request<ComposeAssistReply>("/api/ai/compose", {
      method: "POST",
      body: JSON.stringify({ content, messages }),
    }),

  // The exposure routes take and return the editor's content; nothing is saved.
  getProxy: () => request<ProxyOverview>("/api/proxy"),
  exposureServices: (id: string, content: string) =>
    request<ServiceExposure[]>(`/api/proxy/projects/${id}/services`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  exposeService: (id: string, content: string, exposure: ExposeRequest) =>
    request<ComposeContent>(`/api/proxy/projects/${id}/expose`, {
      method: "POST",
      body: JSON.stringify({ content, ...exposure }),
    }),
  unexposeService: (id: string, content: string, service: string) =>
    request<ComposeContent>(`/api/proxy/projects/${id}/unexpose`, {
      method: "POST",
      body: JSON.stringify({ content, service }),
    }),
  setAutoUpdate: (id: string, content: string, service: string, enabled: boolean) =>
    request<ComposeContent>(`/api/proxy/projects/${id}/auto-update`, {
      method: "POST",
      body: JSON.stringify({ content, service, enabled }),
    }),

  // networks
  listNetworks: () => request<DockerNetwork[]>("/api/networks"),
  deleteNetwork: (id: string) =>
    request<void>(`/api/networks/${encodeURIComponent(id)}`, { method: "DELETE" }),
  pruneNetworks: () => request<Job>("/api/networks/prune", { method: "POST" }),

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
  pruneImages: () => request<Job>("/api/images/prune", { method: "POST" }),
};
