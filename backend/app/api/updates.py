from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.job import Job, JobKind
from app.models.update import UpdateCheck
from app.schemas.job import JobRead
from app.schemas.update import UpdateCheckRequest, UpdateSummary
from app.services import job_service, tasks

router = APIRouter(prefix="/api/updates", tags=["updates"])


def _latest_per_image(db: Session) -> list[UpdateCheck]:
    newest = (
        select(UpdateCheck.image, func.max(UpdateCheck.id).label("check_id"))
        .group_by(UpdateCheck.image)
        .subquery()
    )
    stmt = (
        select(UpdateCheck)
        .join(newest, UpdateCheck.id == newest.c.check_id)
        .order_by(UpdateCheck.checked_at.desc())
    )
    return list(db.scalars(stmt))


@router.get("", response_model=list[UpdateSummary])
def list_updates(
    image: str | None = Query(default=None, description="Full check history for one image"),
    db: Session = Depends(get_db),
) -> list[UpdateCheck]:
    if image:
        return list(
            db.scalars(
                select(UpdateCheck)
                .where(UpdateCheck.image == image)
                .order_by(UpdateCheck.checked_at.desc())
            )
        )
    return _latest_per_image(db)


@router.post("/check", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def check_updates(req: UpdateCheckRequest | None = None) -> Job:
    """Compare local image digests against their registries.

    With no body, every known image is checked (running containers plus every
    image named in a Compose file).
    """
    images = [i.strip() for i in (req.images or [])] if req else []
    images = [i for i in images if i]
    if images:
        label = f"Update check: {', '.join(images[:3])}" + ("..." if len(images) > 3 else "")
        return job_service.submit(
            JobKind.UPDATE_CHECK, label, tasks.update_check_runner(lambda: images)
        )
    return job_service.submit(
        JobKind.UPDATE_CHECK,
        "Update check: all known images",
        tasks.update_check_runner(tasks.all_known_images),
    )
