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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scan import Scan, ScanFinding
from app.models.update import UpdateCheck
from app.schemas.common import PruneResult
from app.schemas.fail2ban import Fail2banConfig
from app.schemas.project import Project
from app.services import (
    blocklist_service,
    compose_service,
    docker_service,
    fail2ban_config_service,
    git_service,
    host_updates_service,
    job_service,
    notify_service,
    repo_git_service,
    repo_service,
    settings_service,
    stack_service,
    trivy_service,
    update_service,
)
from app.services.job_service import JobContext, JobRunner

logger = logging.getLogger(__name__)

ImageResolver = Callable[[], list[str]]
RowT = TypeVar("RowT")


# --- Persistence -------------------------------------------------------------


def _store_scan(db: Session, image: str) -> Scan:
    """Scan one image and persist the outcome, successful or not."""
    try:
        result = trivy_service.scan_image(image)
    except trivy_service.TrivyError as exc:
        logger.warning("Scan of %s failed: %s", image, exc)
        scan = Scan(image=image, error=str(exc)[:1000])
    else:
        scan = Scan(image=image, **result.counts)
        scan.findings = [ScanFinding(**asdict(finding)) for finding in result.findings]
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def _last_built_commit(db: Session, image: str) -> str | None:
    """Commit of the last git check of an image, which carries the commit it was built from."""
    last = db.scalar(
        select(UpdateCheck).where(UpdateCheck.image == image).order_by(UpdateCheck.id.desc())
    )
    return last.local_digest if last is not None and last.git_source else None


def store_update_check(
    db: Session,
    image: str,
    *,
    git: git_service.GitSource | None = None,
    built: bool = False,
) -> UpdateCheck:
    """Check one image and store the result.

    `git` is the repo the image builds from, if any; `built` means it was just
    built, so the current commit is what it runs.
    """
    if git is not None:
        baseline = None if built else _last_built_commit(db, image)
        result = update_service.check_git(image, git, baseline)
    else:
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
        git_source=result.git_source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- Image sources -----------------------------------------------------------


def git_images(compose_path: Path | None = None) -> dict[str, git_service.GitSource]:
    """Images built from a git repo, with that repo, optionally for one Compose file.

    A service without `image:` gets a name Compose picks, so it is read from the
    service's containers.
    """
    projects = repo_service.discover_projects()
    if compose_path is not None:
        projects = [project for project in projects if Path(project.compose_path) == compose_path]
    projects = repo_service.attach_containers(projects)
    sources: dict[str, git_service.GitSource] = {}
    for project in projects:
        for service in project.services:
            source = git_service.parse_build(service.git_source)
            if source is None:
                continue
            if service.image:
                sources[service.image] = source
                continue
            for container in project.containers:
                if container.compose_service == service.name:
                    sources[container.image] = source
    return sources


def all_known_images() -> list[str]:
    """Every image worth tracking: in use by a container, or named in a Compose file."""
    images = set(repo_service.referenced_images())
    try:
        images.update(docker_service.running_images())
    except docker_service.DockerUnavailable as exc:
        logger.warning("Could not list running images: %s", exc)
    return sorted(images)


# --- Job bodies --------------------------------------------------------------


def _summarise_scans(scans: Sequence[Scan]) -> str:
    failed = sum(1 for scan in scans if scan.error)
    critical = sum(scan.critical for scan in scans)
    high = sum(scan.high for scan in scans)
    parts = [f"{len(scans)} image(s) scanned", f"{critical} critical", f"{high} high"]
    if failed:
        parts.append(f"{failed} failed")
    return ", ".join(parts)


def _notify(db: Session, flag: str, event: str, payload: dict[str, object]) -> None:
    """Send a webhook event when its setting is on."""
    config = settings_service.get_all(db)
    if config[flag]:
        notify_service.send(config["notify_webhook_url"], event, payload)


