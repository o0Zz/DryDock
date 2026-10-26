"""A list of known bad IPs (FireHOL level1 by default), dropped by the host's nftables.

fail2ban bans IPs it sees misbehave in a log, one at a time, until a ban time ends.
A blocklist is the other half: ranges known to be bad before they ever connect,
replaced as a whole once a day. DryDock downloads the lists, merges them, and loads
them in one nftables table it owns, `inet drydock_blocklist`, in one atomic step.

The table drops on the forward hook (ports Docker publishes: the proxy, a VPN) and on
the input hook (host-network services, SSH). Private and reserved ranges are never
blocked, whatever a list says: FireHOL level1 includes the bogons, 192.168.0.0/16
and 172.16.0.0/12 among them, which would cut the LAN and the containers off. The
proxy sync's allowlist (LAN, public IP, trusted IPs) and `ignore_ips` are let through
before the drop.

The table is not persistent: a host reboot clears it. DryDock loads it again when it
starts, and every 24 hours with a fresh download.
"""

from __future__ import annotations

import base64
import gzip
import ipaddress
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.blocklist import (
    IpBlocklistCheck,
    IpBlocklistConfig,
    IpBlocklistHost,
    IpBlocklistSource,
    IpBlocklistStatus,
)
from app.services import docker_service, settings_service, volume_files_service

logger = logging.getLogger(__name__)

SETTING = "ip_blocklist"
TABLE = "drydock_blocklist"
INTERVAL_HOURS = 24
TIMEOUT = 30.0
# A list is a few hundred kB; anything far bigger is not one.
MAX_DOWNLOAD = 10 * 1024**2
# The ruleset goes to the helper in one environment variable, which Linux caps at 128 kB.
MAX_RULESET = 120_000

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

# Never blocked: the LAN, Docker's networks, CGNAT (Tailscale), loopback, link-local,
# multicast and reserved. A list range that overlaps one is dropped as a whole.
NEVER: tuple[Network, ...] = tuple(
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)
# Broader ranges are a broken list, not a bad network.
_MIN_PREFIX = {4: 8, 6: 16}

_COUNTER = re.compile(r"counter packets (\d+)")


class BlocklistError(Exception):
    """A list could not be downloaded or loaded on the host."""


def get_config(db: Session) -> IpBlocklistConfig:
    return config_from(settings_service.get_all(db))


def config_from(values: dict[str, Any]) -> IpBlocklistConfig:
    return IpBlocklistConfig.model_validate(values.get(SETTING) or {})


def save_config(db: Session, config: IpBlocklistConfig) -> None:
    settings_service.set_many(db, {SETTING: config.model_dump()})


# --- Lists ----------------------------------------------------------------------------


def parse(text: str) -> list[Network]:
    """The ranges of a list: one IP or CIDR per line, `#` and `;` comments, junk skipped."""
    networks: list[Network] = []
    for line in text.splitlines():
        token = re.split(r"[\s#;]", line.strip(), maxsplit=1)[0]
        if not token:
            continue
        try:
            network = ipaddress.ip_network(token, strict=False)
        except ValueError:
            continue
        if network.prefixlen < _MIN_PREFIX[network.version]:
            continue
        if any(network.overlaps(never) for never in NEVER if never.version == network.version):
            continue
        networks.append(network)
    return networks


def fetch(url: str) -> list[Network]:
    try:
        with httpx.stream("GET", url, timeout=TIMEOUT, follow_redirects=True) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_DOWNLOAD:
                    raise BlocklistError(f"{url}: larger than {MAX_DOWNLOAD // 1024**2} MB")
    except httpx.HTTPError as exc:
        raise BlocklistError(f"{url}: {exc}") from exc
    networks = parse(body.decode("utf-8", errors="replace"))
    if not networks:
        # An error page or a moved file: loading it would silently empty the list.
        raise BlocklistError(f"{url}: no IP ranges in the answer")
    return networks


