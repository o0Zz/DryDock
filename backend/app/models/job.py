from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


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
    CONTAINER_UPDATE = "container_update"
    PROJECT_ACTION = "project_action"
    IMAGE_PRUNE = "image_prune"
    VOLUME_PRUNE = "volume_prune"
    NETWORK_PRUNE = "network_prune"
    # Delete, rename or duplicate a stack.
    STACK_CHANGE = "stack_change"
    HOST_UPDATE_CHECK = "host_update_check"
    # Commit, push or pull the repo folder.
    REPO_GIT = "repo_git"


class Job(Base):
    """A long-running background task (trivy scan, update check, compose action).

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
    # Command output (e.g. `docker compose up`), shown once the job ends.
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set for scheduler-triggered runs so the UI can tell them apart.
    trigger: Mapped[str] = mapped_column(String, default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