def _maybe_notify_scans(db: Session, scans: Sequence[Scan]) -> None:
    offenders = [scan for scan in scans if scan.critical > 0]
    if not offenders:
        return
    _notify(
        db,
        "notify_on_critical",
        "scan.critical",
        {
            "images": [
                {
                    "image": scan.image,
                    "critical": scan.critical,
                    "high": scan.high,
                    "fixable": scan.fixable,
                }
                for scan in offenders
            ],
            "summary": _summarise_scans(scans),
        },
    )


def _maybe_notify_updates(db: Session, checks: Sequence[UpdateCheck]) -> None:
    available = [check for check in checks if check.has_update]
    if not available:
        return
    _notify(
        db,
        "notify_on_update",
        "update.available",
        {
            "images": [check.image for check in available],
            "newer_tags": {
                check.image: check.newest_tag for check in available if check.newest_tag
            },
        },
    )


def _each_image(
    ctx: JobContext,
    resolve: ImageResolver,
    store: Callable[[Session, str], RowT],
    *,
    progress: str,
    empty: str,
) -> list[RowT]:
    """Run `store` on every image `resolve` returns, reporting progress as it goes.

    The frontend reads the "Scanning <image>" message to tell which image is busy.
    """
    images = resolve()
    ctx.set_total(len(images), f"{len(images)} image(s) queued")
    if not images:
        ctx.note(empty)
        return []
    rows: list[RowT] = []
    for image in images:
        ctx.note(f"{progress} {image}")
        rows.append(store(ctx.db, image))
        ctx.advance()
    return rows


def scan_runner(resolve: ImageResolver, *, notify: bool = False) -> JobRunner:
    """Build a job body that scans whatever `resolve` returns at run time."""

    def run(ctx: JobContext) -> None:
        scans = _each_image(
            ctx, resolve, _store_scan, progress="Scanning", empty="No images to scan"
        )
        if not scans:
            return
        ctx.note(_summarise_scans(scans))
        if notify:
            _maybe_notify_scans(ctx.db, scans)

    return run


def update_check_runner(resolve: ImageResolver, *, notify: bool = False) -> JobRunner:
    """Build a job body that checks images for updates: digest, newer tags, git commits."""

    def run(ctx: JobContext) -> None:
        sources = git_images()
        checks = _each_image(
            ctx,
            resolve,
            lambda db, image: store_update_check(db, image, git=sources.get(image)),
            progress="Checking",
            empty="No images to check",
        )
        if not checks:
            return
        outdated = sum(1 for check in checks if check.has_update)
        failed = sum(1 for check in checks if check.error)
        message = f"{len(checks)} image(s) checked, {outdated} with updates"
        if failed:
            message += f", {failed} failed"
        ctx.note(message)
        if notify:
            _maybe_notify_updates(ctx.db, checks)

    return run


def fail2ban_apply_runner(config: Fail2banConfig) -> JobRunner:
    """Build a job body that writes DryDock's fail2ban jails on the host and reloads it."""

    def run(ctx: JobContext) -> None:
        ctx.set_total(1, "Writing the jails and reloading fail2ban")
        ctx.set_output(fail2ban_config_service.apply(config))
        enabled = sum(jail.enabled for jail in config.jails)
        ctx.advance(f"fail2ban reloaded: {enabled} DryDock jail(s) enabled")

    return run


def blocklist_apply_runner() -> JobRunner:
    """Build a job body that loads the IP blocklist on the host, or removes it when off.

    It reads the config when it runs, so a scheduled refresh follows the last save.
    """

    def run(ctx: JobContext) -> None:
        config = blocklist_service.get_config(ctx.db)
        if not config.enabled:
            ctx.set_total(1, "Removing the blocklist from the host")
            ctx.set_output(blocklist_service.apply(config))
            ctx.advance("Blocklist off")
            return
        ctx.set_total(1, "Downloading the lists and loading them on the host")
        output = blocklist_service.apply(config)
        status = blocklist_service.status()
        errors = [source.error for source in status.sources if source.error] if status else []
        ctx.set_output("\n".join([output.strip(), *errors]))
        entries = status.entries if status else 0
        message = f"Blocklist loaded: {entries} ranges"
        if errors:
            message += f", {len(errors)} list(s) kept from the previous download"
        ctx.advance(message)

    return run


