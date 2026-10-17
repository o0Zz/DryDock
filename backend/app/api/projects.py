from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import require_admin
from app.models.job import Job, JobKind
from app.schemas.compose import (
    ComposeContent,
    ComposeWriteResponse,
    EnvContent,
    EnvWriteResponse,
)
from app.schemas.job import JobRead
from app.schemas.project import Project, ProjectCreate, StackChangeAccepted, StackRename
from app.services import compose_service, job_service, repo_service, stack_service, tasks

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _find_project(project_id: str) -> Project:
    project = repo_service.find_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("", response_model=list[Project])
def list_projects() -> list[Project]:
    return repo_service.attach_containers(repo_service.discover_projects())


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate) -> Project:
    compose_path = compose_service.create_compose(body.name, body.content)
    return repo_service.project_from_path(compose_path.resolve())


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    return repo_service.attach_containers([_find_project(project_id)])[0]


@router.get("/{project_id}/compose", response_model=ComposeContent)
def get_compose(project_id: str) -> ComposeContent:
    project = _find_project(project_id)
    return ComposeContent(content=compose_service.read_compose(Path(project.compose_path)))


@router.put("/{project_id}/compose", response_model=ComposeWriteResponse)
def put_compose(project_id: str, body: ComposeContent) -> ComposeWriteResponse:
    project = _find_project(project_id)
    backup = compose_service.write_compose(project.id, Path(project.compose_path), body.content)
    return ComposeWriteResponse(backup_path=str(backup))


# .env files usually hold the stack's secrets, so they are admin only.
@router.get("/{project_id}/env", response_model=EnvContent, dependencies=[Depends(require_admin)])
def get_env(project_id: str) -> EnvContent:
    content = compose_service.read_env(Path(_find_project(project_id).compose_path))
    return EnvContent(content=content or "", exists=content is not None)


@router.put(
    "/{project_id}/env", response_model=EnvWriteResponse, dependencies=[Depends(require_admin)]
)
def put_env(project_id: str, body: EnvContent) -> EnvWriteResponse:
    project = _find_project(project_id)
    backup = compose_service.write_env(project.id, Path(project.compose_path), body.content)
    return EnvWriteResponse(backup_path=str(backup) if backup else None)


@router.delete("/{project_id}", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def delete_project(project_id: str, remove_volumes: bool = Query(default=False)) -> Job:
    """Queue `down` (with `-v` on request), a backup, then removal of the stack's files."""
    project = repo_service.attach_containers([_find_project(project_id)])[0]
    return job_service.submit(
        JobKind.STACK_CHANGE,
        f"Delete {project.name}",
        tasks.stack_delete_runner(
            project,
            project_name=repo_service.compose_project_name(project),
            stop=bool(project.containers),
            remove_volumes=remove_volumes,
        ),
    )


# Declared before /{project_id}/{action} so "rename" is not taken as an action.
@router.post(
    "/{project_id}/rename", response_model=StackChangeAccepted, status_code=status.HTTP_202_ACCEPTED
)
def rename_project(project_id: str, body: StackRename) -> StackChangeAccepted:
    """Queue `down`, then a move to the new name. The stack is left down."""
    project = repo_service.attach_containers([_find_project(project_id)])[0]
    new_id = stack_service.new_project_id(project, body.name)
    job = job_service.submit(
        JobKind.STACK_CHANGE,
        f"Rename {project.name} to {body.name}",
        tasks.stack_rename_runner(
            project,
            body.name,
            project_name=repo_service.compose_project_name(project),
            stop=bool(project.containers),
        ),
    )
    return StackChangeAccepted(job=JobRead.model_validate(job), project_id=new_id)


@router.post(
    "/{project_id}/duplicate",
    response_model=StackChangeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def duplicate_project(project_id: str, body: StackRename) -> StackChangeAccepted:
    """Queue a copy under the new name. Nothing is started."""
    project = _find_project(project_id)
    new_id = stack_service.new_project_id(project, body.name)
    job = job_service.submit(
        JobKind.STACK_CHANGE,
        f"Duplicate {project.name} as {body.name}",
        tasks.stack_duplicate_runner(project, body.name),
    )
    return StackChangeAccepted(job=JobRead.model_validate(job), project_id=new_id)


@router.post("/{project_id}/{action}", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def run_action(project_id: str, action: str) -> Job:
    """Queue `docker compose <action>`; a pull or first `up` can take minutes."""
    if action not in compose_service.ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")
    project = repo_service.attach_containers([_find_project(project_id)])[0]
    return job_service.submit(
        JobKind.PROJECT_ACTION,
        f"{action.capitalize()} {project.name}",
        tasks.project_action_runner(
            Path(project.compose_path),
            action,
            project_name=repo_service.compose_project_name(project),
        ),
    )
