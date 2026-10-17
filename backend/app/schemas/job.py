from pydantic import BaseModel, ConfigDict

from app.schemas.common import UtcDatetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    label: str
    status: str
    total: int = 0
    done: int = 0
    message: str | None = None
    error: str | None = None
    output: str | None = None
    trigger: str = "manual"
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
