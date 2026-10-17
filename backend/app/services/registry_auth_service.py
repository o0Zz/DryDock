"""Registry credentials, kept in a Docker client config that DryDock owns.

The file is a standard `config.json` (`auths` with base64 `user:password`) at
`<data>/docker/config.json`. That one file serves every consumer:

- `docker compose` (pulls) and `trivy` (remote image fallback) read it through
  `DOCKER_CONFIG`, see `subprocess_env()`;
- the digest check passes `auth_config()` to the daemon;
- the tag check in registry_service logs in to the token endpoint with it.

Credential helpers (`credsStore`) are not supported: the values must be inline.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.registry_service import DOCKER_HUB

logger = logging.getLogger(__name__)

# The key `docker login` writes for Docker Hub.
DOCKER_HUB_KEY = "https://index.docker.io/v1/"
_HUB_ALIASES = {DOCKER_HUB, "docker.io", "index.docker.io", DOCKER_HUB_KEY}


def config_dir() -> Path:
    return settings.data_path / "docker"


def _config_path() -> Path:
    return config_dir() / "config.json"


def normalize(registry: str) -> str:
    """Normalise a registry name to its `auths` key: Docker Hub's URL, else the host."""
    registry = registry.strip().lower()
    for prefix in ("https://", "http://"):
        registry = registry.removeprefix(prefix)
    registry = registry.rstrip("/")
    if registry in _HUB_ALIASES or registry.startswith("index.docker.io/"):
        return DOCKER_HUB_KEY
    return registry


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Cannot read %s: %s", _config_path(), exc)
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Owner-only, like `docker login` leaves it: the file holds passwords.
    temp.chmod(0o600)
    temp.replace(path)


def _decode(entry: dict[str, Any]) -> tuple[str, str] | None:
    if entry.get("username") and entry.get("password"):
        return entry["username"], entry["password"]
    try:
        username, _, password = base64.b64decode(entry.get("auth") or "").decode().partition(":")
    except ValueError:
        return None
    return (username, password) if username and password else None


def list_registries() -> list[tuple[str, str]]:
    """(registry key, username) for every registry with stored credentials."""
    auths = _load().get("auths") or {}
    entries = ((key, _decode(entry)) for key, entry in auths.items() if isinstance(entry, dict))
    return sorted((key, auth[0]) for key, auth in entries if auth)


def credentials(registry: str) -> tuple[str, str] | None:
    """(username, password) for a registry, or None to stay anonymous."""
    entry = (_load().get("auths") or {}).get(normalize(registry))
    return _decode(entry) if isinstance(entry, dict) else None


def auth_config(registry: str) -> dict[str, str] | None:
    """Credentials in the shape docker-py's `auth_config` arguments take."""
    found = credentials(registry)
    return {"username": found[0], "password": found[1]} if found else None


def set_credentials(registry: str, username: str, password: str) -> str:
    """Store credentials, replacing any for the same registry. Returns the key used."""
    key = normalize(registry)
    data = _load()
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    data.setdefault("auths", {})[key] = {"auth": token}
    _save(data)
    logger.info("Stored registry credentials for %s (%s)", key, username)
    return key


def remove_credentials(registry: str) -> bool:
    data = _load()
    removed = (data.get("auths") or {}).pop(normalize(registry), None) is not None
    if removed:
        _save(data)
        logger.info("Removed registry credentials for %s", normalize(registry))
    return removed


def subprocess_env() -> dict[str, str] | None:
    """Environment for `docker` and `trivy` subprocesses: points them at this config.

    None (inherit) until credentials exist, so a fresh install behaves exactly
    like the plain CLI. Compose finds its plugin in the system plugin folder,
    which does not depend on DOCKER_CONFIG.
    """
    if not _config_path().is_file():
        return None
    return {**os.environ, "DOCKER_CONFIG": str(config_dir())}
