from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.core.config import settings
from app.schemas.container import Container
from app.schemas.project import Project, ProjectService
from app.services import docker_service

logger = logging.getLogger(__name__)

# In order of preference when one folder holds several.
COMPOSE_FILENAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
YAML_SUFFIXES = {".yml", ".yaml"}


def _project_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


def _load_yaml(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return None


def _looks_like_compose(path: Path) -> bool:
    """Arbitrary YAML (e.g. `adguard.yml`) counts as a Compose file only if it
    has a top-level `services` mapping."""
    data = _load_yaml(path)
    return isinstance(data, dict) and isinstance(data.get("services"), dict)


def _parse_services(compose_path: Path) -> list[ProjectService]:
    data = _load_yaml(compose_path)
    services = data.get("services") if isinstance(data, dict) else None
    if not isinstance(services, dict):
        return []
    return [
        ProjectService(name=str(name), image=spec.get("image") if isinstance(spec, dict) else None)
        for name, spec in services.items()
    ]


def _project_from_compose(compose_path: Path, repo_root: Path) -> Project:
    stat = compose_path.stat()
    # Project name = the containing folder name for a canonical compose file in a
    # subfolder; otherwise (repo root, or a freely named `foo.yml`) the file stem
    project_dir = compose_path.parent
    canonical = compose_path.name in COMPOSE_FILENAMES
    name = project_dir.name if canonical and project_dir != repo_root else compose_path.stem
    try:
        rel = compose_path.relative_to(repo_root).as_posix()
    except ValueError:
        rel = compose_path.as_posix()
    return Project(
        id=_project_id(compose_path),
        name=name,
        compose_path=str(compose_path),
        relative_path=rel,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        services=_parse_services(compose_path),
    )


def project_from_path(compose_path: Path) -> Project:
    return _project_from_compose(compose_path, settings.repo_path.resolve())


def discover_projects() -> list[Project]:
    root = settings.repo_path.resolve()
    if not root.exists() or not root.is_dir():
        logger.info("Repo path %s does not exist or is not a directory", root)
        return []

    canonical: dict[Path, Path] = {}
    others: list[Path] = []
    for path in root.rglob("*"):
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts) or not path.is_file():
            continue
        if path.name in COMPOSE_FILENAMES:
            # One canonical compose file per directory — prefer docker-compose.yml
            existing = canonical.get(path.parent)
            if existing is None or (
                COMPOSE_FILENAMES.index(path.name) < COMPOSE_FILENAMES.index(existing.name)
            ):
                canonical[path.parent] = path
        elif (
            path.suffix.lower() in YAML_SUFFIXES
            and not path.stem.endswith(".override")
            and _looks_like_compose(path)
        ):
            others.append(path)

    projects = [_project_from_compose(p, root) for p in [*canonical.values(), *others]]
    projects.sort(key=lambda p: p.name.lower())
    return projects


def find_project(project_id: str) -> Project | None:
    return next((p for p in discover_projects() if p.id == project_id), None)


def referenced_images() -> list[str]:
    """Distinct images named by any service across every discovered project."""
    images = {
        service.image
        for project in discover_projects()
        for service in project.services
        if service.image
    }
    return sorted(images)


def _normalise_name(name: str) -> str:
    """Match Docker's own project-name mangling (lowercase, punctuation dropped)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _normalise_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/").lower()


def attach_containers(projects: list[Project]) -> list[Project]:
    """Fill in each project's running containers. Best-effort: a dead daemon
    just means the stack state is unknown, not that the project list fails."""
    try:
        containers = docker_service.list_containers(all_states=True)
    except docker_service.DockerUnavailable:
        return projects

    by_file: dict[str, list[Container]] = defaultdict(list)
    by_name: dict[str, list[Container]] = defaultdict(list)
    for container in containers:
        if container.compose_project:
            by_name[_normalise_name(container.compose_project)].append(container)
        for raw in (container.compose_config_files or "").split(","):
            if raw.strip():
                by_file[_normalise_path(raw.strip())].append(container)

    for project in projects:
        # The config-files label is exact; a label ending in the repo-relative path
        # catches stacks brought up from the host checkout (different mount root);
        # the project name is the last fallback.
        rel_suffix = "/" + _normalise_path(project.relative_path)
        project.containers = (
            by_file.get(_normalise_path(project.compose_path))
            or [c for path, cs in by_file.items() if path.endswith(rel_suffix) for c in cs]
            or by_name.get(_normalise_name(project.name), [])
        )
    return projects


def project_for_container(container_id: str) -> Project | None:
    """The repo project a container was deployed from, if any."""
    for project in attach_containers(discover_projects()):
        if any(c.id == container_id for c in project.containers):
            return project
    return None
