from __future__ import annotations

import contextlib
import io
import logging
import posixpath
import stat
import tarfile
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import docker
from docker.errors import APIError, ContainerError, DockerException, NotFound
from docker.errors import ImageNotFound as DockerImageNotFound
from docker.models.containers import Container as DockerContainer
from docker.models.images import Image as DockerImage
from docker.models.networks import Network as DockerNetwork
from docker.models.volumes import Volume as DockerVolume
from docker.types import LogConfig, Mount

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
from app.schemas.network import Network, NetworkUser
from app.schemas.volume import Volume, VolumeEntry, VolumeUser
from app.services import registry_service

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


class NetworkInUse(Exception):
    """Raised when removing a network that a container uses, or one of Docker's own."""


class NotAFile(Exception):
    """Raised when a volume path to download is a folder, link or device."""


class RegistryLoginFailed(Exception):
    """Raised when a registry rejects credentials (or cannot be reached to check them)."""


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
    # Docker returns e.g. "2024-01-02T03:04:05.123456789Z". Since Python 3.11,
    # fromisoformat takes the `Z` and cuts the nanoseconds to microseconds.
    try:
        return datetime.fromisoformat(str(raw))
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
    repo = registry_service.split_tag(image)[0].rsplit("/", 1)[-1]
    if ref_name and not any(char.isdigit() for char in ref_name) and ref_name != repo:
        return None
    return version


# A service opts in to the scheduled auto-update with this label. Read from the
# container, so it takes effect once the stack is deployed with it.
AUTO_UPDATE_LABEL = "drydock.update"
AUTO_UPDATE_VALUE = "auto"


def _to_schema(container: DockerContainer) -> Container:
    attrs = container.attrs or {}
    labels = attrs.get("Config", {}).get("Labels") or {}
    host_config = attrs.get("HostConfig") or {}
    state = attrs.get("State") or {}
    image_tags = (attrs.get("Config") or {}).get("Image") or (
        container.image.tags[0] if container.image and container.image.tags else ""
    )
    return Container(
        id=container.id or "",
        name=container.name or "",
        image=image_tags,
        image_version=_image_version(image_tags, labels),
        status=container.status,
        state=state.get("Status") or container.status,
        created_at=_parse_created(attrs.get("Created", "")),
        ports=_parse_ports(attrs),
        compose_project=labels.get("com.docker.compose.project"),
        compose_service=labels.get("com.docker.compose.service"),
        compose_config_files=labels.get("com.docker.compose.project.config_files"),
        restart_policy=(host_config.get("RestartPolicy") or {}).get("Name") or None,
        restart_count=attrs.get("RestartCount") or 0,
        health=(state.get("Health") or {}).get("Status"),
        started_at=_optional_time(state.get("StartedAt")),
        finished_at=_optional_time(state.get("FinishedAt")),
        auto_update=labels.get(AUTO_UPDATE_LABEL) == AUTO_UPDATE_VALUE,
    )


def list_containers(*, all_states: bool = True, label: str | None = None) -> list[Container]:
    """Containers, optionally only those with `label` (`key` or `key=value`)."""
    try:
        containers = _client().containers.list(
            all=all_states, filters={"label": label} if label else None
        )
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
        exit_code=state.get("ExitCode"),
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
        if exc.status_code == 409:
            raise ContainerConflict(f"cannot {action} {container.name}: {exc.explanation}") from exc
        raise DockerUnavailable(str(exc)) from exc


def rename_container(container_id: str, name: str) -> Container:
    container = _get_container(container_id)
    try:
        container.rename(name)
        container.reload()
    except APIError as exc:
        # 409 Conflict: another container already has the name.
        if exc.status_code == 409:
            raise ContainerConflict(f"cannot rename {container.name}: {exc.explanation}") from exc
        raise DockerUnavailable(str(exc)) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return _to_schema(container)


def remove_container(container_id: str) -> None:
    """Remove a stopped container. Its named volumes are left alone."""
    container = _get_container(container_id)
    try:
        container.remove()
    except APIError as exc:
        # Docker returns 409 Conflict when the container is still running.
        if exc.status_code == 409:
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
    except (DockerException, ValueError) as exc:
        # A container stopping mid-poll is normal; skip it rather than fail the batch.
        # Docker can then answer with an empty body, which fails to parse as JSON.
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


