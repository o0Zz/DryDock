from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.container import Container
from app.schemas.dashboard import (
    ContainerAlert,
    DashboardStats,
    HostUsage,
    ImageRisk,
    ImageUpdate,
)
from app.services import docker_service, history_service, host_service, repo_service, tasks

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# How many images the "needs attention" lists show; the page links to the rest.
LIST_LIMIT = 5


def _needs_attention(container: Container) -> bool:
    # Docker appends the health check result to the status, e.g. "Up 2 hours (unhealthy)".
    return container.state == "restarting" or "(unhealthy)" in container.status


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
        stats.unhealthy_containers = [
            ContainerAlert(id=container.id, name=container.name, status=container.status)
            for container in containers
            if _needs_attention(container)
        ]
        stats.volumes = len(docker_service.list_volumes())
        stats.host = docker_service.host_info()
    except docker_service.DockerUnavailable as exc:
        stats.docker_error = str(exc)

    tracked = set(tasks.all_known_images())
    stats.images_tracked = len(tracked)

    # Scan and update history keep images that were since removed or replaced by
    # a newer tag; counting them would keep the dashboard red after an update.
    scans = [scan for scan in history_service.scans(db) if scan.image in tracked]
    stats.images_scanned = len(scans)
    stats.images_critical = sum(1 for scan in scans if scan.critical > 0)
    stats.images_high = sum(1 for scan in scans if scan.high > 0)
    stats.critical_total = sum(scan.critical for scan in scans)
    stats.high_total = sum(scan.high for scan in scans)
    if scans:
        stats.last_scan_at = max(scan.scanned_at for scan in scans)
    worst = sorted(
        (scan for scan in scans if scan.critical or scan.high),
        key=lambda scan: (scan.critical, scan.high),
        reverse=True,
    )
    stats.most_vulnerable = [
        ImageRisk(image=scan.image, critical=scan.critical, high=scan.high)
        for scan in worst[:LIST_LIMIT]
    ]

    checks = [check for check in history_service.update_checks(db) if check.image in tracked]
    with_update = [check for check in checks if check.has_update]
    stats.updates_available = len(with_update)
    stats.updates = [
        ImageUpdate(image=check.image, newest_tag=check.newest_tag, rebuilt=check.update_available)
        for check in with_update[:LIST_LIMIT]
    ]
    if checks:
        stats.last_update_check_at = max(check.checked_at for check in checks)

    return stats


@router.get("/host", response_model=HostUsage)
def host_usage() -> HostUsage:
    """Live CPU, memory and temperature; the dashboard polls this on its own."""
    return host_service.usage()
