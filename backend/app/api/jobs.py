from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.job import Job
from app.schemas.job import JobRead
from app.services import job_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobRead])
def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    active: bool = Query(default=False, description="Only jobs that are pending or running"),
    db: Session = Depends(get_db),
) -> list[Job]:
    query = select(Job).order_by(Job.created_at.desc())
    # Active jobs are few, so they come back in full regardless of `limit`.
    if active:
        query = query.where(Job.status.in_(job_service.ACTIVE_STATUSES))
    else:
        query = query.limit(limit)
    return list(db.scalars(query))


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
