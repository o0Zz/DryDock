from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime


class ApiTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    prefix: str
    created_at: UtcDatetime
    last_used_at: UtcDatetime | None = None


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiTokenCreated(ApiTokenRead):
    # The full token. Returned once, at creation; only its hash is stored.
    token: str