def container_image(container_id: str) -> str | None:
    """A local image to run a copy of a container with, or None.

    That is the image the container was created from, else what its tag points
    to now: once the tag is rebuilt, the old image can be gone while the
    container still runs. Never a reference that would need a pull.
    """
    try:
        attrs = _get_container(container_id).attrs or {}
    except DockerNotFound:
        return None
    for reference in (attrs.get("Image"), (attrs.get("Config") or {}).get("Image")):
        if not reference:
            continue
        try:
            _client().images.get(reference)
        except NotFound:
            continue
        except DockerException as exc:
            raise DockerUnavailable(str(exc)) from exc
        return reference
    return None


def mount_source(container_id: str, destination: str) -> str | None:
    """Host path (or volume path) of `destination` in a container.

    `destination` may sit inside a mount: with the git repo root mounted at
    `/repo`, the Compose folder `/repo/docker` is `<source>/docker`.
    """
    try:
        container = _get_container(container_id)
    except DockerNotFound:
        return None
    best: tuple[str, str] | None = None
    for mount in (container.attrs or {}).get("Mounts") or []:
        target, source = mount.get("Destination") or "", mount.get("Source")
        if not source or not (destination == target or destination.startswith(target + "/")):
            continue
        # Nested mounts: the deepest one holds the path.
        if best is None or len(target) > len(best[0]):
            best = (target, source)
    if best is None:
        return None
    target, source = best
    return source + destination[len(target) :]


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
        if exc.status_code == 409:
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


# --- Networks ----------------------------------------------------------------

PREDEFINED_NETWORKS = {"bridge", "host", "none"}


def _network_usage() -> dict[str, list[NetworkUser]]:
    """Map each network name to the containers attached to it, in any state.

    A network's own inspect only lists running containers, and Docker's prune
    goes by that, so it removes networks that stopped stacks still need. The
    containers' settings name their networks in every state; the network ID is
    only filled in once a container has started, so the name is the key.
    """
    usage: dict[str, list[NetworkUser]] = {}
    for container in _client().containers.list(all=True):
        network_settings = (container.attrs or {}).get("NetworkSettings") or {}
        for name, network in (network_settings.get("Networks") or {}).items():
            usage.setdefault(name, []).append(
                NetworkUser(
                    id=container.id or "",
                    name=container.name or "",
                    running=container.status == "running",
                    ip_address=(network or {}).get("IPAddress") or None,
                )
            )
    return usage


def _network_to_schema(network: DockerNetwork, usage: dict[str, list[NetworkUser]]) -> Network:
    attrs = network.attrs or {}
    labels = attrs.get("Labels") or {}
    ipam = (attrs.get("IPAM") or {}).get("Config") or []
    created_raw = attrs.get("Created")
    name = network.name or ""
    return Network(
        id=network.id or "",
        name=name,
        driver=attrs.get("Driver") or "",
        scope=attrs.get("Scope"),
        subnets=[entry["Subnet"] for entry in ipam if entry.get("Subnet")],
        gateways=[entry["Gateway"] for entry in ipam if entry.get("Gateway")],
        internal=bool(attrs.get("Internal")),
        created_at=_parse_created(created_raw) if created_raw else None,
        labels=labels,
        compose_project=labels.get("com.docker.compose.project"),
        predefined=name in PREDEFINED_NETWORKS,
        used_by=usage.get(name, []),
    )


def list_networks() -> list[Network]:
    try:
        # greedy: one inspect per network, for IPAM and creation time.
        networks = _client().networks.list(greedy=True)
        usage = _network_usage()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return sorted(
        (_network_to_schema(network, usage) for network in networks),
        key=lambda network: network.name.lower(),
    )


def network_exists(name: str) -> bool:
    try:
        # `names` matches substrings too, so compare exactly.
        return any(network.name == name for network in _client().networks.list(names=[name]))
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


def remove_network(network_id: str) -> None:
    try:
        network = _client().networks.get(network_id)
    except NotFound as exc:
        raise DockerNotFound(f"network {network_id} not found") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    if network.name in PREDEFINED_NETWORKS:
        raise NetworkInUse(f"{network.name} is one of Docker's own networks")
    try:
        users = _network_usage().get(network.name or "", [])
        if users:
            names = ", ".join(sorted(user.name for user in users))
            raise NetworkInUse(f"network {network.name} is used by {names}")
        network.remove()
    except APIError as exc:
        # 403 or 409 when a container is attached after all.
        if exc.status_code in (403, 409):
            raise NetworkInUse(f"cannot remove {network.name}: {exc.explanation}") from exc
        raise DockerUnavailable(str(exc)) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


