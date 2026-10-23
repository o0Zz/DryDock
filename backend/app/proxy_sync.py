"""Turn `expose.*` container labels into reverse proxy config. Runs as a side container.

The proxy stack starts it from DryDock's own image (`python -m app.proxy_sync`), with the
Docker socket (read only) and the proxy's config folder. The labels name no proxy, so the
Compose files stay the same whatever proxy reads them; PROXY picks the writer:

    expose.host     host name, or several separated by commas
    expose.port     the container port to forward to
    expose.private  "false" makes the service public; anything else keeps it private

Writers:

    traefik  dynamic/expose.yml for Traefik's file provider, which Traefik watches.
    swag     site-confs/drydock-expose.conf for SWAG's nginx; checked with `nginx -t`,
             then `nginx -s reload`, both run in PROXY_CONTAINER.
    caddy    the whole Caddyfile; `caddy reload` in PROXY_CONTAINER checks and loads it.
             With a DNS_PROVIDER (ovh, cloudflare) hosts are grouped under wildcard sites
             (`*.example.org`): one certificate per domain. With `http`, one per name.

A config the proxy refuses is put back to the previous one, so a bad label never takes
the proxy down.

Every route sends Strict-Transport-Security: everything is served over HTTPS, so
browsers may refuse plain HTTP for these names.

Private services only answer an IP allowlist: LAN_RANGES, the current public IP (LAN and
VPN clients often come back through it, hairpin NAT) and TRUSTED_IPS.

A container with `network_mode: host` is reached at host.docker.internal (the proxy maps it
with extra_hosts: host-gateway). Any other container must share NETWORK with the proxy; it
is reached by name, which survives a recreate where its IP does not.

With ALLOWLIST_FILE set it also writes that allowlist, one entry per line, for tools that
must never block those IPs (DryDock's fail2ban jails read it).

Every POLL_SECONDS it lists the running containers with an `expose.host` label (one cheap
API call); every IP_REFRESH_SECONDS it asks for the public IP. The config is only rewritten
when it changes, so the proxy reloads only then.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
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
# A config the proxy refused is tried again after this long: it may only have been
# starting (SWAG writes its own nginx config on its first start).
RETRY_SECONDS = 60

_HOST_NAME = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$")
_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


@dataclass(frozen=True)
class Route:
    name: str
    hosts: tuple[str, ...]
    url: str
    private: bool

    @property
    def target(self) -> str:
        """`host:port` of the service."""
        return self.url.removeprefix("http://")


@dataclass
class Config:
    proxy: str = "traefik"
    output: Path = Path("/dynamic")
    network: str = "proxy"
    entrypoint: str = "websecure"
    lan_ranges: list[str] = field(default_factory=lambda: ["192.168.0.0/16"])
    trusted_ips: list[str] = field(default_factory=list)
    poll_seconds: float = 5
    ip_refresh_seconds: float = 300
    allowlist_file: Path | None = None
    # The proxy's container, where SWAG and Caddy are told to reload.
    proxy_container: str = ""
    # SWAG's own ssl.conf already sends HSTS (recent versions): do not send it twice.
    ssl_conf_hsts: bool = False
    # Caddy only: how it gets certificates (CADDY_DNS). The other proxies set it up
    # in their own config.
    dns_provider: str = "http"

    @classmethod
    def from_env(cls) -> Config:
        env = os.environ
        proxy = env.get("PROXY", "traefik")
        return cls(
            proxy=proxy,
            output=Path(env.get("OUTPUT", "/dynamic")),
            network=env.get("NETWORK", "proxy"),
            entrypoint=env.get("ENTRYPOINT", "websecure"),
            lan_ranges=_split(env.get("LAN_RANGES", "192.168.0.0/16")),
            trusted_ips=_split(env.get("TRUSTED_IPS", "")),
            poll_seconds=float(env.get("POLL_SECONDS", "5")),
            ip_refresh_seconds=float(env.get("IP_REFRESH_SECONDS", "300")),
            allowlist_file=Path(env["ALLOWLIST_FILE"]) if env.get("ALLOWLIST_FILE") else None,
            proxy_container=env.get("PROXY_CONTAINER", proxy),
            dns_provider=env.get("DNS_PROVIDER", "http"),
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


# --- Writers --------------------------------------------------------------------------


def render_traefik(routes: list[Route], sources: list[str], config: Config) -> str:
    """Traefik's dynamic config: one router and one service per route."""
    routers: dict[str, Any] = {}
    services: dict[str, Any] = {}
    for route in routes:
        middlewares = (["private"] if route.private else []) + ["hsts"]
        routers[route.name] = {
            "rule": " || ".join(f"Host(`{host}`)" for host in route.hosts),
            "entryPoints": [config.entrypoint],
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


def render_nginx(routes: list[Route], sources: list[str], config: Config) -> str:
    """Server blocks for SWAG, built like its own proxy-confs (ssl.conf, proxy.conf)."""
    blocks = [f"# {HEADER}"]
    for route in routes:
        lines = [
            "server {",
            "    listen 443 ssl;",
            "    listen [::]:443 ssl;",
            f"    server_name {' '.join(route.hosts)};",
            "    include /config/nginx/ssl.conf;",
            # Uploads are the service's business, as with Traefik and Caddy.
            "    client_max_body_size 0;",
        ]
        if not config.ssl_conf_hsts:
            lines.append(
                f'    add_header Strict-Transport-Security "max-age={HSTS_SECONDS}" always;'
            )
        if route.private:
            lines += [f"    allow {source};" for source in sources] + ["    deny all;"]
        lines += ["    location / {", "        include /config/nginx/proxy.conf;"]
        host, port = route.target.rsplit(":", 1)
        if host == HOST_GATEWAY:
            # From /etc/hosts (extra_hosts), which nginx only reads for a fixed name.
            lines.append(f"        proxy_pass {route.url};")
        else:
            # Through Docker's DNS at request time: nginx still starts while a
            # service is down.
            lines += [
                "        include /config/nginx/resolver.conf;",
                f"        set $upstream_app {host};",
                f"        set $upstream_port {port};",
                "        proxy_pass http://$upstream_app:$upstream_port;",
            ]
        lines += ["    }", "}"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _site(host: str) -> str:
    """The Caddy site a host belongs to: `*.example.org` for `a.example.org`."""
    labels = host.split(".")
    return "*." + ".".join(labels[1:]) if len(labels) > 2 else host


# How Caddy proves it owns the domain, by DNS_PROVIDER. A DNS provider gets wildcard
# certificates and needs its caddy-dns module in the image (the template builds it); the
# values come from the container's env. `http` needs nothing: one certificate per name,
# through port 80, for any domain.
CADDY_DNS: dict[str, list[str]] = {
    "ovh": [
        "\tacme_dns ovh {",
        "\t\tendpoint {$OVH_ENDPOINT}",
        "\t\tapplication_key {$OVH_APPLICATION_KEY}",
        "\t\tapplication_secret {$OVH_APPLICATION_SECRET}",
        "\t\tconsumer_key {$OVH_CONSUMER_KEY}",
        "\t}",
    ],
    "cloudflare": ["\tacme_dns cloudflare {$CF_DNS_API_TOKEN}"],
    "http": [],
}


def render_caddy(routes: list[Route], sources: list[str], config: Config) -> str:
    """A whole Caddyfile. Credentials stay placeholders, filled in from Caddy's own env."""
    wildcard = config.dns_provider != "http"
    out = [f"# {HEADER}", "{", "\temail {$ACME_EMAIL}", *CADDY_DNS[config.dns_provider], "}"]
    out += [
        "",
        "(common) {",
        "\tlog {",
        "\t\toutput file /logs/access.log",
        "\t\tformat json",
        "\t}",
        f'\theader Strict-Transport-Security "max-age={HSTS_SECONDS}"',
        "}",
    ]
    sites: dict[str, list[tuple[str, Route]]] = {}
    for route in routes:
        for host in route.hosts:
            # Without a DNS provider there is no wildcard: one site, one certificate per name.
            sites.setdefault(_site(host) if wildcard else host, []).append((host, route))
    for site, entries in sorted(sites.items()):
        out += ["", f"{site} {{", "\timport common"]
        for host, route in entries:
            # One matcher per host: a route with several hosts gets several.
            matcher = "@" + host.replace(".", "_")
            out += [f"\t{matcher} host {host}", f"\thandle {matcher} {{"]
            if route.private:
                out += [
                    f"\t\t@blocked not remote_ip {' '.join(sources)}",
                    "\t\trespond @blocked 403",
                ]
            out += [f"\t\treverse_proxy {route.target}", "\t}"]
        # Any other name of a wildcard: no service behind it.
        out += ["\thandle {", "\t\tabort", "\t}", "}"]
    return "\n".join(out) + "\n"


@dataclass(frozen=True)
class Writer:
    filename: str
    render: Callable[[list[Route], list[str], Config], str]
    # Run in the proxy's container after a write; a failure puts the old file back.
    check: tuple[str, ...] = ()
    reload: tuple[str, ...] = ()


WRITERS = {
    # Traefik watches its folder.
    "traefik": Writer("expose.yml", render_traefik),
    "swag": Writer(
        "drydock-expose.conf", render_nginx, ("nginx", "-t"), ("nginx", "-s", "reload")
    ),
    # `caddy reload` refuses a bad config and keeps the running one.
    "caddy": Writer(
        "Caddyfile",
        render_caddy,
        reload=("caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"),
    ),
}


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


def in_proxy(client: Any, config: Config, command: tuple[str, ...]) -> tuple[bool | None, str]:
    """Run a command in the proxy's container: (succeeded, output).

    None when the container is missing or not running.
    """
    try:
        result = client.containers.get(config.proxy_container).exec_run(list(command))
    except DockerException as exc:
        return None, str(exc)
    return result.exit_code == 0, (result.output or b"").decode("utf-8", errors="replace")


def deploy(client: Any, config: Config, writer: Writer, content: str) -> str:
    """Write the config and have the proxy load it: "changed", "unchanged" or "rejected"."""
    path = config.output / writer.filename
    previous = read(path)
    if previous == content:
        return "unchanged"
    write(path, content)
    for step in (writer.check, writer.reload):
        if not step:
            continue
        ok, output = in_proxy(client, config, step)
        if ok is None:
            # Not running yet, or restarting: it reads the file when it starts.
            logger.info("%s not reachable (%s); it loads the file on start", config.proxy, output)
            return "changed"
        if not ok:
            logger.error("%s failed, previous config put back: %s", " ".join(step), output[-800:])
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                write(path, previous)
            return "rejected"
    return "changed"


def ssl_conf_sets_hsts(path: Path) -> bool:
    return any(
        line.strip().startswith("add_header Strict-Transport-Security")
        for line in (read(path) or "").splitlines()
    )


def public_ip() -> str | None:
    try:
        answer = httpx.get("https://api.ipify.org", timeout=10).text.strip()
    except httpx.HTTPError as exc:
        logger.warning("Public IP lookup failed: %s", exc)
        return None
    return answer if _IPV4.match(answer) else None


def run(config: Config) -> None:
    if config.proxy not in WRITERS:
        raise SystemExit(f"PROXY={config.proxy} is not supported (only: {', '.join(WRITERS)})")
    writer = WRITERS[config.proxy]
    if config.proxy == "caddy" and config.dns_provider not in CADDY_DNS:
        raise SystemExit(
            f"DNS_PROVIDER={config.dns_provider} is not supported for Caddy "
            f"(only: {', '.join(CADDY_DNS)})"
        )
    client = docker.from_env()
    ip: str | None = None
    next_ip_check = 0.0
    last_problems: list[str] | None = None
    last_rendered: str | None = None
    retry_at: float | None = None
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
        if config.proxy == "swag":
            config.ssl_conf_hsts = ssl_conf_sets_hsts(config.output.parent / "ssl.conf")
        content = writer.render(routes, sources, config)
        retry = retry_at is not None and time.monotonic() >= retry_at
        if content != last_rendered or retry:
            last_rendered = content
            result = deploy(client, config, writer, content)
            retry_at = time.monotonic() + RETRY_SECONDS if result == "rejected" else None
            if result == "changed":
                logger.info(
                    "Wrote %s: %d routes (%s)",
                    writer.filename,
                    len(routes),
                    ", ".join(host for route in routes for host in route.hosts) or "none",
                )
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(Config.from_env())
