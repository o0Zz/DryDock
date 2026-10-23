"""Expose stack services through a reverse proxy, with neutral Compose labels.

DryDock never carries the traffic, and its labels name no proxy:

    expose.host     host name, or several separated by commas
    expose.port     the container port to forward to
    expose.private  "false" makes the service public; anything else keeps it private
    expose.hsts     "true" adds a Strict-Transport-Security header (written by hand)

The proxy stack runs DryDock's proxy sync (`app.proxy_sync`) next to the proxy. It reads
these labels from the running containers and writes the proxy's own config, so the Compose
files stay the same whatever proxy runs, and a plain `docker compose up` keeps them.

This module reads and writes the labels in the Compose files and lists what is exposed.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from app.schemas.project import Project
from app.schemas.proxy import ProxyContainer, ProxyRoute, ServiceExposure
from app.services import compose_service, docker_service, repo_service

LABEL_PREFIX = "expose."
# Images of the proxies the sync can write for, to find the proxy's container.
PROXY_IMAGES = ("traefik",)
# Set on the proxy sync's container by the proxy stack, to find it.
SYNC_LABEL = "drydock.proxy-sync"
# Labels of an older setup: a proxy reading them would route the service twice.
_LEGACY_PREFIXES = ("traefik.", "swag_")

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")
_HOST_NAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$"
)


class ProxyError(compose_service.ComposeError):
    """The requested exposure cannot be written (unknown service, bad host...)."""


def _legacy(key: str) -> bool:
    return key == "swag" or key.startswith(_LEGACY_PREFIXES)


# --- Reading --------------------------------------------------------------------------


def _labels(spec: dict[str, Any]) -> dict[str, str]:
    """A service's labels as a mapping, from either Compose form (list or mapping)."""
    raw = spec.get("labels")
    if isinstance(raw, dict):
        return {str(key): "" if value is None else str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        labels = {}
        for item in raw:
            key, _, value = str(item).partition("=")
            labels[key.strip()] = value.strip()
        return labels
    return {}


def _declared_ports(spec: dict[str, Any]) -> list[int]:
    """Container ports named by `ports` (the target side) and `expose`."""
    candidates = []
    for entry in spec.get("ports") or []:
        if isinstance(entry, dict):
            candidates.append(str(entry.get("target", "")))
        else:
            # [ip:][published:]target[/protocol]
            candidates.append(str(entry).rsplit(":", 1)[-1])
    candidates.extend(str(entry) for entry in spec.get("expose") or [])
    # Ranges (`8000-8010`) and variables are skipped.
    ports = {port.split("/")[0] for port in candidates}
    return sorted(int(port) for port in ports if port.isdigit())


def _host_network(spec: dict[str, Any]) -> bool:
    return spec.get("network_mode") == "host"


def _blocked(spec: dict[str, Any]) -> str | None:
    mode = spec.get("network_mode")
    # A host-network service is reached at host.docker.internal.
    if not mode or mode == "host":
        return None
    return f"uses network_mode: {mode}; the proxy reaches services over a Docker network"


def describe(name: str, spec: Any) -> ServiceExposure:
    spec = spec if isinstance(spec, dict) else {}
    labels = _labels(spec)
    hosts = [host.strip() for host in labels.get(f"{LABEL_PREFIX}host", "").split(",")]
    port = labels.get(f"{LABEL_PREFIX}port", "").strip()
    return ServiceExposure(
        service=name,
        exposed=any(hosts),
        hosts=[host for host in hosts if host],
        port=int(port) if port.isdigit() else None,
        public=labels.get(f"{LABEL_PREFIX}private", "true").strip().lower() == "false",
        ports=_declared_ports(spec),
        blocked=_blocked(spec),
        legacy=any(_legacy(key) for key in labels),
    )


def services(content: str) -> list[ServiceExposure]:
    compose_service.validate_yaml(content)
    data = _yaml().load(content)
    return [describe(str(name), spec) for name, spec in data["services"].items()]


def _env_values(compose_path: Path) -> dict[str, str]:
    """Plain `KEY=value` lines of the stack's .env, enough to resolve a host name."""
    values = {}
    for line in (compose_service.read_env(compose_path) or "").splitlines():
        match = _ENV_LINE.match(line)
        if match and not line.lstrip().startswith("#"):
            values[match.group(1)] = match.group(2).strip("\"'")
    return values


def _interpolate(text: str, values: dict[str, str]) -> str:
    if "${" not in text:
        return text
    return _VARIABLE.sub(lambda match: values.get(match.group(1)) or match.group(2) or "", text)


def routes(projects: list[Project]) -> list[ProxyRoute]:
    """Every exposed service across the repo. Call with containers attached."""
    found = []
    for project in projects:
        data = repo_service.load_compose(project.compose_path)
        specs = data.get("services") if isinstance(data, dict) else None
        if not isinstance(specs, dict):
            continue
        env: dict[str, str] | None = None
        for name, spec in specs.items():
            exposure = describe(str(name), spec)
            if not exposure.exposed:
                continue
            if env is None and any("${" in host for host in exposure.hosts):
                env = _env_values(Path(project.compose_path))
            found.append(
                ProxyRoute(
                    project_id=project.id,
                    project_name=project.name,
                    service=exposure.service,
                    # `Host(`traefik.${PROXY_DOMAIN}`)`: Compose fills it in from the .env.
                    hosts=[_interpolate(host, env or {}) for host in exposure.hosts],
                    port=exposure.port,
                    public=exposure.public,
                    running=any(
                        container.compose_service == exposure.service
                        and container.state == "running"
                        for container in project.containers
                    ),
                )
            )
    return sorted(found, key=lambda route: (route.hosts[:1], route.project_name))


def _best(candidates: list[Any]) -> ProxyContainer | None:
    """The running one first: an old stopped copy must not hide the live one."""
    candidates.sort(key=lambda container: container.state != "running")
    if not candidates:
        return None
    best = candidates[0]
    return ProxyContainer(id=best.id, name=best.name, running=best.state == "running")


def proxy_containers() -> tuple[ProxyContainer | None, ProxyContainer | None]:
    """The proxy's container and the proxy sync's. Raises DockerUnavailable."""
    containers = docker_service.list_containers(all_states=True)
    proxies = [
        container
        for container in containers
        if container.image.split("@")[0].rsplit(":", 1)[0].rsplit("/", 1)[-1] in PROXY_IMAGES
    ]
    syncs = docker_service.list_containers(all_states=True, label=SYNC_LABEL)
    return _best(proxies), _best(syncs)


# --- Writing --------------------------------------------------------------------------


def full_host(host: str, domain: str) -> str:
    """`jellyfin` + `example.org` gives `jellyfin.example.org`; a full name stays."""
    host = host.strip().lower().rstrip(".")
    if "." not in host and domain:
        host = f"{host}.{domain.strip().lower().strip('.')}"
    if not _HOST_NAME.match(host):
        raise ProxyError(f"Invalid host name: {host}")
    return host


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    # Never fold long lines (Host rules, commands).
    yaml.width = 4096
    return yaml


def _guess_indent(content: str) -> tuple[int, int]:
    """The file's mapping indent and the dash offset of its block sequences.

    ruamel writes one style for the whole file, so take the most common one: a file
    written with `- item` under its key (offset 0) stays that way.
    """
    mapping: dict[int, int] = {}
    offsets: dict[int, int] = {}
    previous: tuple[int, str] | None = None
    for line in content.splitlines():
        stripped = line.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if previous and previous[1].endswith(":") and indent > previous[0]:
            if stripped.startswith("- "):
                offset = indent - previous[0]
                offsets[offset] = offsets.get(offset, 0) + 1
            else:
                step = indent - previous[0]
                mapping[step] = mapping.get(step, 0) + 1
        previous = (indent, stripped.split(" #")[0].rstrip())
    mapping_indent = max(mapping, key=lambda key: mapping[key]) if mapping else 2
    offset = max(offsets, key=lambda key: offsets[key]) if offsets else mapping_indent
    return mapping_indent, offset


def _load(content: str) -> tuple[YAML, CommentedMap]:
    compose_service.validate_yaml(content)
    # ruamel keeps the `\r` of CRLF inside comments; _dump puts CRLF back.
    content = content.replace("\r\n", "\n")
    yaml = _yaml()
    try:
        data = yaml.load(content)
    except YAMLError as exc:
        raise ProxyError(f"Invalid YAML: {exc}") from exc
    mapping_indent, offset = _guess_indent(content)
    yaml.indent(mapping=mapping_indent, sequence=offset + 2, offset=offset)
    return yaml, data


def _tail(node: Any) -> tuple[Any, Any] | None:
    """The innermost last entry of a mapping or sequence: (its container, its key)."""
    while isinstance(node, (CommentedMap, CommentedSeq)) and len(node):
        key = list(node)[-1] if isinstance(node, CommentedMap) else len(node) - 1
        value = node[key]
        if isinstance(value, (CommentedMap, CommentedSeq)) and len(value):
            node = value
            continue
        return node, key
    return None


def _comment_slot(node: Any) -> int:
    # ruamel keeps the comment after a mapping value at index 2, after a list item at 0.
    return 2 if isinstance(node, CommentedMap) else 0


def _take_trailing_comment(node: Any) -> Any:
    """Detach the comment that ends a block, blank lines included.

    ruamel ties the blank line before the next top-level key to the block's last
    entry, so keys appended to the block would land after that blank line.
    """
    tail = _tail(node)
    if tail is None:
        return None
    container, key = tail
    entry = container.ca.items.get(key)
    if not entry or entry[_comment_slot(container)] is None:
        return None
    token = entry[_comment_slot(container)]
    entry[_comment_slot(container)] = None
    return token


def _put_trailing_comment(node: Any, token: Any) -> None:
    tail = _tail(node)
    if token is None or tail is None:
        return
    container, key = tail
    entry = container.ca.items.setdefault(key, [None, None, None, None])
    entry[_comment_slot(container)] = token


def _dump(yaml: YAML, data: CommentedMap, original: str) -> str:
    out = io.StringIO()
    yaml.dump(data, out)
    content = out.getvalue()
    compose_service.validate_yaml(content)
    # ruamel writes LF; a file edited on Windows keeps its CRLF.
    return content.replace("\n", "\r\n") if "\r\n" in original else content


def _service(data: CommentedMap, service: str) -> CommentedMap:
    specs = data["services"]
    if service not in specs:
        raise ProxyError(f"No service named {service} in this file")
    if specs[service] is None:
        specs[service] = CommentedMap()
    spec = specs[service]
    if not isinstance(spec, dict):
        raise ProxyError(f"Service {service} is not a mapping")
    return spec


def _rewrite_labels(spec: CommentedMap, drop: Any, add: dict[str, str]) -> None:
    """Remove the labels whose key `drop(key)` accepts, then add `add`, in the file's form."""
    raw = spec.get("labels")
    if isinstance(raw, dict):
        for key in [key for key in raw if drop(str(key))]:
            del raw[key]
        raw.update(add)
    else:
        items = [item for item in raw or [] if not drop(str(item).partition("=")[0].strip())]
        raw = CommentedSeq(items)
        raw.extend(f"{key}={value}" for key, value in add.items())
    if raw:
        spec["labels"] = raw
    elif "labels" in spec:
        del spec["labels"]


def _network_names(raw: Any) -> list[str]:
    if isinstance(raw, dict):
        return [str(name) for name in raw]
    if isinstance(raw, list):
        return [str(name) for name in raw]
    return []


def _attach(data: CommentedMap, spec: CommentedMap, network: str) -> None:
    raw = spec.get("networks")
    if isinstance(raw, dict):
        if network not in raw:
            raw[network] = None
    elif isinstance(raw, list):
        if network not in raw:
            raw.append(network)
    else:
        # A service without `networks` is on `default`; keep it there for its siblings.
        spec["networks"] = CommentedSeq(["default", network])
    top = data.get("networks")
    if top is None:
        data["networks"] = top = CommentedMap()
    if network not in top:
        # Created by the proxy stack, shared by every exposed stack.
        top[network] = CommentedMap(external=True)


def _detach(data: CommentedMap, spec: CommentedMap, network: str) -> None:
    raw = spec.get("networks")
    if isinstance(raw, dict):
        raw.pop(network, None)
        if list(raw) == ["default"] and raw["default"] is None:
            del spec["networks"]
    elif isinstance(raw, list):
        if network in raw:
            raw.remove(network)
        if list(raw) in ([], ["default"]):
            del spec["networks"]
    still_used = any(
        network in _network_names(other.get("networks"))
        for other in data["services"].values()
        if isinstance(other, dict)
    )
    top = data.get("networks")
    if still_used or not isinstance(top, dict) or network not in top:
        return
    # Only the declaration this module writes; a network the stack itself creates stays.
    if dict(top[network] or {}) == {"external": True}:
        del top[network]
        if not top:
            del data["networks"]


def expose(
    content: str,
    *,
    service: str,
    host: str,
    port: int,
    public: bool,
    network: str,
) -> str:
    """Write the service's `expose.*` labels. Labels of an older proxy setup go."""
    yaml, data = _load(content)
    spec = _service(data, service)
    reason = _blocked(spec)
    if reason:
        raise ProxyError(f"{service} {reason}")
    managed = {
        f"{LABEL_PREFIX}host": host,
        f"{LABEL_PREFIX}port": str(port),
        f"{LABEL_PREFIX}private": "false" if public else "true",
    }
    spec_tail, file_tail = _take_trailing_comment(spec), _take_trailing_comment(data)
    _rewrite_labels(spec, lambda key: key in managed or _legacy(key), managed)
    # A host-network container is reached through the host; it joins no network.
    if not _host_network(spec):
        _attach(data, spec, network)
    _put_trailing_comment(spec, spec_tail)
    _put_trailing_comment(data, file_tail)
    return _dump(yaml, data, content)


def unexpose(content: str, *, service: str, network: str) -> str:
    """Drop the service's `expose.*` labels and its link to the proxy network."""
    yaml, data = _load(content)
    spec = _service(data, service)
    spec_tail, file_tail = _take_trailing_comment(spec), _take_trailing_comment(data)
    _rewrite_labels(spec, lambda key: key.startswith(LABEL_PREFIX), {})
    _detach(data, spec, network)
    _put_trailing_comment(spec, spec_tail)
    _put_trailing_comment(data, file_tail)
    return _dump(yaml, data, content)
