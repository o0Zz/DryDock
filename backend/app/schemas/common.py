from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field


def _stamp_utc(value: datetime) -> datetime:
    """Mark a naive timestamp as UTC.

    SQLite has no timezone type, so everything comes back naive even though we
    only ever store UTC. Without this the browser would read the value as local
    time and display every scan shifted by the machine's offset.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_stamp_utc)]


class PruneResult(BaseModel):
    deleted: list[str] = Field(default_factory=list)
    space_reclaimed: int = 0
