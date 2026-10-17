from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.container import Container, ContainerDetail, ContainerStats
from app.services import docker_service

router = APIRouter(prefix="/api/containers", tags=["containers"])


@router.get("", response_model=list[Container])
def list_containers() -> list[Container]:
    try:
        return docker_service.list_containers()
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


# Declared before /{container_id} so "stats" is not taken as a container id.
@router.get("/stats", response_model=list[ContainerStats])
def container_stats() -> list[ContainerStats]:
    try:
        return docker_service.running_stats()
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


@router.get("/{container_id}", response_model=Container)
def get_container(container_id: str) -> Container:
    try:
        return docker_service.get_container(container_id)
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{container_id}/inspect", response_model=ContainerDetail)
def inspect_container(
    container_id: str, user: User = Depends(get_current_user)
) -> ContainerDetail:
    try:
        return docker_service.get_container_detail(container_id, privileged=user.is_admin)
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_container(container_id: str) -> None:
    try:
        docker_service.remove_container(container_id)
    except docker_service.ContainerRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{container_id}/{action}")
def container_action(container_id: str, action: str) -> dict[str, str]:
    try:
        docker_service.perform_action(container_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "action": action}
