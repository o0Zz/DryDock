from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.dashboard import DashboardStats
from app.services import docker_service, history_service, repo_service, tasks

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db)) -> DashboardStats:
    stats = DashboardStats()

    projects = repo_service.discover_projects()
    stats.projects = len(projects)
    stats.services = sum(len(project.services) for project in projects)

    try:
        containers = docker_service.list_containers(all_states=True)
        stats.containers_running = sum(
            1 for container in containers if container.state == "running"
        )
        stats.containers_stopped = len(containers) - stats.containers_running
        stats.volumes = len(docker_service.list_volumes())
    except docker_service.DockerUnavailable as exc:
        stats.docker_error = str(exc)

    stats.images_tracked = len(tasks.all_known_images())

    scans = history_service.scans(db)
    stats.images_scanned = len(scans)
    stats.images_critical = sum(1 for scan in scans if scan.critical > 0)
    stats.images_high = sum(1 for scan in scans if scan.high > 0)
    stats.critical_total = sum(scan.critical for scan in scans)
    stats.high_total = sum(scan.high for scan in scans)
    if scans:
        stats.last_scan_at = max(scan.scanned_at for scan in scans)

    checks = history_service.update_checks(db)
    stats.updates_available = sum(1 for check in checks if check.has_update)
    if checks:
        stats.last_update_check_at = max(check.checked_at for check in checks)

    return stats
