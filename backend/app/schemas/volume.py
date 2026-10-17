from datetime import datetime

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


class VolumeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    driver: str = "local"
    labels: dict[str, str] = Field(default_factory=dict)
