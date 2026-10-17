from pydantic import BaseModel, ConfigDict

from app.schemas.common import UtcDatetime


class UpdateCheckRequest(BaseModel):
    # Omit to check every known image (running containers + Compose files).
    images: list[str] | None = None


class UpdateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    image: str
    checked_at: UtcDatetime
    local_digest: str | None = None
    remote_digest: str | None = None
    update_available: bool = False
    error: str | None = None
