from fastapi import APIRouter, HTTPException

from app.schemas.container import Container
from app.services import docker_service

router = APIRouter(prefix="/api/containers", tags=["containers"])


@router.get("", response_model=list[Container])
def list_containers() -> list[Container]:
    try:
        return docker_service.list_containers()
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


@router.get("/{container_id}", response_model=Container)
def get_container(container_id: str) -> Container:
    try:
        return docker_service.get_container(container_id)
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