def collapse(networks: list[Network]) -> list[Network]:
    """Merged and sorted, one family after the other: an nftables interval set wants no overlap."""
    merged: list[Network] = []
    for version in (4, 6):
        merged += ipaddress.collapse_addresses(n for n in networks if n.version == version)
    return merged


# --- Cache ----------------------------------------------------------------------------
# What was last loaded, per source. A source that fails keeps its previous ranges, so a
# download error never shrinks the list, and a reboot without internet still loads one.


def _cache_path() -> Path:
    return settings.data_path / "blocklist" / "blocklist.json"


def _load_cache() -> dict[str, Any]:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(cache), encoding="utf-8")
    temp.replace(path)


def status() -> IpBlocklistStatus | None:
    cache = _load_cache()
    if not cache:
        return None
    return IpBlocklistStatus(
        applied_at=cache.get("applied_at"),
        entries=len(cache.get("block", [])),
        sources=[
            IpBlocklistSource(
                url=source["url"],
                entries=len(source.get("networks", [])),
                fetched_at=source.get("fetched_at"),
                error=source.get("error"),
            )
            for source in cache.get("sources", [])
        ],
    )


def refresh(urls: list[str]) -> list[dict[str, Any]]:
    """Download every source; one that fails keeps its cached ranges and reports the error."""
    cached = {source["url"]: source for source in _load_cache().get("sources", [])}
    sources = []
    for url in urls:
        try:
            networks = fetch(url)
            sources.append(
                {
                    "url": url,
                    "networks": [str(n) for n in networks],
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "error": None,
                }
            )
        except BlocklistError as exc:
            logger.warning("Blocklist download failed: %s", exc)
            previous = cached.get(url, {})
            sources.append(
                {
                    "url": url,
                    "networks": previous.get("networks", []),
                    "fetched_at": previous.get("fetched_at"),
                    "error": str(exc),
                }
            )
    if not any(source["networks"] for source in sources):
        errors = "; ".join(source["error"] or "" for source in sources)
        raise BlocklistError(f"No list could be downloaded: {errors}")
    return sources


def allowed(config: IpBlocklistConfig) -> list[Network]:
    """Never blocked: the private ranges, `ignore_ips`, and the allowlist file if readable."""
    networks = list(NEVER) + [ipaddress.ip_network(ip, strict=False) for ip in config.ignore_ips]
    if config.allowlist_file:
        try:
            text = docker_service.read_host_file(
                config.allowlist_file, image=volume_files_service.helper_image()
            ).decode("utf-8", errors="replace")
        except (docker_service.DockerNotFound, docker_service.NotAFile):
            text = ""
        for line in text.split():
            try:
                networks.append(ipaddress.ip_network(line, strict=False))
            except ValueError:
                continue
    return collapse(networks)


# --- Host -----------------------------------------------------------------------------


def _set(name: str, family: str, networks: list[Network]) -> str:
    lines = [f"\tset {name} {{", f"\t\ttype {family}_addr", "\t\tflags interval"]
    if networks:
        elements = ",\n\t\t\t".join(str(n) for n in networks)
        lines.append(f"\t\telements = {{\n\t\t\t{elements}\n\t\t}}")
    return "\n".join(lines + ["\t}"])


def _chain(hook: str) -> str:
    return "\n".join(
        [
            f"\tchain {hook} {{",
            f"\t\ttype filter hook {hook} priority -1; policy accept;",
            "\t\tip saddr @allow4 accept",
            "\t\tip6 saddr @allow6 accept",
            "\t\tip saddr @block4 counter drop",
            "\t\tip6 saddr @block6 counter drop",
            "\t}",
        ]
    )


