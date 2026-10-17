from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VolumeUser(BaseModel):
    """A container mounting the volume, and where."""

    id: str
    name: str
    running: bool
    destination: str
    rw: bool = True


class Volume(BaseModel):
    name: str
    driver: str
    mountpoint: str
    scope: str | None = None
    created_at: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    compose_project: str | None = None
    used_by: list[VolumeUser] = Field(default_factory=list)


class VolumeEntry(BaseModel):
    """One file or folder inside a volume."""

    name: str
    type: Literal["dir", "file", "link", "other"]
    size: int
    modified_at: datetime | None = None


class VolumeListing(BaseModel):
    path: str
    entries: list[VolumeEntry]
    # More entries than the listing returns; the rest are left out.
    truncated: bool = False


class VolumeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    driver: str = "local"
    labels: dict[str, str] = Field(default_factory=dict)
