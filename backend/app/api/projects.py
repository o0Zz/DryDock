import re
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.schemas.compose import ActionResult, ComposeContent, ComposeWriteResponse
from app.schemas.container import Container
from app.schemas.project import Project, ProjectCreate
from app.services import compose_service, docker_service, repo_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _normalise_name(name: str) -> str:
    """Match Docker's own project-name mangling (lowercase, punctuation dropped)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _normalise_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/").lower()


def _attach_containers(projects: list[Project]) -> list[Project]:
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


def _find_project(project_id: str) -> Project:
    for project in repo_service.discover_projects():
        if project.id == project_id:
            return project
    raise HTTPException(status_code=404, detail="Project not found")


@router.get("", response_model=list[Project])
def list_projects() -> list[Project]:
    return _attach_containers(repo_service.discover_projects())


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate) -> Project:
    try:
        compose_path = compose_service.create_compose(body.name, body.content)
    except compose_service.ComposeExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except compose_service.ComposeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return repo_service.project_from_path(compose_path.resolve())


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    return _attach_containers([_find_project(project_id)])[0]


@router.get("/{project_id}/compose", response_model=ComposeContent)
def get_compose(project_id: str) -> ComposeContent:
    project = _find_project(project_id)
    return ComposeContent(content=compose_service.read_compose(Path(project.compose_path)))


@router.put("/{project_id}/compose", response_model=ComposeWriteResponse)
def put_compose(project_id: str, body: ComposeContent) -> ComposeWriteResponse:
    project = _find_project(project_id)
    try:
        backup = compose_service.write_compose(
            project.id, Path(project.compose_path), body.content
        )
    except compose_service.ComposeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ComposeWriteResponse(backup_path=str(backup))


@router.post("/{project_id}/{action}", response_model=ActionResult)
def run_action(project_id: str, action: str) -> ActionResult:
    project = _find_project(project_id)
    try:
        result = compose_service.run_action(Path(project.compose_path), action)
    except compose_service.ComposeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResult(**result)