def prune_networks() -> list[str]:
    """Remove every custom network no container uses, running or not. Returns their names.

    Not `docker network prune`: that only counts running containers.
    """
    deleted: list[str] = []
    for network in list_networks():
        if network.predefined or network.used_by:
            continue
        try:
            remove_network(network.id)
        except (NetworkInUse, DockerNotFound) as exc:
            # Attached or removed meanwhile; prune what is still free.
            logger.info("Skipped network %s: %s", network.name, exc)
            continue
        deleted.append(network.name)
    return deleted


# --- Volume files ------------------------------------------------------------

# Where helper containers mount the volume they read.
VOLUME_ROOT = "/volume"
_CHUNK_SIZE = 64 * 1024
# find arguments after the folder: one `stat` line per direct child.
_LIST_ARGS = ["-mindepth", "1", "-maxdepth", "1", "-exec", "stat", "-c", "%f %s %Y %n", "{}", "+"]
# Type bits of Go's os.FileMode (dir, symlink, device, pipe, socket, char device,
# irregular), as sent in Docker's archive stat header. A regular file has none.
_GO_MODE_TYPE = (1 << 31) | (1 << 27) | (1 << 26) | (1 << 25) | (1 << 24) | (1 << 21) | (1 << 19)


@dataclass
class VolumeFile:
    name: str
    size: int
    chunks: Iterator[bytes]


