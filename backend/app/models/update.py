from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UpdateCheck(Base):
    """Result of comparing an image's local digest against the registry.

    Rows are append-only, like scans: the latest row per image is current.
    """

    __tablename__ = "update_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image: Mapped[str] = mapped_column(String, index=True, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    local_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    remote_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    update_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Newer version tags of the same shape found in the registry's tag list.
    newest_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    newest_same_major_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    tag_error: Mapped[str | None] = mapped_column(String, nullable=True)

    @property
    def has_update(self) -> bool:
        """Either kind of update: same tag rebuilt, or a newer version tag."""
        return self.update_available or bool(self.newest_tag)
