from __future__ import annotations

import logging
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.core.config import settings
from app.services import host_path_service, registry_auth_service
from app.services.repo_service import COMPOSE_FILENAMES

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = {"up", "down", "pull", "reload", "stop"}


class ComposeError(Exception):
    """Raised for compose-service errors that map cleanly to HTTP failures."""


class ComposeExists(ComposeError):
    """Raised when creating a stack in a folder that already has one."""


def read_compose(compose_path: Path) -> str:
    return compose_path.read_text(encoding="utf-8")


def _validate_yaml(content: str) -> None:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ComposeError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ComposeError("Compose file must be a YAML mapping at the root")
    if "services" not in data or not isinstance(data["services"], dict):
        raise ComposeError("Compose file must contain a 'services' mapping")


def _backup(project_id: str, path: Path, extension: str) -> Path:
    backup_dir = settings.backups_path / project_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{stamp}{extension}"
    shutil.copy2(path, backup_path)
    logger.info("Backed up %s to %s", path, backup_path)
    return backup_path


def write_compose(project_id: str, compose_path: Path, content: str) -> Path:
    _validate_yaml(content)
    backup = _backup(project_id, compose_path, compose_path.suffix)
    compose_path.write_text(content, encoding="utf-8")
    return backup


# --- .env ----------------------------------------------------------------------

# `KEY=value`, `export KEY=value`, Compose's `KEY: value`, or a bare `KEY`.
_ENV_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_.-]*\s*(?:[=:](?P<value>.*))?$"
)


def env_path(compose_path: Path) -> Path:
    """The `.env` Compose reads for this file: the one in the project folder.
    Stacks that share a folder share it too."""
    return compose_path.parent / ".env"


def read_env(compose_path: Path) -> str | None:
    path = env_path(compose_path)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _closes(value: str, quote: str) -> bool:
    """Whether a quoted value that opened earlier ends in `value`."""
    index = 0
    while (index := value.find(quote, index)) != -1:
        if quote == "'" or value[index - 1 : index] != "\\":
            return True
        index += 1
    return False


def _validate_env(content: str) -> None:
    """Check the dotenv syntax Compose accepts, so a typo fails here, not on the next `up`."""
    open_quote: tuple[str, int] | None = None
    for number, line in enumerate(content.splitlines(), start=1):
        if open_quote:
            if _closes(line, open_quote[0]):
                open_quote = None
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_ASSIGNMENT.match(line)
        if match is None:
            raise ComposeError(f"Line {number}: expected KEY=value, got {stripped[:40]!r}")
        value = (match["value"] or "").strip()
        # Double and single quotes may span lines; the value ends at the matching quote.
        if value[:1] in ("'", '"') and not _closes(value[1:], value[0]):
            open_quote = (value[0], number)
    if open_quote:
        raise ComposeError(f"Line {open_quote[1]}: quoted value is never closed")


def write_env(project_id: str, compose_path: Path, content: str) -> Path | None:
    """Validate, back up the current file if there is one, then write. Returns the backup."""
    _validate_env(content)
    path = env_path(compose_path)
    backup = _backup(project_id, path, ".env") if path.is_file() else None
    path.write_text(content, encoding="utf-8")
    return backup


def create_compose(name: str, content: str) -> Path:
    """Create `<repo>/<name>/docker-compose.yml`. `name` must already be a safe
    single path segment (the API schema enforces it)."""
    _validate_yaml(content)
    project_dir = settings.repo_path / name
    if any((project_dir / filename).exists() for filename in COMPOSE_FILENAMES):
        raise ComposeExists(f"A compose file already exists in '{name}/'")
    project_dir.mkdir(parents=True, exist_ok=True)
    compose_path = project_dir / "docker-compose.yml"
    compose_path.write_text(content, encoding="utf-8")
    logger.info("Created new stack %s", compose_path)
    return compose_path


def override_path(compose_path: Path) -> Path | None:
    """The `<stem>.override.y(a)ml` next to a Compose file, if any. Passing -f turns
    off Compose's own override merge, so it has to be added back explicitly."""
    for suffix in (".yml", ".yaml"):
        candidate = compose_path.with_name(f"{compose_path.stem}.override{suffix}")
        if candidate.is_file():
            return candidate
    return None


