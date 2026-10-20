from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.container import Container
from app.schemas.job import JobRead


class ProjectService(BaseModel):
    name: str
    image: str | None = None
    # `url#ref` when the service builds from a git repo; update checks follow its commits.
    git_source: str | None = None


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


class StackRename(BaseModel):
    # Same rule as ProjectCreate: it becomes the folder or file name and the project name.
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=64)


class StackChangeAccepted(BaseModel):
    job: JobRead
    # ID the stack has once the job is done (rename, duplicate).
    project_id: str
