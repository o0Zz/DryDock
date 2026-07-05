from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterator

import docker
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container as DockerContainer
from docker.models.volumes import Volume as DockerVolume

from app.schemas.container import Container, ContainerPort
from app.schemas.volume import PruneResult, Volume

logger = logging.getLogger(__name__)


class DockerUnavailable(Exception):
    """Raised when the Docker daemon cannot be reached."""


class VolumeInUse(Exception):
    """Raised when trying to remove a volume that is attached to a container."""


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
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
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
        return datetime.now(tz=timezone.utc)


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
    image_tags = (attrs.get("Config") or {}).get("Image") or (c.image.tags[0] if c.image and c.image.tags else "")
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