class _ChunkReader(io.RawIOBase):
    """File-like view over an iterator of byte chunks, for tarfile's stream mode."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._pending = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        while not self._pending:
            try:
                self._pending = next(self._chunks)
            except StopIteration:
                return 0
        size = min(len(buffer), len(self._pending))
        buffer[:size] = self._pending[:size]
        self._pending = self._pending[size:]
        return size


def _helper_options(volume: str, image: str) -> dict[str, Any]:
    return {
        "image": image,
        "volumes": {volume: {"bind": VOLUME_ROOT, "mode": "ro"}},
        "network_mode": "none",
        "labels": {"drydock.helper": "volume-files"},
    }


def _remove_quietly(container: DockerContainer) -> None:
    with contextlib.suppress(DockerException):
        container.remove(force=True)


def ensure_image(reference: str) -> None:
    """Pull `reference` unless it is already present."""
    try:
        try:
            _client().images.get(reference)
        except NotFound:
            _client().images.pull(reference)
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


def _entry_type(mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISLNK(mode):
        return "link"
    return "other"


def _parse_entries(output: bytes) -> list[VolumeEntry]:
    """Parse `stat -c '%f %s %Y %n'` lines. The name comes last, so spaces in it are fine."""
    entries: list[VolumeEntry] = []
    for line in output.decode("utf-8", errors="replace").splitlines():
        parts = line.split(" ", 3)
        if len(parts) != 4:
            continue  # the tail of a file name that holds a newline
        raw_mode, size, mtime, path = parts
        try:
            entries.append(
                VolumeEntry(
                    name=posixpath.basename(path),
                    type=_entry_type(int(raw_mode, 16)),
                    size=int(size),
                    modified_at=datetime.fromtimestamp(int(mtime), tz=UTC),
                )
            )
        except ValueError:
            continue
    return entries


def list_volume_dir(name: str, path: str, *, image: str) -> list[VolumeEntry]:
    """Entries of the folder `path` (absolute, normalised) in a volume, unsorted."""
    _get_volume(name)
    # The trailing slash makes find fail on a file, not only on a missing path.
    target = (VOLUME_ROOT + path).rstrip("/") + "/"
    try:
        output = _client().containers.run(
            entrypoint=["find"],
            command=[target, *_LIST_ARGS],
            remove=True,
            # run() only returns the output for log drivers it can read back.
            log_config=LogConfig(type=LogConfig.types.JSON),
            **_helper_options(name, image),
        )
    except ContainerError as exc:
        raise DockerNotFound(f"no folder {path} in volume {name}") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return _parse_entries(output or b"")


def open_volume_file(name: str, path: str, *, image: str) -> VolumeFile:
    """Open a regular file in a volume for streaming.

    The helper container is only created, never started: Docker mounts its
    volumes for the copy. It is removed once the stream ends.
    """
    _get_volume(name)
    try:
        container = _client().containers.create(**_helper_options(name, image))
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    try:
        raw, file_stat = container.get_archive(VOLUME_ROOT + path, chunk_size=_CHUNK_SIZE)
        if file_stat.get("mode", 0) & _GO_MODE_TYPE:
            raise NotAFile(f"{path} is not a regular file")
        # Closed by chunks() below, once the response has streamed the file.
        tar = tarfile.open(fileobj=io.BufferedReader(_ChunkReader(raw)), mode="r|")  # noqa: SIM115
        member = tar.next()
        source = tar.extractfile(member) if member else None
        if source is None:
            raise NotAFile(f"{path} is not a regular file")
    except NotFound as exc:
        _remove_quietly(container)
        raise DockerNotFound(f"no file {path} in volume {name}") from exc
    except DockerException as exc:
        _remove_quietly(container)
        raise DockerUnavailable(str(exc)) from exc
    except BaseException:
        _remove_quietly(container)
        raise

    def chunks() -> Iterator[bytes]:
        try:
            while block := source.read(_CHUNK_SIZE):
                yield block
        finally:
            tar.close()
            _remove_quietly(container)

    return VolumeFile(
        name=posixpath.basename(path), size=int(file_stat.get("size", 0)), chunks=chunks()
    )


# --- Host helpers ------------------------------------------------------------

# Where host helper containers mount the host path they read.
HOST_ROOT = "/host"
# A host file is read into memory; the fail2ban database is a few MB.
_MAX_HOST_FILE = 64 * 1024 * 1024


class HostCommandFailed(Exception):
    """Raised when a command run on the host through a helper exits non-zero."""


def _host_helper_options(source: str, image: str, purpose: str) -> dict[str, Any]:
    return {
        "image": image,
        # A Mount, unlike a `volumes` bind, fails on a missing source instead of
        # creating an empty folder on the host.
        "mounts": [Mount(target=HOST_ROOT, source=source, type="bind", read_only=True)],
        "network_mode": "none",
        "labels": {"drydock.helper": purpose},
    }


COMPOSE_HELPER = "compose"


def start_compose_helper(
    script: str,
    *,
    job_id: str,
    parent_id: str,
    mounts: list[Mount],
    working_dir: str,
    environment: dict[str, str],
) -> str:
    """Start `sh -c script` in a detached copy of container `parent_id`; returns its ID.

    The copy has the parent's image, mounts (Docker socket, repo, data) and
    user, and lives on its own. A Compose run that recreates the parent (DryDock
    updating itself) stops the parent halfway, so it cannot run inside it. The
    `drydock.job` label lets a restarted DryDock find the helper again.
    """
    attrs = _get_container(parent_id).attrs or {}
    image = container_image(parent_id)
    if image is None:
        raise DockerNotFound(f"no local image to copy container {parent_id} with")
    try:
        # create + start, not run: run pulls an image it cannot find, and an
        # image ID is not something a registry has.
        helper = _client().containers.create(
            image=image,
            entrypoint=["sh", "-c"],
            command=[script],
            volumes_from=[parent_id],
            mounts=mounts,
            working_dir=working_dir,
            environment=environment,
            user=(attrs.get("Config") or {}).get("User") or "",
            group_add=(attrs.get("HostConfig") or {}).get("GroupAdd") or None,
            labels={"drydock.helper": COMPOSE_HELPER, "drydock.job": job_id},
            log_config=LogConfig(type=LogConfig.types.JSON),
        )
        helper.start()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return helper.id or ""


def follow_helper(
    helper_id: str,
    on_output: Callable[[str], None],
    *,
    timeout: float,
    stop: threading.Event,
) -> int | None:
    """Wait for a helper to exit, passing its output on as it grows; returns its exit code.

    Returns None as soon as `stop` is set, leaving the helper running. Past
    `timeout` seconds it kills the helper and raises TimeoutError.
    """
    container = _get_container(helper_id)
    deadline = time.monotonic() + timeout
    shown: str | None = None
    while True:
        try:
            container.reload()
            output = container.logs().decode("utf-8", errors="replace")
        except NotFound as exc:
            raise DockerNotFound(f"container {helper_id} not found") from exc
        except DockerException as exc:
            raise DockerUnavailable(str(exc)) from exc
        if output != shown:
            on_output(output)
            shown = output
        if container.status in ("exited", "dead"):
            return (container.attrs.get("State") or {}).get("ExitCode", 1)
        if time.monotonic() > deadline:
            with contextlib.suppress(DockerException):
                container.kill()
            raise TimeoutError(f"helper {helper_id} still running after {timeout:.0f}s")
        if stop.wait(2):
            return None


def compose_helpers() -> dict[str, str]:
    """Compose helpers in any state, as job ID -> container ID."""
    try:
        helpers = _client().containers.list(
            all=True, filters={"label": f"drydock.helper={COMPOSE_HELPER}"}
        )
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return {
        helper.labels["drydock.job"]: helper.id or ""
        for helper in helpers
        if helper.labels.get("drydock.job")
    }


def remove_helper(helper_id: str) -> None:
    """Remove a helper container, running or not. Best effort: it is only clutter."""
    try:
        _client().containers.get(helper_id).remove(force=True)
    except NotFound:
        pass
    except (DockerException, DockerUnavailable) as exc:
        logger.warning("Could not remove helper container %s: %s", helper_id, exc)


def _missing_source(exc: APIError) -> bool:
    return "bind source path does not exist" in str(exc)


def run_on_host(
    script: str,
    *,
    image: str,
    writable: tuple[str, ...] = (),
    environment: dict[str, str] | None = None,
    host_network: bool = False,
) -> str:
    """Output of `sh -c script` chrooted into the host's root, mounted read-only.

    The host's own binaries run (its apt, its shell), so the output is what the
    host itself would print, whatever DryDock's image is. `writable` host folders
    are mounted read-write on top, so a script can only write there.
    `host_network` runs it in the host's network namespace with NET_ADMIN, for
    the host's firewall (nftables); otherwise it has no network at all.
    """
    options = _host_helper_options("/", image, "host-command")
    options["mounts"] += [
        Mount(target=posixpath.join(HOST_ROOT, path.lstrip("/")), source=path, type="bind")
        for path in writable
    ]
    if host_network:
        options["network_mode"] = "host"
        options["cap_add"] = ["NET_ADMIN"]
    try:
        output = _client().containers.run(
            entrypoint=["chroot"],
            command=[HOST_ROOT, "sh", "-c", script],
            remove=True,
            environment=environment,
            log_config=LogConfig(type=LogConfig.types.JSON),
            **options,
        )
    except ContainerError as exc:
        raise HostCommandFailed(str(exc)) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    return (output or b"").decode("utf-8", errors="replace")


def read_host_file(path: str, *, image: str) -> bytes:
    """Content of a regular file on the host, copied out of a helper container.

    Like volume downloads, the helper is only created, never started.
    """
    folder, name = posixpath.split(path)
    try:
        container = _client().containers.create(**_host_helper_options(folder, image, "host-file"))
    except APIError as exc:
        if _missing_source(exc):
            raise DockerNotFound(f"{folder} does not exist on the host") from exc
        raise DockerUnavailable(str(exc)) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    try:
        raw, _ = container.get_archive(posixpath.join(HOST_ROOT, name), chunk_size=_CHUNK_SIZE)
        with tarfile.open(fileobj=io.BufferedReader(_ChunkReader(raw)), mode="r|") as tar:
            member = tar.next()
            source = tar.extractfile(member) if member else None
            if member is None or source is None:
                raise NotAFile(f"{path} is not a regular file")
            if member.size > _MAX_HOST_FILE:
                raise NotAFile(f"{path} is larger than {_MAX_HOST_FILE // 1024**2} MB")
            return source.read()
    except NotFound as exc:
        raise DockerNotFound(f"{path} does not exist on the host") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    finally:
        _remove_quietly(container)


# --- Registries --------------------------------------------------------------


def registry_login(registry: str, username: str, password: str) -> None:
    """Have the daemon check credentials against the registry.

    Uses a throwaway client: docker-py keeps a successful login in memory, and
    the shared client must only use what is stored on disk.
    """
    try:
        client = docker.from_env()
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    try:
        client.login(username=username, password=password, registry=registry, reauth=True)
    except APIError as exc:
        raise RegistryLoginFailed(f"login to {registry} failed: {exc.explanation or exc}") from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc
    finally:
        client.close()


# --- Images ------------------------------------------------------------------


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

    wanted = registry_service.split_tag(image)[0]
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


def registry_digest(image: str, auth_config: dict[str, str] | None = None) -> str:
    """Look up an image's current manifest digest in its registry.

    This is a metadata request only - nothing is downloaded, which is what makes
    running it across every image practical on a Pi.
    """
    try:
        return _client().images.get_registry_data(image, auth_config=auth_config).id
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
        if exc.status_code == 409:
            raise ImageInUse(exc.explanation or f"image {image} is in use") from exc
        raise DockerUnavailable(str(exc)) from exc
    except DockerException as exc:
        raise DockerUnavailable(str(exc)) from exc


def prune_images() -> PruneResult:
    """Prune every image without a container (`docker image prune -a`), dangling ones included."""
    try:
        # dangling=false is Docker's "all": tagged images go too, not only <none> ones.
        result = _client().images.prune(filters={"dangling": False})
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
