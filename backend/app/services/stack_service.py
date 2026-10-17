"""Delete, rename and duplicate stacks: the file side of it.

A stack either owns its folder (not the repo root, and no other stack in it or
below it), or shares the folder with other stacks or sits in the repo root.

- Owned folder: the whole folder is the stack. Delete archives and removes it,
  rename moves it, duplicate copies it, data folders and `.env` included.
- Shared folder: only the Compose file and its `.override` file belong to the
  stack. The rest of the folder, `.env` included, is left alone.

The new name is always the new Compose project name: a canonical file
(`docker-compose.yml`) takes it from its folder, any other file from its stem.
"""

from __future__ import annotations

import logging
import shutil
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.schemas.project import Project
from app.services import compose_service, repo_service

logger = logging.getLogger(__name__)


@dataclass
class StackLayout:
    compose_path: Path
    # The Compose file, then its override when there is one.
    files: list[Path]
    # Set when the stack owns its folder.
    folder: Path | None


def layout(project: Project) -> StackLayout:
    compose_path = Path(project.compose_path)
    folder = compose_path.parent
    override = compose_service.override_path(compose_path)
    files = [compose_path, *([override] if override else [])]
    root = settings.repo_path.resolve()
    shared = folder.resolve() == root or any(
        other.id != project.id and Path(other.compose_path).is_relative_to(folder)
        for other in repo_service.discover_projects()
    )
    return StackLayout(compose_path=compose_path, files=files, folder=None if shared else folder)


def _renamed(path: Path, compose_path: Path, new_stem: str) -> str:
    """New file name for the Compose file or its override, for a stack stem `new_stem`."""
    if path == compose_path:
        return f"{new_stem}{path.suffix}"
    return f"{new_stem}.override{path.suffix}"


def target_paths(stack: StackLayout, new_name: str) -> dict[Path, Path]:
    """Where each path of the stack goes for `new_name`: the folder (owned folder), or
    each file. The Compose file is always in the result."""
    compose_path = stack.compose_path
    canonical = compose_path.name in repo_service.COMPOSE_FILENAMES
    if stack.folder is not None:
        new_folder = stack.folder.parent / new_name
        moves = {stack.folder: new_folder}
        for path in stack.files:
            name = path.name if canonical else _renamed(path, compose_path, new_name)
            moves[path] = new_folder / name
        return moves
    return {path: path.parent / _renamed(path, compose_path, new_name) for path in stack.files}


def check_new_name(project: Project, new_name: str) -> Path:
    """Refuse a name another stack has, or paths that exist. Returns the new Compose path."""
    if any(other.name.lower() == new_name.lower() for other in repo_service.discover_projects()):
        raise compose_service.ComposeExists(f"A stack named '{new_name}' already exists")
    moves = target_paths(layout(project), new_name)
    taken = [target for target in moves.values() if target.exists()]
    if taken:
        raise compose_service.ComposeExists(f"{taken[0].name} already exists")
    return moves[Path(project.compose_path)]


def new_project_id(project: Project, new_name: str) -> str:
    return repo_service.project_id(check_new_name(project, new_name))


# --- Changes, run from background jobs ------------------------------------------------


def _backup_dir(project_id: str) -> Path:
    backup_dir = settings.backups_path / project_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _stamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def delete(project: Project) -> str:
    """Back up, then remove the stack's files. Returns where the backup went."""
    stack = layout(project)
    backup_dir = _backup_dir(project.id)
    if stack.folder is not None:
        archive = backup_dir / f"{_stamp()}-stack.tar.gz"
        # Low compression: the folder can hold data, and this may run on a Pi.
        with tarfile.open(archive, "w:gz", compresslevel=1) as tar:
            tar.add(stack.folder, arcname=stack.folder.name)
        shutil.rmtree(stack.folder)
        logger.info("Deleted stack folder %s (backup %s)", stack.folder, archive)
        return str(archive)
    stamp = _stamp()
    for path in stack.files:
        shutil.copy2(path, backup_dir / f"{stamp}-{path.name}")
        path.unlink()
    logger.info("Deleted %s (backup in %s)", ", ".join(map(str, stack.files)), backup_dir)
    return str(backup_dir)


def rename(project: Project, new_name: str) -> Path:
    """Move the stack's folder or files to `new_name`. Returns the new Compose path."""
    target = check_new_name(project, new_name)
    stack = layout(project)
    moves = target_paths(stack, new_name)
    if stack.folder is not None:
        new_folder = moves.pop(stack.folder)
        shutil.move(stack.folder, new_folder)
        # The files now live in the new folder; rename them there if their name changes.
        moves = {new_folder / old.name: new for old, new in moves.items()}
    for old, new in moves.items():
        if old != new:
            old.rename(new)
    logger.info("Renamed stack %s to %s", project.name, new_name)
    return target


def duplicate(project: Project, new_name: str) -> Path:
    """Copy the stack's folder or files under `new_name`. Returns the new Compose path."""
    target = check_new_name(project, new_name)
    stack = layout(project)
    moves = target_paths(stack, new_name)
    if stack.folder is not None:
        new_folder = moves.pop(stack.folder)
        shutil.copytree(stack.folder, new_folder, symlinks=True)
        moves = {new_folder / old.name: new for old, new in moves.items()}
        for old, new in moves.items():
            if old != new:
                old.rename(new)
    else:
        for old, new in moves.items():
            shutil.copy2(old, new)
    logger.info("Duplicated stack %s as %s", project.name, new_name)
    return target
