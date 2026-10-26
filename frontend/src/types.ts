export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  /** Still on the default password: the API refuses everything but a password change. */
  must_change_password: boolean;
}

export type ProjectAction = "up" | "down" | "pull" | "reload" | "stop";

export type ContainerAction = "start" | "stop" | "restart" | "pause" | "unpause" | "kill";

export interface UserPatch {
  password?: string;
  is_admin?: boolean;
  is_active?: boolean;
}

export interface ProjectService {
  name: string;
  image: string | null;
  /** `url#ref` when the service builds from a git repo. */
  git_source: string | null;
}

export interface Project {
  id: string;
  name: string;
  compose_path: string;
  relative_path: string;
  modified_at: string;
  services: ProjectService[];
  containers: Container[];
}

export interface ComposeContent {
  content: string;
}

export interface ComposeSaveResult {
  backup_path: string;
}

export interface EnvContent {
  content: string;
  /** False when the stack folder has no .env yet; saving creates it. */
  exists: boolean;
}

export interface EnvSaveResult {
  /** Null when there was no .env to back up. */
  backup_path: string | null;
}

export interface Volume {
  name: string;
  driver: string;
  mountpoint: string;
  scope: string | null;
  created_at: string | null;
  labels: Record<string, string>;
  compose_project: string | null;
  used_by: VolumeUser[];
}

export interface VolumeEntry {
  name: string;
  type: "dir" | "file" | "link" | "other";
  size: number;
  modified_at: string | null;
}

export interface VolumeListing {
  /** Absolute path inside the volume, `/` for its root. */
  path: string;
  entries: VolumeEntry[];
  /** The folder holds more entries than were returned. */
  truncated: boolean;
}

export interface ImageUser {
  name: string;
  running: boolean;
}

export interface LocalImage {
  id: string;
  tags: string[];
  size: number;
  created_at: string | null;
  used_by: ImageUser[];
}

export interface NetworkUser {
  id: string;
  name: string;
  running: boolean;
  ip_address: string | null;
}

export interface DockerNetwork {
  id: string;
  name: string;
  driver: string;
  scope: string | null;
  subnets: string[];
  gateways: string[];
  internal: boolean;
  created_at: string | null;
  labels: Record<string, string>;
  compose_project: string | null;
  /** bridge, host and none: Docker's own networks, which cannot be removed. */
  predefined: boolean;
  /** Containers in any state, so a stopped stack's network counts as used. */
  used_by: NetworkUser[];
}

export interface VolumeUser {
  id: string;
  name: string;
  running: boolean;
  /** Mount path inside the container. */
  destination: string;
  rw: boolean;
}

export interface ContainerPort {
  private_port: number;
  public_port: number | null;
  protocol: string;
  host_ip: string | null;
}

export interface Container {
  id: string;
  name: string;
  image: string;
  image_version: string | null;
  status: string;
  state: string;
  created_at: string;
  ports: ContainerPort[];
  compose_project: string | null;
  compose_service: string | null;
  compose_config_files: string | null;
  restart_policy: string | null;
  restart_count: number;
  /** Health check result: "healthy", "unhealthy" or "starting"; null without a check. */
  health: string | null;
  /** Last start and stop; null when it never happened. */
  started_at: string | null;
  finished_at: string | null;
}

export interface ContainerActionResult {
  status: string;
  action: string;
}

export interface EnvVar {
  key: string;
  value: string;
}

export interface MountInfo {
  type: string;
  source: string | null;
  destination: string;
  mode: string | null;
  rw: boolean;
}

export interface NetworkInfo {
  name: string;
  ip_address: string | null;
  gateway: string | null;
  mac_address: string | null;
}

/** Curated `docker inspect` view; `raw` and real env values are admin-only. */
export interface ContainerDetail extends Container {
  image_id: string | null;
  command: string[] | null;
  entrypoint: string[] | null;
  working_dir: string | null;
  user: string | null;
  hostname: string | null;
  exit_code: number | null;
  env: EnvVar[];
  env_revealed: boolean;
  mounts: MountInfo[];
  networks: NetworkInfo[];
  labels: Record<string, string>;
  raw: Record<string, unknown> | null;
}

