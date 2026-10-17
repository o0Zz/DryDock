export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
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
  started_at: string | null;
  finished_at: string | null;
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

/** What `useJobs` hands back to a page. */
/** A queued rename or duplicate, and the stack's ID once it is done. */
export interface StackChangeAccepted {
  job: Job;
  project_id: string;
}

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
