"""Periodic scans and update checks, driven by the runtime settings."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import SessionLocal
from app.models.job import JobKind
from app.services import blocklist_service, docker_service, job_service, settings_service, tasks

logger = logging.getLogger(__name__)

SCAN_JOB_ID = "scheduled-scan"
UPDATE_JOB_ID = "scheduled-update-check"
BLOCKLIST_JOB_ID = "scheduled-blocklist"

_scheduler: BackgroundScheduler | None = None


def _run_scheduled_scan() -> None:
    job_service.submit(
        JobKind.SCAN_RUNNING,
        "Scheduled scan of running images",
        tasks.scan_runner(docker_service.running_images, notify=True),
        trigger="schedule",
    )


def _run_scheduled_update_check() -> None:
    job_service.submit(
        JobKind.UPDATE_CHECK,
        "Scheduled update check",
        tasks.update_check_runner(tasks.all_known_images, notify=True),
        trigger="schedule",
    )
    # Host packages follow the image update schedule, so one switch covers both.
    job_service.submit(
        JobKind.HOST_UPDATE_CHECK,
        "Scheduled host update check",
        tasks.host_update_check_runner(notify=True),
        trigger="schedule",
    )


def run_blocklist() -> None:
    job_service.submit(
        JobKind.BLOCKLIST_APPLY,
        "IP blocklist refresh",
        tasks.blocklist_apply_runner(),
        trigger="schedule",
    )


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.start()
    reconfigure()
    # A host reboot clears the nftables table, and DryDock starts with the host.
    with SessionLocal() as db:
        if blocklist_service.get_config(db).enabled:
            run_blocklist()


def reconfigure() -> None:
    """Re-read settings and (re)install the periodic jobs. Safe to call anytime."""
    if _scheduler is None:
        return

    with SessionLocal() as db:
        config = settings_service.get_all(db)

    _apply(
        SCAN_JOB_ID,
        enabled=config["scan_schedule_enabled"],
        hours=config["scan_interval_hours"],
        func=_run_scheduled_scan,
        name="CVE scan of running images",
    )
    _apply(
        UPDATE_JOB_ID,
        enabled=config["update_check_enabled"],
        hours=config["update_check_interval_hours"],
        func=_run_scheduled_update_check,
        name="Registry update check",
    )
    _apply(
        BLOCKLIST_JOB_ID,
        enabled=blocklist_service.config_from(config).enabled,
        hours=blocklist_service.INTERVAL_HOURS,
        func=run_blocklist,
        name="IP blocklist refresh",
    )


def _apply(job_id: str, *, enabled: bool, hours: int, func: Callable[[], None], name: str) -> None:
    assert _scheduler is not None
    if not enabled:
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
            logger.info("Disabled schedule %s", job_id)
        return

    # replace_existing keeps reconfigure() idempotent when only the interval changed.
    _scheduler.add_job(
        func,
        trigger=IntervalTrigger(hours=hours),
        id=job_id,
        name=name,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Scheduled %s every %sh", job_id, hours)


def next_run_times() -> dict[str, datetime | None]:
    """Next fire time per schedule, for display in the settings UI."""
    result: dict[str, datetime | None] = {}
    for job_id in (SCAN_JOB_ID, UPDATE_JOB_ID):
        job = _scheduler.get_job(job_id) if _scheduler else None
        result[job_id] = job.next_run_time if job else None
    return result


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
