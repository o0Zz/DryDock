from fastapi import APIRouter, Query, status

from app.models.job import Job, JobKind
from app.schemas.job import JobRead
from app.schemas.volume import Volume, VolumeCreate
from app.services import docker_service, job_service, tasks

router = APIRouter(prefix="/api/volumes", tags=["volumes"])


@router.get("", response_model=list[Volume])
def list_volumes() -> list[Volume]:
    return docker_service.list_volumes()


@router.post("/prune", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def prune_volumes() -> Job:
    return job_service.submit(
        JobKind.VOLUME_PRUNE, "Prune unused volumes", tasks.volume_prune_runner()
    )


@router.post("", response_model=Volume, status_code=status.HTTP_201_CREATED)
def create_volume(body: VolumeCreate) -> Volume:
    return docker_service.create_volume(body.name, body.driver, body.labels)


@router.get("/{name}", response_model=Volume)
def get_volume(name: str) -> Volume:
    return docker_service.get_volume(name)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_volume(name: str, force: bool = Query(default=False)) -> None:
    docker_service.remove_volume(name, force=force)
