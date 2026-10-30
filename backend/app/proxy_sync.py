"""Turn `expose.*` container labels into reverse proxy config. Runs as a side container.

The proxy stack starts it from DryDock's own image (`python -m app.proxy_sync`), with the
Docker socket (read only) and the proxy's config folder. The labels name no proxy, so the
Compose files stay the same whatever proxy reads them:

    expose.host     host name, or several separated by commas
    expose.port     the container port to forward to
    expose.private  "false" makes the service public; anything else keeps it private

It writes OUTPUT/expose.yml for Traefik's file provider, which Traefik watches. Traefik
keeps its last good config when it refuses a file, so a bad label never takes it down.
Another proxy needs another renderer here, not other labels.

Every route sends Strict-Transport-Security: everything is served over HTTPS, so
browsers may refuse plain HTTP for these names.

Private services only answer an IP allowlist: LAN_RANGES, the current public IP (LAN and
VPN clients often come back through it, hairpin NAT) and TRUSTED_IPS.

A container with `network_mode: host` is reached at host.docker.internal (Traefik maps it
with extra_hosts: host-gateway). Any other container must share NETWORK with Traefik; it
is reached by name, which survives a recreate where its IP does not.

With ALLOWLIST_FILE set it also writes that allowlist, one entry per line, for tools that
must never block those IPs (DryDock's fail2ban jails read it).

Every POLL_SECONDS it lists the running containers with an `expose.host` label (one cheap
API call); every IP_REFRESH_SECONDS it asks for the public IP. The file is only rewritten
when it changes, so Traefik reloads only then.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docker
import httpx
import yaml
from docker.errors import DockerException

logger = logging.getLogger("proxy_sync")

LABEL_PREFIX = "expose."
HOST_GATEWAY = "host.docker.internal"
HSTS_SECONDS = 15768000  # six months
HEADER = "Written by DryDock's proxy sync from expose.* labels. Edits are overwritten."
FILENAME = "expose.yml"
# Traefik's HTTPS entrypoint, as the stack template names it.
ENTRYPOINT = "websecure"

_HOST_NAME = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$")
_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


@dataclass(frozen=True)
class Route:
    name: str
    hosts: tuple[str, ...]
    url: str
    private: bool


@dataclass
class Config:
    output: Path = Path("/dynamic")
    network: str = "proxy"
    lan_ranges: list[str] = field(default_factory=lambda: ["192.168.0.0/16"])
    trusted_ips: list[str] = field(default_factory=list)
    poll_seconds: float = 5
    ip_refresh_seconds: float = 300
    allowlist_file: Path | None = None

    @classmethod
    def from_env(cls) -> Config:
        env = os.environ
        return cls(
            output=Path(env.get("OUTPUT", "/dynamic")),
            network=env.get("NETWORK", "proxy"),
            lan_ranges=_split(env.get("LAN_RANGES", "192.168.0.0/16")),
            trusted_ips=_split(env.get("TRUSTED_IPS", "")),
            poll_seconds=float(env.get("POLL_SECONDS", "5")),
            ip_refresh_seconds=float(env.get("IP_REFRESH_SECONDS", "300")),
            allowlist_file=Path(env["ALLOWLIST_FILE"]) if env.get("ALLOWLIST_FILE") else None,
        )


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.replace(" ", ",").split(",") if item.strip()]


def routes_from(containers: list[dict[str, Any]], network: str) -> tuple[list[Route], list[str]]:
    """Routes for containers as the Docker API lists them, and why others were skipped."""
    routes: list[Route] = []
    problems: list[str] = []
    for container in containers:
        name = (container.get("Names") or ["/?"])[0].lstrip("/")
        labels = container.get("Labels") or {}
        hosts = tuple(host.lower() for host in _split(labels.get(f"{LABEL_PREFIX}host", "")))
        port = labels.get(f"{LABEL_PREFIX}port", "").strip()
        bad = [host for host in hosts if not _HOST_NAME.match(host)]
        if not hosts or bad:
            problems.append(f"{name}: invalid expose.host {labels.get(f'{LABEL_PREFIX}host')!r}")
            continue
        if not port.isdigit() or not 0 < int(port) < 65536:
            problems.append(f"{name}: expose.port must be the container port, got {port!r}")
            continue
        mode = (container.get("HostConfig") or {}).get("NetworkMode", "")
        if mode == "host":
            target = HOST_GATEWAY
        elif network in ((container.get("NetworkSettings") or {}).get("Networks") or {}):
            target = name
        else:
            problems.append(f"{name}: not on the {network} network, the proxy cannot reach it")
            continue
        routes.append(
            Route(
                name=re.sub(r"[^A-Za-z0-9-]+", "-", name).strip("-"),
                hosts=hosts,
                url=f"http://{target}:{port}",
                private=labels.get(f"{LABEL_PREFIX}private", "true").strip().lower() != "false",
            )
        )
    # Two containers claiming one host would make the proxy pick one at random.
    seen: dict[str, str] = {}
    kept = []
    for route in sorted(routes, key=lambda route: route.name):
        taken = [host for host in route.hosts if host in seen]
        if taken:
            problems.append(f"{route.name}: {', '.join(taken)} already used by {seen[taken[0]]}")
            continue
        seen.update(dict.fromkeys(route.hosts, route.name))
        kept.append(route)
    return kept, problems


def allowlist(config: Config, public_ip: str | None) -> list[str]:
    ranges = [*config.lan_ranges, *([public_ip] if public_ip else []), *config.trusted_ips]
    return list(dict.fromkeys(ranges))


# --- Rendering ------------------------------------------------------------------------


def render(routes: list[Route], sources: list[str]) -> str:
    """Traefik's dynamic config: one router and one service per route."""
    routers: dict[str, Any] = {}
    services: dict[str, Any] = {}
    for route in routes:
        middlewares = (["private"] if route.private else []) + ["hsts"]
        routers[route.name] = {
            "rule": " || ".join(f"Host(`{host}`)" for host in route.hosts),
            "entryPoints": [ENTRYPOINT],
            "service": route.name,
            "middlewares": middlewares,
        }
        services[route.name] = {"loadBalancer": {"servers": [{"url": route.url}]}}
    dynamic = {
        "http": {
            "routers": routers,
            "services": services,
            "middlewares": {
                # Also used by hand as private@file, e.g. on Traefik's own dashboard.
                "private": {"ipAllowList": {"sourceRange": sources}},
                "hsts": {"headers": {"stsSeconds": HSTS_SECONDS}},
            },
        }
    }
    return f"# {HEADER}\n" + yaml.safe_dump(dynamic, sort_keys=False, default_flow_style=False)


