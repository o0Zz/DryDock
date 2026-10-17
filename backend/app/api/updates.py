from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.job import Job, JobKind
from app.models.update import UpdateCheck
from app.schemas.job import JobRead
from app.schemas.update import UpdateCheckRequest, UpdateSummary
from app.services import history_service, job_service, tasks

router = APIRouter(prefix="/api/updates", tags=["updates"])


@router.get("", response_model=list[UpdateSummary])
def list_updates(
    image: str | None = Query(default=None, description="Full check history for one image"),
    db: Session = Depends(get_db),
) -> list[UpdateCheck]:
    return history_service.update_checks(db, image)


@router.post("/check", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def check_updates(body: UpdateCheckRequest | None = None) -> Job:
    """Compare local image digests against their registries.

    With no body, every known image is checked (running containers plus every
    image named in a Compose file).
    """
    requested = body.images if body and body.images else []
    images = [image.strip() for image in requested if image.strip()]
    if images:
        label = f"Update check: {', '.join(images[:3])}" + ("..." if len(images) > 3 else "")
        runner = tasks.update_check_runner(lambda: images)
    else:
        label = "Update check: all known images"
        runner = tasks.update_check_runner(tasks.all_known_images)
    return job_service.submit(JobKind.UPDATE_CHECK, label, runner)
