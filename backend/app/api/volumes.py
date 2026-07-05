from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.volume import PruneResult, Volume, VolumeCreate
from app.services import docker_service

router = APIRouter(prefix="/api/volumes", tags=["volumes"])


@router.get("", response_model=list[Volume])
def list_volumes() -> list[Volume]:
    try:
        return docker_service.list_volumes()
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


@router.post("/prune", response_model=PruneResult)
def prune_volumes() -> PruneResult:
    try:
        return docker_service.prune_volumes()
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


@router.post("", response_model=Volume, status_code=status.HTTP_201_CREATED)
def create_volume(body: VolumeCreate) -> Volume:
    try:
        return docker_service.create_volume(body.name, body.driver, body.labels)
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


@router.get("/{name}", response_model=Volume)
def get_volume(name: str) -> Volume:
    try:
        return docker_service.get_volume(name)
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_volume(name: str, force: bool = Query(default=False)) -> None:
    try:
        docker_service.remove_volume(name, force=force)
    except docker_service.VolumeInUse as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
