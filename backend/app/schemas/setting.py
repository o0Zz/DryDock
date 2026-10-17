from datetime import datetime

from pydantic import BaseModel, Field


class SettingsRead(BaseModel):
    scan_schedule_enabled: bool
    scan_interval_hours: int
    update_check_enabled: bool
    update_check_interval_hours: int
    notify_webhook_url: str
    notify_on_critical: bool
    notify_on_update: bool
    # Computed, read-only context for the settings screen.
    next_scan_run: datetime | None = None
    next_update_run: datetime | None = None
    repo_path: str
    data_path: str


class SettingsUpdate(BaseModel):
    scan_schedule_enabled: bool | None = None
    scan_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    update_check_enabled: bool | None = None
    update_check_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    notify_webhook_url: str | None = Field(default=None, max_length=2000)
    notify_on_critical: bool | None = None
    notify_on_update: bool | None = None
