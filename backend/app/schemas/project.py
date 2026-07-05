from datetime import datetime

from pydantic import BaseModel


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