export interface ScanSummary {
  id: number;
  image: string;
  scanned_at: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
  unknown: number;
  fixable: number;
  error: string | null;
}

export interface ScanFinding {
  vulnerability_id: string;
  severity: string;
  package_name: string;
  installed_version: string | null;
  fixed_version: string | null;
  title: string | null;
  primary_url: string | null;
  target: string | null;
}

export interface ScanDetail extends ScanSummary {
  findings: ScanFinding[];
  truncated: boolean;
}

export interface UpdateSummary {
  image: string;
  checked_at: string;
  local_digest: string | null;
  remote_digest: string | null;
  update_available: boolean;
  error: string | null;
  /** Newer version tag of the same shape in the registry (e.g. 2026.10.2). */
  newest_tag: string | null;
  /** Newest tag within the current major, when it differs from newest_tag. */
  newest_same_major_tag: string | null;
  tag_error: string | null;
  /** `url#ref` for an image built from git: the digests are then the built and the latest commit. */
  git_source: string | null;
}

export type JobStatus = "pending" | "running" | "success" | "error";

export interface Job {
  id: string;
  kind: string;
  label: string;
  status: JobStatus;
  total: number;
  done: number;
  message: string | null;
  error: string | null;
  output: string | null;
  trigger: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** A queued rename or duplicate, and the stack's ID once it is done. */
export interface StackChangeAccepted {
  job: Job;
  project_id: string;
}

/** What `useJobs` hands back to a page. */
export interface JobTracker {
  jobs: Job[];
  track: (job: Job) => void;
  start: (queueJob: () => Promise<Job>) => Promise<void>;
  dismiss: (id: string) => void;
  busy: boolean;
}

export interface AppSettings {
  scan_schedule_enabled: boolean;
  scan_interval_hours: number;
  update_check_enabled: boolean;
  update_check_interval_hours: number;
  notify_webhook_url: string;
  notify_on_critical: boolean;
  notify_on_update: boolean;
  /** Bare sub-domains complete to it in the Exposure panel. */
  proxy_domain: string;
  /** Docker network the proxy shares with the stacks it exposes. */
  proxy_network: string;
  next_scan_run: string | null;
  next_update_run: string | null;
  repo_path: string;
  data_path: string;
}

export type SettingsPatch = Partial<
  Pick<
    AppSettings,
    | "scan_schedule_enabled"
    | "scan_interval_hours"
    | "update_check_enabled"
    | "update_check_interval_hours"
    | "notify_webhook_url"
    | "notify_on_critical"
    | "notify_on_update"
    | "proxy_domain"
    | "proxy_network"
  >
>;

export interface HostInfo {
  os: string | null;
  kernel: string | null;
  architecture: string | null;
  docker_version: string | null;
  cpus: number | null;
  memory_total: number | null;
}

/** Live host load; a field is null where the host does not expose it. */
export interface HostUsage {
  cpu_percent: number | null;
  load_1m: number | null;
  memory_total: number | null;
  memory_used: number | null;
  uptime_seconds: number | null;
  temperature_c: number | null;
}

export interface ContainerAlert {
  id: string;
  name: string;
  status: string;
}

export interface ImageRisk {
  image: string;
  critical: number;
  high: number;
}

export interface ImageUpdate {
  image: string;
  newest_tag: string | null;
  rebuilt: boolean;
}

export interface DashboardStats {
  projects: number;
  services: number;
  containers_running: number;
  containers_stopped: number;
  volumes: number;
  images_tracked: number;
  images_scanned: number;
  images_critical: number;
  images_high: number;
  critical_total: number;
  high_total: number;
  updates_available: number;
  last_scan_at: string | null;
  last_update_check_at: string | null;
  unhealthy_containers: ContainerAlert[];
  most_vulnerable: ImageRisk[];
  updates: ImageUpdate[];
  host: HostInfo | null;
  /** Pending OS package updates on the host; null until checked, or without apt. */
  host_updates: number | null;
  host_security_updates: number;
  host_reboot_required: boolean;
  last_host_update_check_at: string | null;
  docker_error: string | null;
}

export interface HostPackage {
  name: string;
  current: string;
  candidate: string;
  security: boolean;
}

/** The latest check of the host's pending OS package updates. */
export interface HostUpdates {
  checked_at: string;
  /** False when the host has no apt (not Debian or Ubuntu). */
  supported: boolean;
  error: string | null;
  upgradable: number;
  security: number;
  packages: HostPackage[];
  /** When the host last ran `apt update`; the list is only as fresh as this. */
  lists_updated_at: string | null;
  reboot_required: boolean;
  kernel: string | null;
  /** unattended-upgrades installed and on; null when unknown. */
  auto_upgrades: boolean | null;
}

export interface Fail2banJail {
  name: string;
  enabled: boolean;
  active_bans: number;
  /** Bans still in fail2ban's history, which only goes back `dbpurgeage`. */
  bans: number;
  last_ban_at: string | null;
}

export interface Fail2banBan {
  ip: string;
  jail: string;
  banned_at: string;
  /** Null for a permanent ban. */
  expires_at: string | null;
  ban_count: number;
  /** The log lines that triggered the ban, newest last. */
  matches: string[];
}

export interface Fail2banReport {
  database: string;
  history_since: string | null;
  jails: Fail2banJail[];
  active_bans: Fail2banBan[];
  recent_bans: Fail2banBan[];
  /** User names tried in failed SSH logins. */
  top_users: { name: string; count: number }[];
}

/** FastAPI error body: a message, or a list of validation errors. */
export interface ApiErrorBody {
  detail?: string | { msg?: string }[];
}

export interface ContainerStats {
  id: string;
  name: string;
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  network_rx: number;
  network_tx: number;
  block_read: number;
  block_write: number;
  pids: number | null;
}

/** One point of a container's recent CPU and memory history. */
export interface StatsSample {
  at: string;
  cpu_percent: number;
  memory_usage: number;
}

export interface ApiToken {
  id: number;
  name: string;
  /** First characters of the token, to tell tokens apart. */
  prefix: string;
  created_at: string;
  last_used_at: string | null;
}

/** Only returned at creation: the full token is never shown again. */
export interface ApiTokenCreated extends ApiToken {
  token: string;
}

export interface RegistryCredential {
  /** `https://index.docker.io/v1/` for Docker Hub, else the registry host. */
  registry: string;
  username: string;
}

export interface GitCredential {
  /** Host with its port, e.g. `github.com` or `git.lan:3000`. */
  host: string;
  username: string;
}

export interface RepoChange {
  /** `git status --porcelain` code: index then work tree, e.g. " M", "??". */
  status: string;
  /** Relative to the repo folder. */
  path: string;
}

/** The git repository the repo folder is part of. */
export interface RepoGitStatus {
  supported: boolean;
  /** Why not, when not supported. */
  reason: string | null;
  branch: string | null;
  upstream: string | null;
  /** Against the upstream as of the last pull or push. */
  ahead: number;
  behind: number;
  remote_url: string | null;
  /** A login is stored for the remote's host. */
  has_login: boolean;
  changes: RepoChange[];
}

export type AiProviderId = "openai" | "anthropic" | "copilot";

export interface AiProvider {
  id: AiProviderId;
  /** A key (Copilot: a GitHub sign-in) is stored. The key itself never comes back. */
  configured: boolean;
  model: string;
  /** OpenAI only: empty means api.openai.com. */
  base_url: string;
  /** Copilot only: the GitHub login. */
  account: string;
}

export interface AiConfig {
  active: AiProviderId | null;
  providers: AiProvider[];
}

export interface AiProviderPatch {
  model: string;
  /** Empty keeps the stored key. */
  api_key?: string;
  base_url?: string;
}

export interface CopilotDevice {
  user_code: string;
  verification_uri: string;
  /** Seconds between polls, as GitHub asks. */
  interval: number;
  expires_in: number;
}

export interface CopilotPoll {
  status: "pending" | "done" | "expired" | "denied";
  account: string | null;
}

export interface AiMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ComposeAssistReply {
  reply: string;
  /** The whole proposed file, or null when the answer changes nothing. */
  content: string | null;
  /** Why the proposed file would not save. */
  error: string | null;
}

export interface ServiceExposure {
  service: string;
  exposed: boolean;
  hosts: string[];
  /** Container port Traefik forwards to. */
  port: number | null;
  /** Reachable from the internet (on the wan entrypoint). */
  public: boolean;
  /** Ports the service declares, to suggest one. */
  ports: number[];
  /** Why the service cannot be exposed, or null. */
  blocked: string | null;
  /** Still has labels of an older proxy setup (traefik.*, swag*); exposing drops them. */
  legacy: boolean;
}

export interface ExposeRequest {
  service: string;
  /** Full host name, or a bare sub-domain completed with the proxy domain. */
  host: string;
  port: number;
  public: boolean;
}

export interface ProxyRoute {
  project_id: string;
  project_name: string;
  service: string;
  hosts: string[];
  port: number | null;
  public: boolean;
  running: boolean;
}

export interface ProxyContainer {
  id: string;
  name: string;
  running: boolean;
  /** For the proxy: traefik, swag or caddy. */
  kind?: string | null;
}

export interface ProxyOverview {
  domain: string;
  network: string;
  /** The proxy's container (Traefik). */
  container: ProxyContainer | null;
  /** DryDock's proxy sync, which turns expose.* labels into the proxy's config. */
  sync: ProxyContainer | null;
  /** Image the proxy stack template runs the sync from: DryDock's own. */
  drydock_image: string;
  network_exists: boolean | null;
  docker_available: boolean;
  routes: ProxyRoute[];
}

export type Fail2banRule = "auth" | "forbidden" | "botsearch" | "badbots" | "custom";

export interface Fail2banJailConfig {
  /** Becomes the jail and filter name, drydock-<name>. */
  name: string;
  enabled: boolean;
  rule: Fail2banRule;
  /** Only for the custom rule. <HOST> marks the client IP. */
  failregex: string;
  maxretry: number;
  /** Seconds. */
  findtime: number;
  /** Seconds. */
  bantime: number;
}

export interface Fail2banConfig {
  /** Host path of the proxy's access log. */
  log_path: string;
  /** text: Traefik, nginx (SWAG). json: Caddy. */
  log_format: "text" | "json";
  /** Host path of the proxy sync's allowlist, never banned. Empty: none. */
  allowlist_file: string;
  ignore_ips: string[];
  /** forward: the proxy's ports are published by Docker. input: it runs on the host network. */
  ban_hook: "forward" | "input";
  jails: Fail2banJailConfig[];
}

export interface Fail2banConfigRead {
  config: Fail2banConfig;
  /** Whether the host's jail file matches this config; null when unreadable. */
  applied: boolean | null;
}

export interface Fail2banTestResult {
  lines: number;
  matched: number;
  top_ips: { ip: string; count: number }[];
  samples: string[];
}

export interface IpBlocklistConfig {
  enabled: boolean;
  /** Lists of IPs and CIDR ranges, one per line. */
  sources: string[];
  /** Host path of the proxy sync's allowlist, never blocked. Empty: none. */
  allowlist_file: string;
  /** Never blocked either, on top of the private ranges, which always are. */
  ignore_ips: string[];
}

export interface IpBlocklistSource {
  url: string;
  /** Ranges at its last successful download. */
  entries: number;
  fetched_at: string | null;
  /** The last download's error; the previous ranges are still used. */
  error: string | null;
}

export interface IpBlocklistRead {
  config: IpBlocklistConfig;
  /** What was last loaded on the host; null when never. */
  status: {
    applied_at: string | null;
    entries: number;
    sources: IpBlocklistSource[];
  } | null;
  host: {
    /** null when the host could not be read. */
    active: boolean | null;
    /** Packets dropped since the list was last loaded. */
    dropped: number | null;
    error: string | null;
  };
}

export interface IpBlocklistCheck {
  ip: string;
  blocked: boolean;
  /** The blocklist range the IP falls in. */
  network: string | null;
  /** The never-blocked range that lets it through anyway. */
  allowed_by: string | null;
}
