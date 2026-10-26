from datetime import datetime

from pydantic import BaseModel, Field


class SettingsRead(BaseModel):
    scan_schedule_enabled: bool
    scan_interval_hours: int
    update_check_enabled: bool
    update_check_interval_hours: int
    auto_update_enabled: bool
    auto_update_hour: int
    notify_webhook_url: str
    notify_on_critical: bool
    notify_on_update: bool
    proxy_domain: str
    proxy_network: str
    # Computed, read-only context for the settings screen.
    next_scan_run: datetime | None = None
    next_update_run: datetime | None = None
    next_auto_update_run: datetime | None = None
    repo_path: str
    data_path: str


class SettingsUpdate(BaseModel):
    scan_schedule_enabled: bool | None = None
    scan_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    update_check_enabled: bool | None = None
    update_check_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    auto_update_enabled: bool | None = None
    auto_update_hour: int | None = Field(default=None, ge=0, le=23)
    notify_webhook_url: str | None = Field(default=None, max_length=2000)
    notify_on_critical: bool | None = None
    notify_on_update: bool | None = None
    # Empty clears it: services then need a full host name.
    proxy_domain: str | None = Field(
        default=None, max_length=253, pattern=r"^$|^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$"
    )
    proxy_network: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
