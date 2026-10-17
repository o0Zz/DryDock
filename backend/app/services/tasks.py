"""Bodies of the long-running background jobs.

Shared by the API (manual runs) and the scheduler (automatic runs) so both paths
behave identically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from sqlalchemy.orm import Session

from app.models.scan import Scan, ScanFinding
from app.models.update import UpdateCheck
from app.services import (
    docker_service,
    notify_service,
    repo_service,
    settings_service,
    trivy_service,
    update_service,
)
from app.services.job_service import JobContext

logger = logging.getLogger(__name__)

ImageResolver = Callable[[], list[str]]


# --- Persistence -------------------------------------------------------------


def store_scan(db: Session, image: str) -> Scan:
    """Scan one image and persist the outcome, successful or not."""
    try:
        result = trivy_service.scan_image(image)
    except trivy_service.TrivyError as exc:
        logger.warning("Scan of %s failed: %s", image, exc)
        scan = Scan(image=image, error=str(exc)[:1000])
        db.add(scan)
        db.commit()
        db.refresh(scan)
        return scan

    scan = Scan(image=image, **result.counts)
    scan.findings = [
        ScanFinding(
            vulnerability_id=f.vulnerability_id,
            severity=f.severity,
            package_name=f.package_name,
            installed_version=f.installed_version,
            fixed_version=f.fixed_version,
            title=f.title,
            primary_url=f.primary_url,
            target=f.target,
        )
        for f in result.findings
    ]
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def store_update_check(db: Session, image: str) -> UpdateCheck:
    result = update_service.check_image(image)
    row = UpdateCheck(
        image=result.image,
        local_digest=result.local_digest,
        remote_digest=result.remote_digest,
        update_available=result.update_available,
        error=result.error[:1000] if result.error else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- Image sources -----------------------------------------------------------


def running_images() -> list[str]:
    return docker_service.running_images()


def compose_images() -> list[str]:
    return repo_service.referenced_images()


def all_known_images() -> list[str]:
    """Every image worth tracking: in use by a container, or named in a Compose file."""
    images = set(compose_images())
    try:
        images.update(running_images())
    except docker_service.DockerUnavailable as exc:
        logger.warning("Could not list running images: %s", exc)
    return sorted(images)


# --- Job bodies --------------------------------------------------------------


def _summarise_scans(scans: Sequence[Scan]) -> str:
    failed = sum(1 for s in scans if s.error)
    critical = sum(s.critical for s in scans)
    high = sum(s.high for s in scans)
    parts = [f"{len(scans)} image(s) scanned", f"{critical} critical", f"{high} high"]
    if failed:
        parts.append(f"{failed} failed")
    return ", ".join(parts)


def _maybe_notify_scans(db: Session, scans: Sequence[Scan]) -> None:
    config = settings_service.get_all(db)
    if not config["notify_on_critical"]:
        return
    offenders = [s for s in scans if s.critical > 0]
    if not offenders:
        return
    notify_service.send(
        config["notify_webhook_url"],
        "scan.critical",
        {
            "images": [
                {"image": s.image, "critical": s.critical, "high": s.high, "fixable": s.fixable}
                for s in offenders
            ],
            "summary": _summarise_scans(scans),
        },
    )


def _maybe_notify_updates(db: Session, checks: Sequence[UpdateCheck]) -> None:
    config = settings_service.get_all(db)
    if not config["notify_on_update"]:
        return
    available = [c for c in checks if c.update_available]
    if not available:
        return
    notify_service.send(
        config["notify_webhook_url"],
        "update.available",
        {"images": [c.image for c in available]},
    )


def scan_runner(resolve: ImageResolver, *, notify: bool = False):
    """Build a job body that scans whatever `resolve` returns at run time."""

    def run(ctx: JobContext) -> None:
        images = resolve()
        ctx.set_total(len(images), f"{len(images)} image(s) queued")
        if not images:
            ctx.note("No images to scan")
            return
        scans: list[Scan] = []
        for image in images:
            ctx.note(f"Scanning {image}")
            scans.append(store_scan(ctx.db, image))
            ctx.advance()
        ctx.note(_summarise_scans(scans))
        if notify:
            _maybe_notify_scans(ctx.db, scans)

    return run


def update_check_runner(resolve: ImageResolver, *, notify: bool = False):
    """Build a job body that compares local vs registry digests."""

    def run(ctx: JobContext) -> None:
        images = resolve()
        ctx.set_total(len(images), f"{len(images)} image(s) queued")
        if not images:
            ctx.note("No images to check")
            return
        checks: list[UpdateCheck] = []
        for image in images:
            ctx.note(f"Checking {image}")
            checks.append(store_update_check(ctx.db, image))
            ctx.advance()
        outdated = sum(1 for c in checks if c.update_available)
        failed = sum(1 for c in checks if c.error)
        message = f"{len(checks)} image(s) checked, {outdated} with updates"
        if failed:
            message += f", {failed} failed"
        ctx.note(message)
        if notify:
            _maybe_notify_updates(ctx.db, checks)

    return run
