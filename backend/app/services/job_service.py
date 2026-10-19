from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, utcnow
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

# Set when DryDock shuts down, so job bodies that wait on something outside
# this process (a Compose helper container) can let go of it.
stopping = threading.Event()


class Interrupted(Exception):
    """Raised by a job body that lets go because DryDock shuts down.

    The work goes on outside this process, so the job stays active for
    `resume` to pick up at the next start.
    """


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


def _find_active(kind: str, label: str) -> Job | None:
    with SessionLocal() as db:
        return db.scalar(
            select(Job).where(
                Job.kind == kind, Job.label == label, Job.status.in_(ACTIVE_STATUSES)
            )
        )


def resume(job_id: str, runner: JobRunner) -> bool:
    """Run a new body for a job an earlier process left active. False when it is not."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status not in ACTIVE_STATUSES:
            return False
    _executor.submit(_run, job_id, runner)
    return True


def fail_interrupted(keep: Collection[str] = ()) -> int:
    """Mark jobs left pending or running by an earlier process as failed.

    Jobs run in this process's threads, so after a restart (an image update, a
    recreate) nothing runs them any more. Without this they show as running
    forever and block an identical job from being queued. `keep` names the jobs
    `resume` picked up. Call once at startup.
    """
    with SessionLocal() as db:
        jobs = list(
            db.scalars(
                select(Job).where(Job.status.in_(ACTIVE_STATUSES), Job.id.notin_(list(keep)))
            )
        )
        for job in jobs:
            job.status = JobStatus.ERROR
            job.error = "Interrupted: DryDock restarted while this job ran"
            job.finished_at = utcnow()
        db.commit()
    if jobs:
        logger.warning("Marked %d job(s) interrupted by the restart as failed", len(jobs))
    return len(jobs)


def submit(kind: str, label: str, runner: JobRunner, *, trigger: str = "manual") -> Job:
    """Queue a job. An identical job already in flight is returned as-is."""
    existing = _find_active(kind, label)
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
        # A resumed job keeps the start of its first run.
        job.started_at = job.started_at or utcnow()
        db.commit()

        try:
            runner(JobContext(db, job))
        except Interrupted:
            logger.info("Job %s (%s) left to resume after the restart", job_id, job.kind)
            return
        except Exception as exc:  # noqa: BLE001 - a job failure must not kill the worker
            logger.exception("Job %s (%s) failed", job_id, job.kind)
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.ERROR
                job.error = str(exc)[:1000]
                job.finished_at = utcnow()
                db.commit()
            return

        job.status = JobStatus.SUCCESS
        job.finished_at = utcnow()
        db.commit()


def shutdown() -> None:
    stopping.set()
    _executor.shutdown(wait=False, cancel_futures=True)
