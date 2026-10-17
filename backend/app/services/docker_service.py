from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound
from docker.errors import ImageNotFound as DockerImageNotFound
from docker.models.containers import Container as DockerContainer
from docker.models.images import Image as DockerImage
from docker.models.volumes import Volume as DockerVolume

from app.schemas.common import PruneResult
from app.schemas.container import (
    Container,
    ContainerDetail,
    ContainerPort,
    ContainerStats,
    EnvVar,
    MountInfo,
    NetworkInfo,
)
from app.schemas.dashboard import HostInfo
from app.schemas.image import ContainerRef, Image
from app.schemas.volume import Volume, VolumeUser

logger = logging.getLogger(__name__)


class DockerUnavailable(Exception):
    """Raised when the Docker daemon cannot be reached."""


class DockerNotFound(DockerUnavailable):
    """Raised when a container or volume does not exist.

    A subclass so callers that only care whether Docker answered can keep
    catching DockerUnavailable; the API maps this one to 404, the base to 503.
    """


class VolumeInUse(Exception):
    """Raised when trying to remove a volume that is attached to a container."""


class ContainerRunning(Exception):
    """Raised when trying to remove a container that is still running."""


class ContainerConflict(Exception):
    """Raised when Docker refuses an action in the container's current state."""


class ImageNotFound(Exception):
    """Raised when an image reference is not present in the local image store."""


class ImageInUse(Exception):
    """Raised when trying to remove an image that a container still uses."""


@lru_cache(maxsize=1)
def _client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


def _reset_client() -> None:
    _client.cache_clear()


def _get_container(container_id: str) -> DockerContainer:
    try:
        return _client().containers.get(container_id)
    except NotFound as exc:
        raise DockerNotFound(f"container {container_id} not found") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


def _get_volume(name: str) -> DockerVolume:
    try:
        return _client().volumes.get(name)
    except NotFound as exc:
        raise DockerNotFound(f"volume {name} not found") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


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
            fraction = tail[:6]
            tz_suffix = ""
        else:
            fraction = tail[:tz_start][:6]
            tz_suffix = tail[tz_start:]
        text = f"{head}.{fraction}{tz_suffix}"
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
            port_str, protocol = key.split("/", 1)
            private = int(port_str)
        except (ValueError, AttributeError):
            continue
        if not bindings:
            result.append(ContainerPort(private_port=private, protocol=protocol))
            continue
        for binding in bindings:
            public = binding.get("HostPort")
            result.append(
                ContainerPort(
                    private_port=private,
                    public_port=int(public) if public else None,
                    protocol=protocol,
                    host_ip=binding.get("HostIp") or None,
                )
            )
    return result


def _image_version(image: str, labels: dict[str, str]) -> str | None:
    """Version the image declares in its OCI label, if it can be trusted.

    Container labels already include the image's labels, so no extra inspect
    is needed. Labels are inherited from the base image, though: an image built
    FROM ubuntu reports ubuntu's version unless it sets its own. Ubuntu marks
    its labels with a plain name in `ref.name`, so a name that is not this
    image's repo means the version belongs to the base image.
    """
    version = (labels.get("org.opencontainers.image.version") or "").strip()
    if not version:
        return None
    ref_name = labels.get("org.opencontainers.image.ref.name") or ""
    repo = _repo_of(image).rsplit("/", 1)[-1]
    if ref_name and not any(char.isdigit() for char in ref_name) and ref_name != repo:
        return None
    return version


