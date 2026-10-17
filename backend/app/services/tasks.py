"""Bodies of the long-running background jobs.

Shared by the API (manual runs) and the scheduler (automatic runs) so both paths
behave identically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import TypeVar

from sqlalchemy.orm import Session

from app.models.scan import Scan, ScanFinding
from app.models.update import UpdateCheck
from app.services import (
    compose_service,
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
T = TypeVar("T")


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
    scan.findings = [ScanFinding(**asdict(f)) for f in result.findings]
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
        newest_tag=result.newest_tag,
        newest_same_major_tag=result.newest_same_major_tag,
        tag_error=result.tag_error[:1000] if result.tag_error else None,
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
    available = [c for c in checks if c.has_update]
    if not available:
        return
    notify_service.send(
        config["notify_webhook_url"],
        "update.available",
        {
            "images": [c.image for c in available],
            "newer_tags": {c.image: c.newest_tag for c in available if c.newest_tag},
        },
    )


def _each_image(
    ctx: JobContext,
    resolve: ImageResolver,
    store: Callable[[Session, str], T],
    *,
    progress: str,
    empty: str,
) -> list[T]:
    """Run `store` on every image `resolve` returns, reporting progress as it goes.

    The frontend reads the "Scanning <image>" message to tell which image is busy.
    """
    images = resolve()
    ctx.set_total(len(images), f"{len(images)} image(s) queued")
    if not images:
        ctx.note(empty)
        return []
    rows: list[T] = []
    for image in images:
        ctx.note(f"{progress} {image}")
        rows.append(store(ctx.db, image))
        ctx.advance()
    return rows


def scan_runner(resolve: ImageResolver, *, notify: bool = False):
    """Build a job body that scans whatever `resolve` returns at run time."""

    def run(ctx: JobContext) -> None:
        scans = _each_image(
            ctx, resolve, store_scan, progress="Scanning", empty="No images to scan"
        )
        if not scans:
            return
        ctx.note(_summarise_scans(scans))
        if notify:
            _maybe_notify_scans(ctx.db, scans)

    return run


def update_check_runner(resolve: ImageResolver, *, notify: bool = False):
    """Build a job body that compares local vs registry digests."""

    def run(ctx: JobContext) -> None:
        checks = _each_image(
            ctx, resolve, store_update_check, progress="Checking", empty="No images to check"
        )
        if not checks:
            return
        outdated = sum(1 for c in checks if c.has_update)
        failed = sum(1 for c in checks if c.error)
        message = f"{len(checks)} image(s) checked, {outdated} with updates"
        if failed:
            message += f", {failed} failed"
        ctx.note(message)
        if notify:
            _maybe_notify_updates(ctx.db, checks)

    return run


def container_update_runner(
    compose_path: Path, service: str, image: str, *, project_name: str | None = None
):
    """Build a job body that pulls one service's image and recreates its container."""

    def run(ctx: JobContext) -> None:
        ctx.set_total(3, f"Pulling {image}")
        compose_service.pull_service(compose_path, service, project_name=project_name)
        ctx.advance(f"Recreating {service}")
        compose_service.recreate_service(compose_path, service, project_name=project_name)
        # Refresh the stored check so the "update available" badge clears.
        ctx.advance(f"Re-checking {image}")
        store_update_check(ctx.db, image)
        ctx.advance(f"{service} updated to the latest {image}")

    return run


def project_action_runner(compose_path: Path, action: str):
    """Build a job body that runs `docker compose <action>` on a whole project."""

    def run(ctx: JobContext) -> None:
        ctx.set_total(1, f"docker compose {action}")
        result = compose_service.run_action(compose_path, action)
        # docker compose writes its progress to stderr, so keep both streams.
        ctx.set_output("\n".join(s for s in (result["stdout"], result["stderr"]) if s))
        if result["exit_code"] != 0:
            detail = (result["stderr"] or result["stdout"] or "").strip()[-1000:]
            raise compose_service.ComposeError(
                f"`docker compose {action}` failed (exit {result['exit_code']}): {detail}"
            )
        ctx.advance(f"docker compose {action} done")

    return run


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def image_prune_runner(*, all_unused: bool):
    """Build a job body that prunes dangling images, or every unused one."""

    def run(ctx: JobContext) -> None:
        result = docker_service.prune_images(all_unused=all_unused)
        ctx.note(
            f"Pruned {len(result.deleted)} image(s), "
            f"reclaimed {_format_bytes(result.space_reclaimed)}"
        )

    return run


def volume_prune_runner():
    """Build a job body that removes every volume no container uses."""

    def run(ctx: JobContext) -> None:
        result = docker_service.prune_volumes()
        ctx.note(
            f"Pruned {len(result.deleted)} volume(s), "
            f"reclaimed {_format_bytes(result.space_reclaimed)}"
        )

    return run
