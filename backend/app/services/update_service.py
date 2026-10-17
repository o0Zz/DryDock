from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services import docker_service

logger = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    image: str
    local_digest: str | None = None
    remote_digest: str | None = None
    update_available: bool = False
    error: str | None = None


def check_image(image: str) -> UpdateResult:
    """Compare an image's local digest against the registry, without pulling.

    Uses a registry manifest lookup (``docker manifest inspect`` equivalent), so
    this is cheap enough to run over every image on a Pi.
    """
    if "@sha256:" in image:
        # Already pinned to a digest, so by definition it is what it says it is.
        return UpdateResult(image=image, local_digest=image.split("@", 1)[1])

    try:
        local = docker_service.local_repo_digest(image)
    except docker_service.ImageNotFound:
        return UpdateResult(image=image, error="image not present locally")
    except docker_service.DockerUnavailable as exc:
        return UpdateResult(image=image, error=f"docker unavailable: {exc}")

    if local is None:
        # Images built locally (or loaded from a tarball) have no RepoDigests,
        # so there is no registry reference to compare against.
        return UpdateResult(image=image, error="no registry digest (built locally?)")

    try:
        remote = docker_service.registry_digest(image)
    except docker_service.DockerUnavailable as exc:
        return UpdateResult(image=image, local_digest=local, error=str(exc))

    return UpdateResult(
        image=image,
        local_digest=local,
        remote_digest=remote,
        update_available=bool(remote) and remote != local,
    )