def _to_schema(container: DockerContainer) -> Container:
    attrs = container.attrs or {}
    labels = attrs.get("Config", {}).get("Labels") or {}
    host_config = attrs.get("HostConfig") or {}
    image_tags = (attrs.get("Config") or {}).get("Image") or (
        container.image.tags[0] if container.image and container.image.tags else ""
    )
    return Container(
        id=container.id or "",
        name=container.name or "",
        image=image_tags,
        image_version=_image_version(image_tags, labels),
        status=container.status,
        state=(attrs.get("State") or {}).get("Status") or container.status,
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
    return [_to_schema(container) for container in containers]


def host_info() -> HostInfo:
    try:
        info = _client().info()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return HostInfo(
        os=info.get("OperatingSystem"),
        kernel=info.get("KernelVersion"),
        architecture=info.get("Architecture"),
        docker_version=info.get("ServerVersion"),
        cpus=info.get("NCPU"),
        memory_total=info.get("MemTotal"),
    )


def get_container(container_id: str) -> Container:
    return _to_schema(_get_container(container_id))


MASKED_VALUE = "••••••"


def _optional_time(raw: str | None) -> datetime | None:
    # Docker reports "never" as the zero time, 0001-01-01T00:00:00Z.
    if not raw or raw.startswith("0001-01-01"):
        return None
    return _parse_created(raw)


def _as_list(value: str | list[str] | None) -> list[str] | None:
    if value is None:
        return None
    return [value] if isinstance(value, str) else list(value)


def get_container_detail(container_id: str, *, privileged: bool) -> ContainerDetail:
    """Inspect one container. `privileged` (admin) reveals env values and
    includes the raw inspect payload; otherwise env values are masked."""
    container = _get_container(container_id)
    attrs = container.attrs or {}
    config = attrs.get("Config") or {}
    state = attrs.get("State") or {}

    env: list[EnvVar] = []
    for entry in config.get("Env") or []:
        key, _, value = entry.partition("=")
        env.append(EnvVar(key=key, value=value if privileged else MASKED_VALUE))

    mounts = [
        MountInfo(
            type=mount.get("Type") or "bind",
            source=mount.get("Source") or mount.get("Name") or None,
            destination=mount.get("Destination") or "",
            mode=mount.get("Mode") or None,
            rw=bool(mount.get("RW", True)),
        )
        for mount in attrs.get("Mounts") or []
    ]

    networks = [
        NetworkInfo(
            name=name,
            ip_address=network.get("IPAddress") or None,
            gateway=network.get("Gateway") or None,
            mac_address=network.get("MacAddress") or None,
        )
        for name, network in ((attrs.get("NetworkSettings") or {}).get("Networks") or {}).items()
    ]

    return ContainerDetail(
        **_to_schema(container).model_dump(),
        image_id=attrs.get("Image"),
        command=_as_list(config.get("Cmd")),
        entrypoint=_as_list(config.get("Entrypoint")),
        working_dir=config.get("WorkingDir") or None,
        user=config.get("User") or None,
        hostname=config.get("Hostname") or None,
        started_at=_optional_time(state.get("StartedAt")),
        finished_at=_optional_time(state.get("FinishedAt")),
        exit_code=state.get("ExitCode"),
        restart_count=attrs.get("RestartCount") or 0,
        health=(state.get("Health") or {}).get("Status"),
        env=env,
        env_revealed=privileged,
        mounts=mounts,
        networks=networks,
        labels=config.get("Labels") or {},
        raw=attrs if privileged else None,
    )


def perform_action(container_id: str, action: str) -> None:
    allowed = {"start", "stop", "restart", "kill", "pause", "unpause"}
    if action not in allowed:
        raise ValueError(f"Unsupported action: {action}")
    container = _get_container(container_id)
    try:
        getattr(container, action)()
    except APIError as exc:
        # 409 Conflict: e.g. kill or pause on a container that is not running.
        if exc.response is not None and exc.response.status_code == 409:
            raise ContainerConflict(f"cannot {action} {container.name}: {exc.explanation}") from exc
        raise DockerUnavailable(str(exc)) from exc


def remove_container(container_id: str) -> None:
    """Remove a stopped container. Its named volumes are left alone."""
    container = _get_container(container_id)
    try:
        container.remove()
    except APIError as exc:
        # Docker returns 409 Conflict when the container is still running.
        if exc.response is not None and exc.response.status_code == 409:
            raise ContainerRunning(f"container {container.name} is running; stop it first") from exc
        raise DockerUnavailable(str(exc)) from exc


def stream_logs(container_id: str, *, tail: int = 200) -> Iterator[bytes]:
    return _get_container(container_id).logs(stream=True, follow=True, tail=tail, timestamps=False)


# --- Stats -------------------------------------------------------------------

# Each stats call blocks ~1s while the daemon takes two CPU samples, so fetch
# them concurrently; capped to keep a Pi responsive.
STATS_WORKERS = 8


def _stats_to_schema(container: DockerContainer, raw: dict) -> ContainerStats:
    cpu = raw.get("cpu_stats") or {}
    precpu = raw.get("precpu_stats") or {}
    usage = cpu.get("cpu_usage") or {}
    cpu_delta = usage.get("total_usage", 0) - (precpu.get("cpu_usage") or {}).get("total_usage", 0)
    system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
    online_cpus = cpu.get("online_cpus") or len(usage.get("percpu_usage") or []) or 1
    cpu_percent = 0.0
    if cpu_delta > 0 and system_delta > 0:
        cpu_percent = cpu_delta / system_delta * online_cpus * 100

    mem = raw.get("memory_stats") or {}
    mem_detail = mem.get("stats") or {}
    # Same as `docker stats`: page cache is reclaimable, so it is not "used".
    cache = mem_detail.get("inactive_file", mem_detail.get("total_inactive_file", 0))
    mem_usage = max(mem.get("usage", 0) - cache, 0)
    mem_limit = mem.get("limit", 0)

    networks = (raw.get("networks") or {}).values()
    blkio = (raw.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []

    def _block_bytes(operation: str) -> int:
        return sum(
            entry.get("value", 0)
            for entry in blkio
            if str(entry.get("op", "")).lower() == operation
        )

    return ContainerStats(
        id=container.id or "",
        name=container.name or "",
        cpu_percent=round(cpu_percent, 2),
        memory_usage=mem_usage,
        memory_limit=mem_limit,
        memory_percent=round(mem_usage / mem_limit * 100, 2) if mem_limit else 0.0,
        network_rx=sum(network.get("rx_bytes", 0) for network in networks),
        network_tx=sum(network.get("tx_bytes", 0) for network in networks),
        block_read=_block_bytes("read"),
        block_write=_block_bytes("write"),
        pids=(raw.get("pids_stats") or {}).get("current"),
    )


def _one_stats(container: DockerContainer) -> ContainerStats | None:
    try:
        return _stats_to_schema(container, container.stats(stream=False))
    except DockerException as exc:
        # A container stopping mid-poll is normal; skip it rather than fail the batch.
        logger.debug("Stats unavailable for %s: %s", container.name, exc)
        return None


def running_stats() -> list[ContainerStats]:
    """CPU / memory / IO snapshot of every running container."""
    try:
        containers = _client().containers.list()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    if not containers:
        return []
    with ThreadPoolExecutor(max_workers=min(STATS_WORKERS, len(containers))) as pool:
        results = pool.map(_one_stats, containers)
    return [stats for stats in results if stats is not None]


# --- Exec console ------------------------------------------------------------

# Prefer bash when the image has it; most minimal images only ship sh.
CONSOLE_CMD = ["/bin/sh", "-c", "command -v bash >/dev/null 2>&1 && exec bash || exec sh"]


class ExecSession:
    """An interactive TTY exec in a container, over Docker's hijacked socket."""

    def __init__(self, exec_id: str, sock: Any) -> None:
        self.exec_id = exec_id
        # Unix sockets come back wrapped in SocketIO; the Windows npipe socket
        # is used as-is. Both expose recv/sendall.
        self._sock = getattr(sock, "_sock", sock)

    def read(self, size: int = 4096) -> bytes:
        try:
            return self._sock.recv(size)
        except OSError:
            return b""

    def write(self, data: bytes) -> None:
        self._sock.sendall(data)

    def resize(self, cols: int, rows: int) -> None:
        with contextlib.suppress(DockerException):
            _client().api.exec_resize(self.exec_id, height=rows, width=cols)

    def close(self) -> None:
        # shutdown() unblocks a recv() waiting in another thread; close() alone may not.
        with contextlib.suppress(Exception):
            self._sock.shutdown(2)
        with contextlib.suppress(Exception):
            self._sock.close()


def open_exec(container_id: str, *, cols: int = 80, rows: int = 24) -> ExecSession:
    api = _client().api
    try:
        exec_id = api.exec_create(
            container_id,
            CONSOLE_CMD,
            stdin=True,
            tty=True,
            environment={"TERM": "xterm-256color"},
        )["Id"]
        sock = api.exec_start(exec_id, tty=True, socket=True)
    except NotFound as exc:
        raise DockerNotFound(f"container {container_id} not found") from exc
    except APIError as exc:
        # 409 Conflict: container is not running.
        raise DockerUnavailable(exc.explanation or str(exc)) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    session = ExecSession(exec_id, sock)
    session.resize(cols, rows)
    return session


def mount_source(container_id: str, destination: str) -> str | None:
    """Host path (or volume path) mounted at `destination` in a container."""
    try:
        container = _get_container(container_id)
    except DockerNotFound:
        return None
    for mount in (container.attrs or {}).get("Mounts") or []:
        if mount.get("Destination") == destination:
            return mount.get("Source") or None
    return None


# --- Volumes -----------------------------------------------------------------


def _volume_usage() -> dict[str, list[VolumeUser]]:
    """Map each named volume to the containers (any state) mounting it."""
    usage: dict[str, list[VolumeUser]] = {}
    for container in _client().containers.list(all=True):
        for mount in (container.attrs or {}).get("Mounts") or []:
            if mount.get("Type") != "volume":
                continue
            name = mount.get("Name")
            if name:
                usage.setdefault(name, []).append(
                    VolumeUser(
                        id=container.id or "",
                        name=container.name or "",
                        running=container.status == "running",
                        destination=mount.get("Destination") or "",
                        rw=bool(mount.get("RW", True)),
                    )
                )
    return usage


def _volume_to_schema(volume: DockerVolume, usage: dict[str, list[VolumeUser]]) -> Volume:
    attrs = volume.attrs or {}
    labels = attrs.get("Labels") or {}
    created_raw = attrs.get("CreatedAt")
    return Volume(
        name=volume.name or "",
        driver=attrs.get("Driver") or "local",
        mountpoint=attrs.get("Mountpoint") or "",
        scope=attrs.get("Scope"),
        created_at=_parse_created(created_raw) if created_raw else None,
        labels=labels,
        compose_project=labels.get("com.docker.compose.project"),
        used_by=usage.get(volume.name or "", []),
    )


def list_volumes() -> list[Volume]:
    try:
        volumes = _client().volumes.list()
        usage = _volume_usage()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return sorted(
        (_volume_to_schema(volume, usage) for volume in volumes),
        key=lambda volume: volume.name.lower(),
    )


def get_volume(name: str) -> Volume:
    volume = _get_volume(name)
    try:
        usage = _volume_usage()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return _volume_to_schema(volume, usage)


def create_volume(name: str, driver: str = "local", labels: dict[str, str] | None = None) -> Volume:
    try:
        volume = _client().volumes.create(name=name, driver=driver, labels=labels or {})
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return _volume_to_schema(volume, _volume_usage())


def remove_volume(name: str, *, force: bool = False) -> None:
    volume = _get_volume(name)
    try:
        volume.remove(force=force)
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
        local_image = _client().images.get(image)
    except DockerImageNotFound as exc:
        raise ImageNotFound(image) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc

    repo_digests = (local_image.attrs or {}).get("RepoDigests") or []
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


def _image_usage() -> dict[str, list[ContainerRef]]:
    """Map each image ID to the containers (any state) created from it."""
    usage: dict[str, list[ContainerRef]] = {}
    for container in _client().containers.list(all=True):
        image_id = (container.attrs or {}).get("Image")
        if image_id:
            usage.setdefault(image_id, []).append(
                ContainerRef(name=container.name or "", running=container.status == "running")
            )
    return usage


def _image_to_schema(image: DockerImage, usage: dict[str, list[ContainerRef]]) -> Image:
    attrs = image.attrs or {}
    created_raw = attrs.get("Created")
    return Image(
        id=image.id or "",
        tags=image.tags,
        size=attrs.get("Size") or 0,
        created_at=_parse_created(created_raw) if created_raw else None,
        used_by=usage.get(image.id or "", []),
    )


def list_images() -> list[Image]:
    try:
        images = _client().images.list()
        usage = _image_usage()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return sorted(
        (_image_to_schema(image, usage) for image in images),
        key=lambda image: (image.tags[0] if image.tags else "~").lower(),
    )


def remove_image(image: str, *, force: bool = False) -> None:
    """Remove one image reference.

    Removing a tag that shares its image with other tags only untags it. Even
    with ``force``, an image used by a running container is refused.
    """
    try:
        local_image = _client().images.get(image)
        used_by = _image_usage().get(local_image.id or "", [])
    except DockerImageNotFound as exc:
        raise ImageNotFound(image) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc

    running = [container.name for container in used_by if container.running]
    if running:
        raise ImageInUse(f"image {image} is used by running container(s): {', '.join(running)}")
    try:
        _client().images.remove(image, force=force)
    except DockerImageNotFound as exc:
        raise ImageNotFound(image) from exc
    except APIError as exc:
        # Docker returns 409 Conflict when a stopped container still references it.
        if exc.response is not None and exc.response.status_code == 409:
            raise ImageInUse(exc.explanation or f"image {image} is in use") from exc
        raise DockerUnavailable(str(exc)) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


def prune_images(*, all_unused: bool = False) -> PruneResult:
    """Prune dangling images, or with ``all_unused`` every image without a container."""
    try:
        result = _client().images.prune(filters={"dangling": not all_unused})
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    entries = result.get("ImagesDeleted") or []
    return PruneResult(
        deleted=[entry["Deleted"] for entry in entries if entry.get("Deleted")],
        space_reclaimed=result.get("SpaceReclaimed") or 0,
    )


def running_images() -> list[str]:
    """Distinct images used by currently running containers."""
    return sorted(
        {container.image for container in list_containers(all_states=False) if container.image}
    )
