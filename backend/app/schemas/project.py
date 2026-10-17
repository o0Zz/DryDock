from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.container import Container


class ProjectService(BaseModel):
    name: str
    image: str | None = None


class Project(BaseModel):
    id: str
    name: str
    compose_path: str
    relative_path: str
    modified_at: datetime
    services: list[ProjectService]
    # Containers Docker currently associates with this Compose file. Empty when
    # the stack is down or the daemon is unreachable.
    containers: list[Container] = []


class ProjectCreate(BaseModel):
    # Becomes the folder name and so the Compose project name, which Docker
    # restricts to lowercase letters, digits, '-' and '_'.
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=64)
    content: str