def render(block: list[Network], allow: list[Network]) -> str:
    """The whole table. Declaring, deleting and re-creating it in one file swaps it atomically."""
    body = [
        _set("allow4", "ipv4", [n for n in allow if n.version == 4]),
        _set("allow6", "ipv6", [n for n in allow if n.version == 6]),
        _set("block4", "ipv4", [n for n in block if n.version == 4]),
        _set("block6", "ipv6", [n for n in block if n.version == 6]),
        _chain("forward"),
        _chain("input"),
    ]
    return (
        "# Managed by DryDock (Host page, IP blocklist).\n"
        f"table inet {TABLE}\n"
        f"delete table inet {TABLE}\n"
        f"table inet {TABLE} {{\n" + "\n".join(body) + "\n}\n"
    )


# Errors go to stderr: that is what a failed helper reports.
_LOAD = rf"""
set -e
command -v nft >/dev/null || {{ echo "nftables (nft) is not installed on the host" >&2; exit 2; }}
echo "$DRYDOCK_RULESET" | base64 -d | gzip -dc | nft -f -
nft list chain inet {TABLE} forward >/dev/null
echo "Blocklist loaded in table inet {TABLE}"
"""

_REMOVE = rf"""
command -v nft >/dev/null || exit 0
if nft list tables | grep -qx "table inet {TABLE}"; then
  nft delete table inet {TABLE}
  echo "Blocklist removed from the host"
else
  echo "No blocklist on the host"
fi
"""

_STATE = rf"""
command -v nft >/dev/null || {{ echo "@@nonft"; exit 0; }}
nft list tables | grep -qx "table inet {TABLE}" || {{ echo "@@absent"; exit 0; }}
nft list chain inet {TABLE} forward
nft list chain inet {TABLE} input
"""


def _on_host(script: str, environment: dict[str, str] | None = None) -> str:
    # nftables lives in the host's network namespace.
    try:
        return docker_service.run_on_host(
            script,
            image=volume_files_service.helper_image(),
            host_network=True,
            environment=environment,
        )
    except docker_service.HostCommandFailed as exc:
        raise BlocklistError(str(exc)) from exc


def apply(config: IpBlocklistConfig) -> str:
    """Download the lists and load them on the host, or remove the table when disabled."""
    if not config.enabled:
        return _on_host(_REMOVE)
    sources = refresh(config.sources)
    block = collapse(
        [ipaddress.ip_network(net) for source in sources for net in source["networks"]]
    )
    allow = allowed(config)
    ruleset = base64.b64encode(gzip.compress(render(block, allow).encode("utf-8"))).decode()
    if len(ruleset) > MAX_RULESET:
        raise BlocklistError(
            f"{len(block)} ranges are too many to load at once: use smaller lists"
        )
    output = _on_host(_LOAD, {"DRYDOCK_RULESET": ruleset})
    _save_cache(
        {
            "applied_at": datetime.now(UTC).isoformat(),
            "sources": sources,
            "block": [str(n) for n in block],
            "allow": [str(n) for n in allow],
        }
    )
    return output


def host_state() -> IpBlocklistHost:
    try:
        output = _on_host(_STATE)
    except BlocklistError as exc:
        return IpBlocklistHost(error=str(exc))
    except docker_service.DockerUnavailable as exc:
        return IpBlocklistHost(error=str(exc))
    if "@@nonft" in output:
        return IpBlocklistHost(active=False, error="nftables (nft) is not installed on the host")
    if "@@absent" in output:
        return IpBlocklistHost(active=False)
    return IpBlocklistHost(active=True, dropped=sum(int(n) for n in _COUNTER.findall(output)))


def check(ip: str) -> IpBlocklistCheck:
    """Whether the last loaded list blocks `ip`."""
    address = ipaddress.ip_address(ip)
    cache = _load_cache()
    for net in cache.get("allow", []):
        if address in ipaddress.ip_network(net):
            return IpBlocklistCheck(ip=ip, blocked=False, allowed_by=net)
    for net in cache.get("block", []):
        if address in ipaddress.ip_network(net):
            return IpBlocklistCheck(ip=ip, blocked=True, network=net)
    return IpBlocklistCheck(ip=ip, blocked=False)
