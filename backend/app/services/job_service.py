from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.job import Job, JobStatus

logger = logging.getLogger(__name__)

# One worker on purpose: trivy scans and registry lookups are heavy, and a Pi
# running several at once is slower overall than running them back to back.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="drydock-job")

# Finished jobs kept for history before the oldest are pruned.
MAX_HISTORY = 200

ACTIVE_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)

# Only the tail of command output is kept: the end is where errors are.
MAX_OUTPUT = 20_000


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobContext:
    """Handed to a job body so it can report progress as it goes."""

    def __init__(self, db: Session, job: Job) -> None:
        self.db = db
        self.job = job

    def set_total(self, total: int, message: str | None = None) -> None:
        self.job.total = total
        if message is not None:
            self.job.message = message
        self.db.commit()

    def advance(self, message: str | None = None) -> None:
        self.job.done += 1
        if message is not None:
            self.job.message = message
        self.db.commit()

    def note(self, message: str) -> None:
        self.job.message = message
        self.db.commit()

    def set_output(self, output: str) -> None:
        # Committed at once so the output survives the rollback of a failing job.
        self.job.output = output[-MAX_OUTPUT:] or None
        self.db.commit()


JobRunner = Callable[[JobContext], None]


def _prune(db: Session) -> None:
    finished = list(
        db.scalars(
            select(Job)
            .where(Job.status.notin_(ACTIVE_STATUSES))
            .order_by(Job.created_at.desc())
            .offset(MAX_HISTORY)
        )
    )
    for job in finished:
        db.delete(job)
    if finished:
        db.commit()


def find_active(kind: str, label: str) -> Job | None:
    with SessionLocal() as db:
        return db.scalar(
            select(Job).where(
                Job.kind == kind, Job.label == label, Job.status.in_(ACTIVE_STATUSES)
            )
        )


def submit(kind: str, label: str, runner: JobRunner, *, trigger: str = "manual") -> Job:
    """Queue a job. An identical job already in flight is returned as-is."""
    existing = find_active(kind, label)
    if existing is not None:
        logger.info("Reusing in-flight job %s (%s)", existing.id, label)
        return existing

    job = Job(id=uuid4().hex, kind=kind, label=label, status=JobStatus.PENDING, trigger=trigger)
    with SessionLocal() as db:
        db.add(job)
        db.commit()
        db.refresh(job)
        _prune(db)

    _executor.submit(_run, job.id, runner)
    return job


def _run(job_id: str, runner: JobRunner) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("Job %s vanished before it started", job_id)
            return
        job.status = JobStatus.RUNNING
        job.started_at = _utcnow()
        db.commit()

        try:
            runner(JobContext(db, job))
        except Exception as exc:  # noqa: BLE001 - a job failure must not kill the worker
            logger.exception("Job %s (%s) failed", job_id, job.kind)
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.ERROR
                job.error = str(exc)[:1000]
                job.finished_at = _utcnow()
                db.commit()
            return

        job.status = JobStatus.SUCCESS
        job.finished_at = _utcnow()
        db.commit()


def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
