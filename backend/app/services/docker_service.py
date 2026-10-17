from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache

import docker
from docker.errors import APIError, DockerException, NotFound
from docker.errors import ImageNotFound as DockerImageNotFound
from docker.models.containers import Container as DockerContainer
from docker.models.volumes import Volume as DockerVolume

from app.schemas.container import Container, ContainerPort
from app.schemas.volume import PruneResult, Volume

logger = logging.getLogger(__name__)


class DockerUnavailable(Exception):
    """Raised when the Docker daemon cannot be reached."""


class VolumeInUse(Exception):
    """Raised when trying to remove a volume that is attached to a container."""


class ImageNotFound(Exception):
    """Raised when an image reference is not present in the local image store."""


@lru_cache(maxsize=1)
def _client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


def _reset_client() -> None:
    _client.cache_clear()


def _parse_created(raw: str | int | float) -> datetime:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=UTC)
    # Docker's API returns e.g. "2024-01-02T03:04:05.6789Z" — trim beyond microseconds
    text = str(raw).replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        # keep at most 6 fractional digits, drop the rest before the timezone
        tz_start = max(tail.find("+"), tail.find("-"))
        if tz_start == -1:
            frac = tail[:6]
            tz = ""
        else:
            frac = tail[:tz_start][:6]
            tz = tail[tz_start:]
        text = f"{head}.{frac}{tz}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(tz=UTC)


def _parse_ports(attrs: dict) -> list[ContainerPort]:
    result: list[ContainerPort] = []
    ports = attrs.get("NetworkSettings", {}).get("Ports") or {}
    for key, bindings in ports.items():
        # key looks like "80/tcp"
        try:
            port_str, proto = key.split("/", 1)
            private = int(port_str)
        except (ValueError, AttributeError):
            continue
        if not bindings:
            result.append(ContainerPort(private_port=private, protocol=proto))
            continue
        for binding in bindings:
            public = binding.get("HostPort")
            result.append(
                ContainerPort(
                    private_port=private,
                    public_port=int(public) if public else None,
                    protocol=proto,
                    host_ip=binding.get("HostIp") or None,
                )
            )
    return result


def _to_schema(c: DockerContainer) -> Container:
    attrs = c.attrs or {}
    labels = attrs.get("Config", {}).get("Labels") or {}
    host_config = attrs.get("HostConfig") or {}
    image_tags = (attrs.get("Config") or {}).get("Image") or (
        c.image.tags[0] if c.image and c.image.tags else ""
    )
    return Container(
        id=c.id or "",
        name=c.name or "",
        image=image_tags,
        status=c.status,
        state=(attrs.get("State") or {}).get("Status") or c.status,
        created_at=_parse_created(attrs.get("Created", "")),
        ports=_parse_ports(attrs),
        compose_project=labels.get("com.docker.compose.project"),
        compose_service=labels.get("com.docker.compose.service"),
        compose_config_files=labels.get("com.docker.compose.project.config_files"),
        restart_policy=(host_config.get("RestartPolicy") or {}).get("Name") or None,
    )


def list_containers(*, all_states: bool = True) -> list[Container]:
    try:
        containers = _client().containers.list(all=all_states)
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return [_to_schema(c) for c in containers]


def get_container(container_id: str) -> Container:
    try:
        c = _client().containers.get(container_id)
    except NotFound as exc:
        raise DockerUnavailable(f"container {container_id} not found") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return _to_schema(c)


def perform_action(container_id: str, action: str) -> None:
    allowed = {"start", "stop", "restart"}
    if action not in allowed:
        raise ValueError(f"Unsupported action: {action}")
    try:
        c = _client().containers.get(container_id)
    except NotFound as exc:
        raise DockerUnavailable(f"container {container_id} not found") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc

    getattr(c, action)()


def stream_logs(container_id: str, *, tail: int = 200) -> Iterator[bytes]:
    try:
        c = _client().containers.get(container_id)
    except NotFound as exc:
        raise DockerUnavailable(f"container {container_id} not found") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc

    return c.logs(stream=True, follow=True, tail=tail, timestamps=False)


# --- Volumes -----------------------------------------------------------------


