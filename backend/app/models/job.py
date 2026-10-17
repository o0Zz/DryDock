from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class JobKind:
    SCAN_IMAGE = "scan_image"
    SCAN_RUNNING = "scan_running"
    SCAN_COMPOSE = "scan_compose"
    UPDATE_CHECK = "update_check"


class Job(Base):
    """A long-running background task (trivy scan, registry update check).

    Scans routinely take minutes on a Pi, which is far too long to hold an HTTP
    request open, so the API hands back one of these and the UI polls it.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, index=True, nullable=False, default=JobStatus.PENDING
    )
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set for scheduler-triggered runs so the UI can tell them apart.
    trigger: Mapped[str] = mapped_column(String, default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
