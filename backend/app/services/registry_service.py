"""Find newer version tags of an image by listing its registry's tags.

The digest check in update_service only notices a tag being rebuilt (`latest`,
`stable`). A pinned tag like `2025.10.4` never changes, so this module looks
for *other* tags of the same shape with a higher version.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

DOCKER_HUB = "registry-1.docker.io"
TIMEOUT = 15.0
PAGE_SIZE = 1000
# Docker Hub images like home-assistant have thousands of tags; cap the walk.
MAX_PAGES = 30

_VERSION_RE = re.compile(r"^(?P<prefix>\D*)(?P<ver>\d+(?:\.\d+)*)(?P<suffix>.*)$")
_CHALLENGE_RE = re.compile(r'(\w+)="([^"]*)"')
_NEXT_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="?next"?')


class RegistryError(Exception):
    """Raised when a registry's tag list cannot be fetched."""


# --- References --------------------------------------------------------------


def split_tag(image: str) -> tuple[str, str]:
    """Split an image reference into (name, tag), dropping any digest.
    The tag defaults to "latest"."""
    name = image.split("@", 1)[0]
    slash = name.rfind("/")
    colon = name.rfind(":")
    # A colon before the last slash belongs to a registry port, not a tag.
    if colon > slash:
        return name[:colon], name[colon + 1 :]
    return name, "latest"


def parse_reference(image: str) -> tuple[str, str, str]:
    """Split an image reference into (registry host, repository, tag)."""
    name, tag = split_tag(image)
    first, _, rest = name.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        registry, repository = first, rest
    else:
        registry, repository = DOCKER_HUB, name
    if registry in ("docker.io", "index.docker.io"):
        registry = DOCKER_HUB
    if registry == DOCKER_HUB and "/" not in repository:
        repository = f"library/{repository}"
    return registry, repository, tag


# --- Versions ----------------------------------------------------------------


@dataclass(frozen=True)
class TagVersion:
    tag: str
    # Tags only compare when their shape matches: same prefix, same number of
    # numeric parts, same suffix ignoring digits. That keeps `1.25-alpine` away
    # from `1.27`, and `2025.10.4` away from prereleases like `2025.11.0b3`.
    shape: tuple[str, int, str]
    numbers: tuple[int, ...]
    suffix_numbers: tuple[int, ...]

    @property
    def sort_key(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        return self.numbers, self.suffix_numbers


def parse_version(tag: str) -> TagVersion | None:
    """Parse a version-like tag; `None` for floating tags like `latest`."""
    match = _VERSION_RE.match(tag)
    if not match:
        return None
    numbers = tuple(int(part) for part in match["ver"].split("."))
    suffix = match["suffix"]
    return TagVersion(
        tag=tag,
        shape=(match["prefix"], len(numbers), re.sub(r"\d+", "", suffix)),
        numbers=numbers,
        suffix_numbers=tuple(int(digits) for digits in re.findall(r"\d+", suffix)),
    )


# Registries keep stray tags of the same shape that are not real releases, e.g.
# linuxserver/qbittorrent has `20.04.1` (an Ubuntu base) next to 4.x / 5.x.
# Walking up from the current major, stop at the first jump bigger than this.
MAX_MAJOR_GAP = 3


def _drop_outlier_majors(current_major: int, versions: list[TagVersion]) -> list[TagVersion]:
    reachable = current_major
    for major in sorted({version.numbers[0] for version in versions}):
        if major - reachable > MAX_MAJOR_GAP:
            break
        reachable = max(reachable, major)
    return [version for version in versions if version.numbers[0] <= reachable]


def find_newer(current: str, tags: list[str]) -> tuple[str | None, str | None]:
    """Return (newest tag overall, newest tag in the same major line).

    The second value is only set when it differs from the first. For calendar
    versions (`2025.10.4`) the year is the major.
    """
    base = parse_version(current)
    if base is None:
        return None, None
    newer = [
        version
        for version in (parse_version(tag) for tag in tags)
        if version is not None and version.shape == base.shape and version.sort_key > base.sort_key
    ]
    newer = _drop_outlier_majors(base.numbers[0], newer)
    if not newer:
        return None, None
    newest = max(newer, key=lambda version: version.sort_key)
    same_major = [version for version in newer if version.numbers[0] == base.numbers[0]]
    newest_same_major = (
        max(same_major, key=lambda version: version.sort_key) if same_major else None
    )
    if newest_same_major is None or newest_same_major.tag == newest.tag:
        return newest.tag, None
    return newest.tag, newest_same_major.tag


# --- Registry API ------------------------------------------------------------


# (username, password), or None to stay anonymous.
Credentials = tuple[str, str] | None


def _authorization(client: httpx.Client, challenge: str, auth: Credentials) -> str:
    """Answer a `WWW-Authenticate` challenge: a bearer token from the realm (with
    the credentials when there are some), or Basic auth."""
    scheme, _, params = challenge.partition(" ")
    if scheme.lower() == "basic":
        if auth is None:
            raise RegistryError("registry requires credentials")
        return "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    if scheme.lower() != "bearer":
        raise RegistryError(f"unsupported registry auth: {scheme}")
    fields = dict(_CHALLENGE_RE.findall(params))
    realm = fields.pop("realm", None)
    if not realm:
        raise RegistryError("registry auth challenge has no realm")
    response = client.get(realm, params=fields, auth=auth)
    if response.status_code in (401, 403) and auth is not None:
        raise RegistryError("registry rejected the stored credentials")
    if response.status_code != 200:
        raise RegistryError(f"registry token request failed ({response.status_code})")
    body = response.json()
    token = body.get("token") or body.get("access_token")
    if not token:
        raise RegistryError("registry returned no token")
    return f"Bearer {token}"


def list_tags(registry: str, repository: str, auth: Credentials = None) -> list[str]:
    url: str | None = f"https://{registry}/v2/{repository}/tags/list?n={PAGE_SIZE}"
    headers: dict[str, str] = {}
    tags: list[str] = []
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            for _ in range(MAX_PAGES):
                if url is None:
                    break
                response = client.get(url, headers=headers)
                if response.status_code == 401 and "Authorization" not in headers:
                    challenge = response.headers.get("www-authenticate", "")
                    headers["Authorization"] = _authorization(client, challenge, auth)
                    response = client.get(url, headers=headers)
                if response.status_code in (401, 403):
                    raise RegistryError(
                        "registry rejected the stored credentials"
                        if auth
                        else "registry requires credentials"
                    )
                if response.status_code == 404:
                    raise RegistryError("repository not found in registry")
                response.raise_for_status()
                tags.extend(response.json().get("tags") or [])
                link = _NEXT_LINK_RE.search(response.headers.get("link", ""))
                url = str(response.url.join(link.group(1))) if link else None
            else:
                logger.info(
                    "Stopped listing %s/%s tags after %d pages", registry, repository, MAX_PAGES
                )
    except httpx.HTTPError as exc:
        raise RegistryError(f"registry request failed: {exc}") from exc
    except ValueError as exc:  # bad JSON
        raise RegistryError("registry returned invalid JSON") from exc
    return tags


def newer_tags(image: str, auth: Credentials) -> tuple[str | None, str | None]:
    """(newest, newest same major) for `image`, or (None, None) when its tag is
    not a version. Raises RegistryError when the registry cannot be queried."""
    registry, repository, tag = parse_reference(image)
    if parse_version(tag) is None:
        return None, None
    return find_newer(tag, list_tags(registry, repository, auth))
