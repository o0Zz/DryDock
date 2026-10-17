from pydantic import BaseModel, ConfigDict

from app.schemas.common import UtcDatetime


class HostInfo(BaseModel):
    """Facts about the Docker host, from `docker info`."""

    os: str | None = None
    kernel: str | None = None
    architecture: str | None = None
    docker_version: str | None = None
    cpus: int | None = None
    memory_total: int | None = None


class HostUsage(BaseModel):
    """Live host load. A field is None where the host does not expose it."""

    cpu_percent: float | None = None
    load_1m: float | None = None
    memory_total: int | None = None
    memory_used: int | None = None
    uptime_seconds: float | None = None
    temperature_c: float | None = None


class ContainerAlert(BaseModel):
    id: str
    name: str
    status: str


class ImageRisk(BaseModel):
    image: str
    critical: int
    high: int


class ImageUpdate(BaseModel):
    image: str
    # Newest version tag of the same shape, when the registry has one.
    newest_tag: str | None = None
    # The same tag was rebuilt (new digest).
    rebuilt: bool = False


class DashboardStats(BaseModel):
    """Everything the dashboard shows, in one round trip."""

    # The endpoint fills this in field by field, and pydantic skips
    # validators on assignment unless asked - without this the UTC stamping
    # on the timestamps below never runs.
    model_config = ConfigDict(validate_assignment=True)

    projects: int = 0
    services: int = 0
    containers_running: int = 0
    containers_stopped: int = 0
    volumes: int = 0
    images_tracked: int = 0
    images_scanned: int = 0
    images_critical: int = 0
    images_high: int = 0
    critical_total: int = 0
    high_total: int = 0
    updates_available: int = 0
    last_scan_at: UtcDatetime | None = None
    last_update_check_at: UtcDatetime | None = None
    # Restarting in a loop or failing their health check.
    unhealthy_containers: list[ContainerAlert] = []
    # Worst images first, capped; the counts above hold the totals.
    most_vulnerable: list[ImageRisk] = []
    updates: list[ImageUpdate] = []
    host: HostInfo | None = None
    # Pending OS package updates on the host; None until the first check,
    # or when the host has no apt.
    host_updates: int | None = None
    host_security_updates: int = 0
    host_reboot_required: bool = False
    last_host_update_check_at: UtcDatetime | None = None
    # Set when the Docker daemon could not be reached, so the UI can say so
    # instead of silently reporting zero containers.
    docker_error: str | None = None