def host_update_check_runner(*, notify: bool = False) -> JobRunner:
    """Build a job body that reads the host's pending OS package updates."""

    def run(ctx: JobContext) -> None:
        ctx.set_total(1, "Reading the host's package state")
        row = host_updates_service.check(ctx.db)
        if row.error:
            raise docker_service.HostCommandFailed(row.error)
        if not row.supported:
            ctx.advance("The host has no apt: only Debian and Ubuntu are supported")
            return
        message = f"{row.upgradable} host package(s) to update, {row.security} security"
        if row.reboot_required:
            message += ", reboot required"
        ctx.advance(message)
        if notify and row.security:
            _notify(
                ctx.db,
                "notify_on_update",
                "host.updates",
                {
                    "upgradable": row.upgradable,
                    "security": row.security,
                    "reboot_required": row.reboot_required,
                },
            )

    return run


def container_update_runner(
    compose_path: Path, service: str, image: str, *, project_name: str | None = None
) -> JobRunner:
    """Build a job body that brings one service's image up to date and recreates its container.

    Pull covers registry images, build covers `build:` services (a git one
    fetches its ref again); each is a no-op for the other kind.
    """

    def run(ctx: JobContext) -> None:
        ctx.set_total(4, f"Pulling {image}")
        compose_service.pull_service(compose_path, service, project_name=project_name)
        ctx.advance(f"Building {service}")
        compose_service.build_service(compose_path, service, project_name=project_name)
        ctx.advance(f"Recreating {service}")
        compose_service.recreate_service(compose_path, service, project_name=project_name, ctx=ctx)
        # Refresh the stored check so the "update available" badge clears.
        ctx.advance(f"Re-checking {image}")
        source = git_images(compose_path).get(image)
        store_update_check(ctx.db, image, git=source, built=source is not None)
        ctx.advance(f"{service} updated to the latest {image}")

    return run


def project_action_runner(
    compose_path: Path, action: str, *, project_name: str | None = None
) -> JobRunner:
    """Build a job body that runs `docker compose <action>` on a whole project."""

    def run(ctx: JobContext) -> None:
        ctx.set_total(1, f"docker compose {action}")
        result = compose_service.run_action(
            compose_path, action, project_name=project_name, ctx=ctx
        )
        ctx.set_output(compose_service.joined_output(result["stdout"], result["stderr"]))
        compose_service.check(action, result["exit_code"], result["stdout"], result["stderr"])
        if action == "pull":
            # "Pull & build" rebuilt the git services: their current commit is now built.
            for built_image, source in git_images(compose_path).items():
                store_update_check(ctx.db, built_image, git=source, built=True)
        ctx.advance(f"docker compose {action} done")

    return run


def _resume_runner(helper_id: str) -> JobRunner:
    """Job body that waits for a Compose helper started by an earlier DryDock process."""

    def run(ctx: JobContext) -> None:
        ctx.note("Waiting for docker compose, started before DryDock restarted")
        exit_code, output = compose_service.follow(helper_id, ctx)
        if exit_code != 0:
            raise compose_service.ComposeError(
                f"`docker compose` failed (exit {exit_code}): {output.strip()[-1000:]}"
            )
        # Steps after the Compose run (a container update's re-check) are skipped.
        ctx.job.done = ctx.job.total
        ctx.note("docker compose done; DryDock restarted meanwhile")

    return run