def _command(compose_path: Path, args: list[str], project_name: str | None = None) -> list[str]:
    command = ["docker", "compose", "-f", str(host_path_service.to_host(compose_path))]
    override = override_path(compose_path)
    if override is not None:
        command += ["-f", str(host_path_service.to_host(override))]
    if project_name:
        command += ["-p", project_name]
    return command + args


def _compose(
    compose_path: Path,
    args: list[str],
    *,
    project_name: str | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    # Through the host-path alias, so relative bind mounts resolve on the host.
    command = _command(compose_path, args, project_name)
    logger.info("Running: %s", " ".join(command))
    try:
        return subprocess.run(  # noqa: S603 — args list, no shell
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=host_path_service.to_host(compose_path).parent,
            # Registry credentials for pulls.
            env=registry_auth_service.subprocess_env(),
        )
    except FileNotFoundError as exc:
        raise ComposeError("`docker` CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ComposeError(f"`docker compose {args[0]}` timed out after {timeout}s") from exc


# Pulling a large image on a Pi over a slow link easily takes several minutes.
PULL_TIMEOUT = 1800


def run_action(compose_path: Path, action: str, *, project_name: str | None = None) -> dict:
    if action not in ALLOWED_ACTIONS:
        raise ComposeError(f"Unsupported action: {action}")

    # `reload` applies an edited Compose file. `docker compose restart` would not:
    # it restarts the existing containers with the config they were created with.
    # `up` after the stop recreates the services whose config changed.
    if action == "reload":
        steps = [["stop"], ["up", "-d"]]
    elif action == "up":
        steps = [["up", "-d"]]
    else:
        steps = [[action]]

    stdout: list[str] = []
    stderr: list[str] = []
    exit_code = 0
    for args in steps:
        # `up` pulls missing images too, so both can take as long as a pull.
        timeout = PULL_TIMEOUT if args[0] in ("up", "pull") else 300
        result = _compose(compose_path, args, project_name=project_name, timeout=timeout)
        stdout.append(result.stdout)
        stderr.append(result.stderr)
        exit_code = result.returncode
        if exit_code != 0:
            break

    return {
        "action": action,
        "exit_code": exit_code,
        "stdout": "".join(stdout),
        "stderr": "".join(stderr),
    }


def _check(result: subprocess.CompletedProcess[str], step: str) -> None:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-1000:]
        raise ComposeError(f"`docker compose {step}` failed (exit {result.returncode}): {detail}")


def down(
    compose_path: Path, *, remove_volumes: bool = False, project_name: str | None = None
) -> str:
    """`docker compose down`, with `-v` to remove the stack's named volumes too.
    Returns the command output; raises ComposeError when it fails."""
    args = ["down", "--remove-orphans", *(["--volumes"] if remove_volumes else [])]
    result = _compose(compose_path, args, project_name=project_name)
    _check(result, "down")
    # docker compose writes its progress to stderr, so keep both streams.
    return "\n".join(text for text in (result.stdout, result.stderr) if text)


def pull_service(compose_path: Path, service: str, *, project_name: str | None = None) -> None:
    """Pull the image of one service."""
    result = _compose(
        compose_path, ["pull", service], project_name=project_name, timeout=PULL_TIMEOUT
    )
    _check(result, "pull")


def recreate_service(compose_path: Path, service: str, *, project_name: str | None = None) -> None:
    """Recreate one service on its current image, leaving the rest of the stack alone."""
    result = _compose(compose_path, ["up", "-d", "--no-deps", service], project_name=project_name)
    _check(result, "up")


def stream_logs(
    compose_path: Path, *, tail: int = 200, project_name: str | None = None
) -> subprocess.Popen[bytes]:
    """Follow the aggregated logs of a Compose project.

    Returns the running process; the caller owns it and must terminate it when
    the client goes away.
    """
    command = _command(
        compose_path, ["logs", "--follow", "--no-color", "--tail", str(tail)], project_name
    )
    logger.info("Streaming: %s", " ".join(command))
    try:
        return subprocess.Popen(  # noqa: S603 - args list, no shell
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=host_path_service.to_host(compose_path).parent,
        )
    except FileNotFoundError as exc:
        raise ComposeError("`docker` CLI not found on PATH") from exc
