"""Read-only access to the files in a named volume.

Volume data lives under the Docker root on the host, which DryDock cannot see.
So each request uses a throwaway helper container with the volume mounted
read-only and no network: `find` + `stat` lists a folder, and a copy out of the
container (`docker cp`) streams a file. The helper uses DryDock's own image, so
nothing is pulled. Outside a container (dev) it falls back to
`settings.helper_image`, pulled on first use.
"""

from __future__ import annotations

import posixpath

from app.core.config import settings
from app.schemas.volume import VolumeListing
from app.services import docker_service, host_path_service

# Plenty for a browser; a bigger folder is cut and flagged as truncated.
MAX_ENTRIES = 2000

_fallback_ready = False


def helper_image() -> str:
    """DryDock's own image when it runs in a container, else the configured fallback.

    Looked up on every call, not cached: rebuilding DryDock's tag can make the
    image it runs on unresolvable by ID (containerd image store), and
    `container_image` then answers with the tag.
    """
    global _fallback_ready
    container_id = host_path_service.own_container_id()
    image = docker_service.container_image(container_id) if container_id else None
    if image is not None:
        return image
    if not _fallback_ready:
        docker_service.ensure_image(settings.helper_image)
        _fallback_ready = True
    return settings.helper_image


def normalize(path: str) -> str:
    """Absolute, clean path inside the volume. `..` cannot climb above its root."""
    return posixpath.normpath("/" + path.strip("/"))


def list_dir(volume: str, path: str) -> VolumeListing:
    path = normalize(path)
    entries = docker_service.list_volume_dir(volume, path, image=helper_image())
    entries.sort(key=lambda entry: (entry.type != "dir", entry.name.lower()))
    return VolumeListing(
        path=path, entries=entries[:MAX_ENTRIES], truncated=len(entries) > MAX_ENTRIES
    )


def open_file(volume: str, path: str) -> docker_service.VolumeFile:
    return docker_service.open_volume_file(volume, normalize(path), image=helper_image())
