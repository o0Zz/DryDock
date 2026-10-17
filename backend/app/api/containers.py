from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.models.job import Job, JobKind
from app.models.user import User
from app.schemas.container import Container, ContainerDetail, ContainerStats
from app.schemas.job import JobRead
from app.services import docker_service, job_service, repo_service, tasks

router = APIRouter(prefix="/api/containers", tags=["containers"])


@router.get("", response_model=list[Container])
def list_containers() -> list[Container]:
    return docker_service.list_containers()


# Declared before /{container_id} so "stats" is not taken as a container id.
@router.get("/stats", response_model=list[ContainerStats])
def container_stats() -> list[ContainerStats]:
    return docker_service.running_stats()


@router.get("/{container_id}", response_model=Container)
def get_container(container_id: str) -> Container:
    return docker_service.get_container(container_id)


@router.get("/{container_id}/inspect", response_model=ContainerDetail)
def inspect_container(
    container_id: str, user: User = Depends(get_current_user)
) -> ContainerDetail:
    return docker_service.get_container_detail(container_id, privileged=user.is_admin)


@router.delete("/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_container(container_id: str) -> None:
    docker_service.remove_container(container_id)


# Declared before /{container_id}/{action} so "update" is not taken as an action.
@router.post(
    "/{container_id}/update", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED
)
def update_container(container_id: str) -> Job:
    """Queue a pull of the container's image and a recreate of its Compose service.

    Only for containers deployed from a Compose file in the repo: anything else
    would have to be recreated by hand with its original `docker run` options.
    """
    container = docker_service.get_container(container_id)
    if not container.compose_service:
        raise HTTPException(
            status_code=409, detail=f"{container.name} is not managed by Docker Compose"
        )
    project = repo_service.project_for_container(container.id)
    if project is None:
        raise HTTPException(
            status_code=409,
            detail=f"No Compose file in the repo matches {container.name}",
        )
    return job_service.submit(
        JobKind.CONTAINER_UPDATE,
        f"Update {container.name}",
        tasks.container_update_runner(
            Path(project.compose_path),
            container.compose_service,
            container.image,
            project_name=container.compose_project,
        ),
    )


@router.post("/{container_id}/{action}")
def container_action(container_id: str, action: str) -> dict[str, str]:
    try:
        docker_service.perform_action(container_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "action": action}
