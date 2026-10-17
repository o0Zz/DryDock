from datetime import datetime

from pydantic import BaseModel, Field


class ContainerRef(BaseModel):
    name: str
    running: bool


class Image(BaseModel):
    id: str
    tags: list[str] = Field(default_factory=list)
    size: int = 0
    created_at: datetime | None = None
    # Containers (any state) created from this image.
    used_by: list[ContainerRef] = Field(default_factory=list)