def resume_compose_jobs() -> set[str]:
    """Pick up jobs whose Compose helper outlived the last DryDock process.

    DryDock updating itself always ends like this: Compose stops it halfway
    through the job. Helpers of jobs that are no longer active are removed.
    Returns the IDs of the resumed jobs. Call once at startup.
    """
    try:
        helpers = docker_service.compose_helpers()
    except docker_service.DockerUnavailable:
        return set()
    resumed: set[str] = set()
    for job_id, helper_id in helpers.items():
        if job_service.resume(job_id, _resume_runner(helper_id)):
            resumed.add(job_id)
        else:
            docker_service.remove_helper(helper_id)
    if resumed:
        logger.info("Resumed %d job(s) whose docker compose run outlived the restart", len(resumed))
    return resumed


def stack_delete_runner(
    project: Project, *, project_name: str | None, stop: bool, remove_volumes: bool
) -> JobRunner:
    """Build a job body that brings a stack down, backs it up and deletes its files."""

    def run(ctx: JobContext) -> None:
        ctx.set_total(2)
        if stop or remove_volumes:
            ctx.note("docker compose down")
            ctx.set_output(
                compose_service.down(
                    Path(project.compose_path),
                    remove_volumes=remove_volumes,
                    project_name=project_name,
                    ctx=ctx,
                )
            )
        ctx.advance("Backing up and deleting files")
        backup = stack_service.delete(project)
        ctx.advance(f"Deleted {project.name}. Backup: {backup}")

    return run


def stack_rename_runner(
    project: Project, new_name: str, *, project_name: str | None, stop: bool
) -> JobRunner:
    """Build a job body that brings a stack down, then moves it to a new name.

    It stays down: its named volumes belong to the old Compose project name.
    """

    def run(ctx: JobContext) -> None:
        ctx.set_total(2)
        if stop:
            ctx.note("docker compose down")
            ctx.set_output(
                compose_service.down(Path(project.compose_path), project_name=project_name, ctx=ctx)
            )
        ctx.advance(f"Renaming to {new_name}")
        stack_service.rename(project, new_name)
        ctx.advance(f"Renamed {project.name} to {new_name}")

    return run


def stack_duplicate_runner(project: Project, new_name: str) -> JobRunner:
    """Build a job body that copies a stack under a new name, without starting it."""

    def run(ctx: JobContext) -> None:
        ctx.set_total(1, f"Copying to {new_name}")
        stack_service.duplicate(project, new_name)
        ctx.advance(f"Duplicated {project.name} as {new_name}")

    return run


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _prune_runner(prune: Callable[[], PruneResult], noun: str) -> JobRunner:
    def run(ctx: JobContext) -> None:
        result = prune()
        ctx.note(
            f"Pruned {len(result.deleted)} {noun}(s), "
            f"reclaimed {_format_bytes(result.space_reclaimed)}"
        )

    return run


def image_prune_runner() -> JobRunner:
    """Build a job body that prunes every image no container uses."""
    return _prune_runner(docker_service.prune_images, "image")


def network_prune_runner() -> JobRunner:
    """Build a job body that removes every custom network no container uses."""

    def run(ctx: JobContext) -> None:
        deleted = docker_service.prune_networks()
        ctx.note(
            f"Pruned {len(deleted)} network(s)" + (f": {', '.join(deleted)}" if deleted else "")
        )

    return run


def volume_prune_runner() -> JobRunner:
    """Build a job body that removes every volume no container uses."""
    return _prune_runner(docker_service.prune_volumes, "volume")


def repo_git_runner(action: str, *, message: str = "", username: str = "") -> JobRunner:
    """Build a job body that commits (and pushes), pushes or pulls the repo folder."""

    def run(ctx: JobContext) -> None:
        output: list[str] = []
        if action in ("commit", "commit_push"):
            ctx.note("Committing")
            output.append(repo_git_service.commit(message, username))
            # Kept when the push fails: the commit is made either way.
            ctx.set_output("\n".join(output))
        if action in ("commit_push", "push"):
            ctx.note("Pushing")
            output.append(repo_git_service.push())
        if action == "pull":
            ctx.note("Pulling")
            output.append(repo_git_service.pull())
        ctx.set_output("\n".join(output))
        ctx.note("Done")

    return run