def _volume_usage() -> dict[str, list[str]]:
    """Map each named volume to the containers currently mounting it."""
    usage: dict[str, list[str]] = {}
    for c in _client().containers.list(all=True):
        for mount in (c.attrs or {}).get("Mounts") or []:
            if mount.get("Type") != "volume":
                continue
            name = mount.get("Name")
            if name:
                usage.setdefault(name, []).append(c.name or "")
    return usage


def _volume_to_schema(v: DockerVolume, usage: dict[str, list[str]]) -> Volume:
    attrs = v.attrs or {}
    labels = attrs.get("Labels") or {}
    created_raw = attrs.get("CreatedAt")
    return Volume(
        name=v.name or "",
        driver=attrs.get("Driver") or "local",
        mountpoint=attrs.get("Mountpoint") or "",
        scope=attrs.get("Scope"),
        created_at=_parse_created(created_raw) if created_raw else None,
        labels=labels,
        compose_project=labels.get("com.docker.compose.project"),
        used_by=usage.get(v.name or "", []),
    )


def list_volumes() -> list[Volume]:
    try:
        volumes = _client().volumes.list()
        usage = _volume_usage()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return sorted(
        (_volume_to_schema(v, usage) for v in volumes), key=lambda v: v.name.lower()
    )


def get_volume(name: str) -> Volume:
    try:
        v = _client().volumes.get(name)
        usage = _volume_usage()
    except NotFound as exc:
        raise DockerUnavailable(f"volume {name} not found") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return _volume_to_schema(v, usage)


def create_volume(name: str, driver: str = "local", labels: dict[str, str] | None = None) -> Volume:
    try:
        v = _client().volumes.create(name=name, driver=driver, labels=labels or {})
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return _volume_to_schema(v, _volume_usage())


def remove_volume(name: str, *, force: bool = False) -> None:
    try:
        v = _client().volumes.get(name)
    except NotFound as exc:
        raise DockerUnavailable(f"volume {name} not found") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    try:
        v.remove(force=force)
    except APIError as exc:
        # Docker returns 409 Conflict when the volume is still attached.
        if exc.response is not None and exc.response.status_code == 409:
            raise VolumeInUse(f"volume {name} is in use") from exc
        raise DockerUnavailable(str(exc)) from exc


def prune_volumes() -> PruneResult:
    try:
        result = _client().volumes.prune()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return PruneResult(
        deleted=result.get("VolumesDeleted") or [],
        space_reclaimed=result.get("SpaceReclaimed") or 0,
    )


# --- Images ------------------------------------------------------------------


def _repo_of(reference: str) -> str:
    """Strip the tag and/or digest off an image reference, keeping the repo."""
    reference = reference.split("@", 1)[0]
    slash = reference.rfind("/")
    colon = reference.rfind(":")
    # A colon before the last slash belongs to a registry port, not a tag.
    if colon > slash:
        reference = reference[:colon]
    return reference


def local_repo_digest(image: str) -> str | None:
    """Return the registry digest recorded for a locally-present image.

    ``None`` means the image exists but was never pulled from a registry (built
    locally or loaded from a tarball), so there is nothing to compare against.
    """
    try:
        img = _client().images.get(image)
    except DockerImageNotFound as exc:
        raise ImageNotFound(image) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc

    repo_digests = (img.attrs or {}).get("RepoDigests") or []
    if not repo_digests:
        return None

    wanted = _repo_of(image)
    for entry in repo_digests:
        repo, _, digest = entry.partition("@")
        if not digest:
            continue
        if repo == wanted or repo.endswith(f"/{wanted}") or wanted.endswith(f"/{repo}"):
            return digest
    # Single-repo image whose reference we could not normalise - use it anyway.
    if len(repo_digests) == 1:
        return repo_digests[0].partition("@")[2] or None
    return None


def registry_digest(image: str) -> str:
    """Look up an image's current manifest digest in its registry.

    This is a metadata request only - nothing is downloaded, which is what makes
    running it across every image practical on a Pi.
    """
    try:
        return _client().images.get_registry_data(image).id
    except NotFound as exc:
        raise DockerUnavailable(f"{image} not found in registry") from exc
    except APIError as exc:
        # Private registries answer 401/403 here when no credentials are configured.
        raise DockerUnavailable(f"registry lookup failed: {exc}") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


def running_images() -> list[str]:
    """Distinct images used by currently running containers."""
    return sorted({c.image for c in list_containers(all_states=False) if c.image})
