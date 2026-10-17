from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services import docker_service, registry_auth_service, registry_service

logger = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    image: str
    local_digest: str | None = None
    remote_digest: str | None = None
    update_available: bool = False
    error: str | None = None
    # Newer version tags (e.g. 2026.1.0 for a pinned 2025.10.4), from the registry's tag list.
    newest_tag: str | None = None
    newest_same_major_tag: str | None = None
    tag_error: str | None = None


def check_image(image: str) -> UpdateResult:
    """Check an image for both kinds of update, without pulling.

    - newer version tags in the registry (pinned tags such as `2025.10.4`)
    - the same tag rebuilt with a new digest (floating tags such as `latest`)
    """
    if "@sha256:" in image:
        # Already pinned to a digest, so by definition it is what it says it is.
        return UpdateResult(image=image, local_digest=image.split("@", 1)[1])

    auth = registry_auth_service.credentials(registry_service.parse_reference(image)[0])
    result = _check_digest(image, auth)
    # Independent of the digest check: still useful when the image is not pulled yet.
    try:
        result.newest_tag, result.newest_same_major_tag = registry_service.newer_tags(image, auth)
    except registry_service.RegistryError as exc:
        logger.info("Tag check for %s failed: %s", image, exc)
        result.tag_error = str(exc)
    return result


def _check_digest(image: str, auth: registry_service.Credentials = None) -> UpdateResult:
    """Compare an image's local digest against the registry's for the same tag.

    Uses a registry manifest lookup (``docker manifest inspect`` equivalent), so
    this is cheap enough to run over every image on a Pi.
    """
    try:
        local_digest = docker_service.local_repo_digest(image)
    except docker_service.ImageNotFound:
        return UpdateResult(image=image, error="image not present locally")
    except docker_service.DockerUnavailable as exc:
        return UpdateResult(image=image, error=f"docker unavailable: {exc}")

    if local_digest is None:
        # Images built locally (or loaded from a tarball) have no RepoDigests,
        # so there is no registry reference to compare against.
        return UpdateResult(image=image, error="no registry digest (built locally?)")

    try:
        remote_digest = docker_service.registry_digest(
            image, {"username": auth[0], "password": auth[1]} if auth else None
        )
    except docker_service.DockerUnavailable as exc:
        return UpdateResult(image=image, local_digest=local_digest, error=str(exc))

    return UpdateResult(
        image=image,
        local_digest=local_digest,
        remote_digest=remote_digest,
        update_available=bool(remote_digest) and remote_digest != local_digest,
    )
