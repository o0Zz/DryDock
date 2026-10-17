"""Make the repo reachable inside DryDock at the path it has on the host.

Compose turns relative paths in a Compose file (`./default.conf`, `./data`) into
absolute ones based on the file's folder, and hands those to the Docker daemon.
The daemon resolves them on the *host*. When DryDock sees the repo at `/repo`
but the host has it at `/home/pi/docker`, a bind mount then points at a host
path that does not exist, and Docker creates an empty directory there instead.

The fix: create `/home/pi/docker -> /repo` inside DryDock's container and run
Compose through that path. Compose still reads the files (via the symlink),
and the daemon receives paths that exist on the host.
"""

from __future__ import annotations

import logging
import os
import re
import socket
from pathlib import Path

from app.core.config import settings
from app.services import docker_service

logger = logging.getLogger(__name__)

# Docker bind-mounts /etc/hostname etc. from /var/lib/docker/containers/<id>/,
# which is the most reliable way to learn our own container id.
_CONTAINER_ID = re.compile(r"/containers/([0-9a-f]{64})/")

MOUNTINFO = Path("/proc/self/mountinfo")

_alias: Path | None = None


def _own_container_id() -> str | None:
    try:
        text = MOUNTINFO.read_text(encoding="utf-8")
    except OSError:
        return None  # not on Linux, so not in a container
    match = _CONTAINER_ID.search(text)
    # The default hostname is the short container id; a custom one won't resolve.
    return match.group(1) if match else socket.gethostname()


def detect_host_path() -> Path | None:
    """Host path of the repo mount, or None when it cannot be told."""
    if settings.repo_host_path:
        return settings.repo_host_path
    container_id = _own_container_id()
    if not container_id:
        return None
    source = docker_service.mount_source(container_id, settings.repo_path.as_posix())
    return Path(source) if source else None


def setup() -> Path | None:
    """Create the host-path alias for the repo, if one is needed. Safe to call again."""
    global _alias
    _alias = None
    repo = settings.repo_path
    try:
        host = detect_host_path()
    except docker_service.DockerUnavailable as exc:
        logger.warning("Could not detect the repo's host path: %s", exc)
        return None
    if host is None or host == repo:
        return None
    if host.is_relative_to(repo):
        logger.warning("Repo host path %s is inside %s; not aliasing it", host, repo)
        return None

    if host.exists() or host.is_symlink():
        # Our link from a previous start, or the repo also mounted at its host
        # path: either way it already is the repo. Anything else is left alone.
        if not (host.exists() and os.path.samefile(host, repo)):
            logger.warning("%s exists and is not the repo; relative mounts may break", host)
            return None
    else:
        host.parent.mkdir(parents=True, exist_ok=True)
        host.symlink_to(repo, target_is_directory=True)

    _alias = host
    logger.info("Running Compose through %s (host path of %s)", host, repo)
    return host


def to_host(path: Path) -> Path:
    """Map a path under the repo to its host-path alias; anything else is unchanged."""
    if _alias is None:
        return path
    try:
        return _alias / path.relative_to(settings.repo_path)
    except ValueError:
        return path
