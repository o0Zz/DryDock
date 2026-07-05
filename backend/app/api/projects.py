from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.schemas.compose import ActionResult, ComposeContent, ComposeWriteResponse
from app.schemas.project import Project
from app.services import compose_service, repo_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _find_project(project_id: str) -> Project:
    for project in repo_service.discover_projects():
        if project.id == project_id:
            return project
    raise HTTPException(status_code=404, detail="Project not found")


@router.get("", response_model=list[Project])
def list_projects() -> list[Project]:
    return repo_service.discover_projects()


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    return _find_project(project_id)


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
