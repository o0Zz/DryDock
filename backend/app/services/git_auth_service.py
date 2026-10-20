"""Git logins, one per host, for private git repos over https.

Three consumers:

- the update check of a service built from git reads the repo's refs with it
  (git_service);
- a build from a git URL gets it as a BuildKit secret, `GIT_AUTH_HEADER.<host>`
  (compose_service adds the secret to the Compose command);
- commit, push and pull of the repo folder (repo_git_service).

The logins live in `<data>/git/credentials`, in the format of git's own
credential store (`https://user:token@host`, one per line, mode 600). Each
host also gets a file with its `Authorization` header value, because a Compose
build secret reads its value from a file.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from app.core.config import settings

logger = logging.getLogger(__name__)


def _dir() -> Path:
    return settings.data_path / "git"


def _store_path() -> Path:
    return _dir() / "credentials"


def header_path(host: str) -> Path:
    """File holding the `Authorization` header value for a host."""
    # A port's ":" is not allowed in a Windows file name (dev).
    return _dir() / "headers" / host.replace(":", "_")


def normalize(value: str) -> str:
    """The host (with its port) of a repo URL or a bare host name, lower case.

    `git@host:path` (ssh) gives its host too, though only https uses the login.
    """
    value = value.strip()
    if "://" not in value:
        value = value.split("@", 1)[-1].split(":", 1)[0] if "@" in value else value
        value = "https://" + value
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:  # not a URL: a local path remote (C:\repo.git) and the like
        return ""
    return f"{host}:{port}" if port else host


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    # Owner-only: the file holds tokens.
    temp.chmod(0o600)
    temp.replace(path)


def _load() -> dict[str, tuple[str, str]]:
    """Host -> (username, token)."""
    try:
        lines = _store_path().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("Cannot read %s: %s", _store_path(), exc)
        return {}
    logins: dict[str, tuple[str, str]] = {}
    for line in lines:
        parts = urlsplit(line.strip())
        if parts.hostname and parts.username and parts.password:
            logins[normalize(line)] = (unquote(parts.username), unquote(parts.password))
    return logins


def _save(logins: dict[str, tuple[str, str]]) -> None:
    lines = [
        f"https://{quote(username, safe='')}:{quote(token, safe='')}@{host}\n"
        for host, (username, token) in sorted(logins.items())
    ]
    _write_private(_store_path(), "".join(lines))


def _header(username: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{token}".encode()).decode()


def list_hosts() -> list[tuple[str, str]]:
    """(host, username) for every stored login."""
    return sorted((host, username) for host, (username, _) in _load().items())


def credentials(url_or_host: str) -> tuple[str, str] | None:
    """(username, token) for the host of a repo URL, or None to stay anonymous."""
    return _load().get(normalize(url_or_host))


def auth_header(url_or_host: str) -> str | None:
    """`Authorization` header value for the host of a repo URL."""
    login = credentials(url_or_host)
    return _header(*login) if login else None


def set_credentials(url_or_host: str, username: str, token: str) -> str:
    """Store a login, replacing any for the same host. Returns the host."""
    host = normalize(url_or_host)
    logins = _load()
    logins[host] = (username, token)
    _save(logins)
    _write_private(header_path(host), _header(username, token))
    logger.info("Stored git login for %s (%s)", host, username)
    return host


def remove_credentials(url_or_host: str) -> bool:
    host = normalize(url_or_host)
    logins = _load()
    if logins.pop(host, None) is None:
        return False
    _save(logins)
    header_path(host).unlink(missing_ok=True)
    logger.info("Removed git login for %s", host)
    return True


def git_env(url: str) -> dict[str, str]:
    """Environment that makes a git command send the login for `url`'s host.

    Passed through `GIT_CONFIG_*` rather than `-c`, so the token stays out of
    the process list, and rather than a credential file, which the repo owner
    (git runs as that user) could not read.
    """
    header = auth_header(url)
    if header is None or not url.startswith("https://"):
        return {}
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.https://{normalize(url)}/.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: {header}",
    }
