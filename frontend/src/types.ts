export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
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

export interface Volume {
  name: string;
  driver: string;
  mountpoint: string;
  scope: string | null;
  created_at: string | null;
  labels: Record<string, string>;
  compose_project: string | null;
  used_by: string[];
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

export interface PruneResult {
  deleted: string[];
  space_reclaimed: number;
}

export interface ActionResult {
  action: string;
  exit_code: number;
  stdout: string;
  stderr: string;
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
  status: string;
  state: string;
  created_at: string;
  ports: ContainerPort[];
  compose_project: string | null;
  compose_service: string | null;
  compose_config_files: string | null;
  restart_policy: string | null;
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
  trigger: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
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
  docker_error: string | null;
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
