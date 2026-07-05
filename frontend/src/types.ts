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
  restart_policy: string | null;
}
