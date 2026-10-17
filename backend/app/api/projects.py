from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.models.job import Job, JobKind
from app.schemas.compose import ComposeContent, ComposeWriteResponse
from app.schemas.job import JobRead
from app.schemas.project import Project, ProjectCreate
from app.services import compose_service, job_service, repo_service, tasks

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


@router.post(
    "/{project_id}/{action}", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED
)
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
