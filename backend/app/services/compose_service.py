from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.core.config import settings
from app.services.repo_service import COMPOSE_FILENAMES

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = {"up", "down", "pull", "restart", "stop"}


class ComposeError(Exception):
    """Raised for compose-service errors that map cleanly to HTTP failures."""


class ComposeExists(ComposeError):
    """Raised when creating a stack in a folder that already has one."""


def read_compose(compose_path: Path) -> str:
    return compose_path.read_text(encoding="utf-8")


def validate_yaml(content: str) -> dict:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ComposeError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ComposeError("Compose file must be a YAML mapping at the root")
    if "services" not in data or not isinstance(data["services"], dict):
        raise ComposeError("Compose file must contain a 'services' mapping")
    return data


def backup_compose(project_id: str, compose_path: Path) -> Path:
    backup_dir = settings.backups_path / project_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{ts}{compose_path.suffix}"
    shutil.copy2(compose_path, backup_path)
    logger.info("Backed up %s to %s", compose_path, backup_path)
    return backup_path


def write_compose(project_id: str, compose_path: Path, content: str) -> Path:
    validate_yaml(content)
    backup = backup_compose(project_id, compose_path)
    compose_path.write_text(content, encoding="utf-8")
    return backup


def create_compose(name: str, content: str) -> Path:
    """Create `<repo>/<name>/docker-compose.yml`. `name` must already be a safe
    single path segment (the API schema enforces it)."""
    validate_yaml(content)
    project_dir = settings.repo_path / name
    if any((project_dir / f).exists() for f in COMPOSE_FILENAMES):
        raise ComposeExists(f"A compose file already exists in '{name}/'")
    project_dir.mkdir(parents=True, exist_ok=True)
    compose_path = project_dir / "docker-compose.yml"
    compose_path.write_text(content, encoding="utf-8")
    logger.info("Created new stack %s", compose_path)
    return compose_path


def run_action(compose_path: Path, action: str, *, detached: bool = True) -> dict:
    if action not in ALLOWED_ACTIONS:
        raise ComposeError(f"Unsupported action: {action}")

    cmd = ["docker", "compose", "-f", str(compose_path), action]
    if action == "up" and detached:
        cmd.append("-d")

    logger.info("Running: %s", " ".join(cmd))
    try:
        proc = subprocess.run(  # noqa: S603 — args list, no shell
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=compose_path.parent,
        )
    except FileNotFoundError as exc:
        raise ComposeError("`docker` CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ComposeError(f"`docker compose {action}` timed out after 300s") from exc

    return {
        "action": action,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def stream_logs(compose_path: Path, *, tail: int = 200) -> subprocess.Popen[bytes]:
    """Follow the aggregated logs of a Compose project.

    Returns the running process; the caller owns it and must terminate it when
    the client goes away.
    """
    cmd = [
        "docker",
        "compose",
        "-f",
        str(compose_path),
        "logs",
        "--follow",
        "--no-color",
        "--tail",
        str(tail),
    ]
    logger.info("Streaming: %s", " ".join(cmd))
    try:
        return subprocess.Popen(  # noqa: S603 - args list, no shell
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=compose_path.parent,
        )
    except FileNotFoundError as exc:
        raise ComposeError("`docker` CLI not found on PATH") from exc
