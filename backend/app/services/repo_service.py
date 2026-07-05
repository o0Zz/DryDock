from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.core.config import settings
from app.schemas.project import Project, ProjectService

logger = logging.getLogger(__name__)

COMPOSE_FILENAMES = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}


def _project_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


def _parse_services(compose_path: Path) -> list[ProjectService]:
    try:
        with compose_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Failed to parse %s: %s", compose_path, exc)
        return []

    services = data.get("services") or {}
    if not isinstance(services, dict):
        return []

    result: list[ProjectService] = []
    for name, spec in services.items():
        image = None
        if isinstance(spec, dict):
            image = spec.get("image")
        result.append(ProjectService(name=str(name), image=image))
    return result


def _project_from_compose(compose_path: Path, repo_root: Path) -> Project:
    stat = compose_path.stat()
    # Project name = the containing folder name, unless the compose file is at the root
    project_dir = compose_path.parent
    name = project_dir.name if project_dir != repo_root else compose_path.stem
    try:
        rel = compose_path.relative_to(repo_root).as_posix()
    except ValueError:
        rel = compose_path.as_posix()
    return Project(
        id=_project_id(compose_path),
        name=name,
        compose_path=str(compose_path),
        relative_path=rel,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        services=_parse_services(compose_path),
    )


def discover_projects(repo_root: Path | None = None) -> list[Project]:
    root = (repo_root or settings.repo_path).resolve()
    if not root.exists() or not root.is_dir():
        logger.info("Repo path %s does not exist or is not a directory", root)
        return []

    found: dict[Path, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.name not in COMPOSE_FILENAMES:
            continue
        # Only one compose file per directory — prefer docker-compose.yml over alternatives
        existing = found.get(path.parent)
        if existing is None or _filename_priority(path.name) < _filename_priority(existing.name):
            found[path.parent] = path

    projects = [_project_from_compose(p, root) for p in found.values()]
    projects.sort(key=lambda p: p.name.lower())
    return projects


def _filename_priority(name: str) -> int:
    order = {
        "docker-compose.yml": 0,
        "docker-compose.yaml": 1,
        "compose.yml": 2,
        "compose.yaml": 3,
    }
    return order.get(name, 99)
