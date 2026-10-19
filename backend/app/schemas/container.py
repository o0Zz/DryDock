from datetime import datetime

from pydantic import BaseModel, Field


class ContainerPort(BaseModel):
    private_port: int
    public_port: int | None = None
    protocol: str = "tcp"
    host_ip: str | None = None


class Container(BaseModel):
    id: str
    name: str
    image: str
    # From the image's org.opencontainers.image.version label; tells what a
    # floating tag like `latest` actually runs.
    image_version: str | None = None
    status: str
    state: str
    created_at: datetime
    ports: list[ContainerPort]
    compose_project: str | None = None
    compose_service: str | None = None
    # Compose file(s) this container was deployed from, per Docker's label.
    compose_config_files: str | None = None
    restart_policy: str | None = None
    restart_count: int = 0
    # Health check result: "healthy", "unhealthy" or "starting"; None without a check.
    health: str | None = None
    # Last start and stop; None when it never happened. Uptime is now - started_at.
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ContainerRename(BaseModel):
    # Docker's own rule for container names.
    name: str = Field(min_length=2, max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")


class EnvVar(BaseModel):
    key: str
    value: str


class MountInfo(BaseModel):
    type: str
    source: str | None = None
    destination: str
    mode: str | None = None
    rw: bool = True


class NetworkInfo(BaseModel):
    name: str
    ip_address: str | None = None
    gateway: str | None = None
    mac_address: str | None = None


class ContainerDetail(Container):
    """Curated `docker inspect` view for the container detail page."""

    image_id: str | None = None
    command: list[str] | None = None
    entrypoint: list[str] | None = None
    working_dir: str | None = None
    user: str | None = None
    hostname: str | None = None
    exit_code: int | None = None
    env: list[EnvVar] = []
    # False when env values were masked for a non-admin viewer.
    env_revealed: bool = False
    mounts: list[MountInfo] = []
    networks: list[NetworkInfo] = []
    labels: dict[str, str] = {}
    # Full inspect payload; admins only, since it includes env values.
    raw: dict | None = None


class ContainerStats(BaseModel):
    id: str
    name: str
    cpu_percent: float
    memory_usage: int
    memory_limit: int
    memory_percent: float
    network_rx: int
    network_tx: int
    block_read: int
    block_write: int
    pids: int | None = None
