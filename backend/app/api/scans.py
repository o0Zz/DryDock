from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models.job import Job, JobKind
from app.models.scan import Scan
from app.schemas.job import JobRead
from app.schemas.scan import ScanDetail, ScanRequest, ScanSummary
from app.services import history_service, job_service, tasks, trivy_service

router = APIRouter(prefix="/api/scans", tags=["scans"])


@router.get("", response_model=list[ScanSummary])
def list_scans(
    image: str | None = Query(default=None, description="Full scan history for one image"),
    db: Session = Depends(get_db),
) -> list[Scan]:
    return history_service.scans(db, image)


@router.post("/image", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def scan_image(body: ScanRequest) -> Job:
    """Queue a scan of a single image."""
    image = body.image.strip()
    if not image:
        raise HTTPException(status_code=400, detail="image is required")
    return job_service.submit(
        JobKind.SCAN_IMAGE, f"Scan {image}", tasks.scan_runner(lambda: [image])
    )


@router.post("/running", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def scan_running() -> Job:
    """Queue a scan of every distinct image used by running containers."""
    return job_service.submit(
        JobKind.SCAN_RUNNING,
        "Scan running images",
        tasks.scan_runner(tasks.running_images),
    )


@router.post("/compose", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def scan_compose() -> Job:
    """Queue a scan of every image referenced by a Compose file in the repo."""
    return job_service.submit(
        JobKind.SCAN_COMPOSE,
        "Scan Compose images",
        tasks.scan_runner(tasks.compose_images),
    )


@router.get("/{scan_id}", response_model=ScanDetail)
def get_scan(scan_id: int, db: Session = Depends(get_db)) -> ScanDetail:
    scan = db.scalar(
        select(Scan).where(Scan.id == scan_id).options(selectinload(Scan.findings))
    )
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    detail = ScanDetail.model_validate(scan)
    detail.truncated = len(scan.findings) >= trivy_service.MAX_FINDINGS
    return detail
