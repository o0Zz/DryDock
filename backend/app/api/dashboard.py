from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.scans import _latest_per_image as latest_scans
from app.api.updates import _latest_per_image as latest_updates
from app.core.database import get_db
from app.schemas.dashboard import DashboardStats
from app.services import docker_service, repo_service, tasks

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db)) -> DashboardStats:
    stats = DashboardStats()

    projects = repo_service.discover_projects()
    stats.projects = len(projects)
    stats.services = sum(len(p.services) for p in projects)

    try:
        containers = docker_service.list_containers(all_states=True)
        stats.containers_running = sum(1 for c in containers if c.state == "running")
        stats.containers_stopped = len(containers) - stats.containers_running
        stats.volumes = len(docker_service.list_volumes())
    except docker_service.DockerUnavailable as exc:
        stats.docker_error = str(exc)

    stats.images_tracked = len(tasks.all_known_images())

    scans = latest_scans(db)
    stats.images_scanned = len(scans)
    stats.images_critical = sum(1 for s in scans if s.critical > 0)
    stats.images_high = sum(1 for s in scans if s.high > 0)
    stats.critical_total = sum(s.critical for s in scans)
    stats.high_total = sum(s.high for s in scans)
    if scans:
        stats.last_scan_at = max(s.scanned_at for s in scans)

    checks = latest_updates(db)
    stats.updates_available = sum(1 for c in checks if c.update_available)
    if checks:
        stats.last_update_check_at = max(c.checked_at for c in checks)

    return stats