# --- Running --------------------------------------------------------------------------


def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def write(path: Path, content: str) -> None:
    # The sync may start before the proxy has created its folders.
    path.parent.mkdir(parents=True, exist_ok=True)
    # A dot name the proxy ignores: it must never read a half-written file.
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def write_if_changed(path: Path, content: str) -> bool:
    if read(path) == content:
        return False
    write(path, content)
    return True


def public_ip() -> str | None:
    try:
        answer = httpx.get("https://api.ipify.org", timeout=10).text.strip()
    except httpx.HTTPError as exc:
        logger.warning("Public IP lookup failed: %s", exc)
        return None
    return answer if _IPV4.match(answer) else None


def run(config: Config) -> None:
    client = docker.from_env()
    ip: str | None = None
    next_ip_check = 0.0
    last_problems: list[str] | None = None
    while True:
        if time.monotonic() >= next_ip_check:
            # Keep the last known IP when the lookup fails: a gap would lock you out.
            ip = public_ip() or ip
            next_ip_check = time.monotonic() + config.ip_refresh_seconds
        try:
            containers = client.api.containers(filters={"label": f"{LABEL_PREFIX}host"})
        except DockerException as exc:
            logger.warning("Docker unavailable: %s", exc)
            time.sleep(config.poll_seconds)
            continue
        routes, problems = routes_from(containers, config.network)
        if problems != last_problems:
            for problem in problems:
                logger.warning("Skipped %s", problem)
            last_problems = problems
        sources = allowlist(config, ip)
        if config.allowlist_file and write_if_changed(
            config.allowlist_file, "\n".join(sources) + "\n"
        ):
            logger.info("Wrote %s: %s", config.allowlist_file.name, ", ".join(sources))
        if write_if_changed(config.output / FILENAME, render(routes, sources)):
            logger.info(
                "Wrote %s: %d routes (%s)",
                FILENAME,
                len(routes),
                ", ".join(host for route in routes for host in route.hosts) or "none",
            )
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(Config.from_env())
