from pydantic import BaseModel, ConfigDict

from app.schemas.common import UtcDatetime


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
    # Set when the Docker daemon could not be reached, so the UI can say so
    # instead of silently reporting zero containers.
    docker_error: str | None = None
