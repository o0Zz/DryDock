from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.core.security import require_admin
from app.models.job import Job, JobKind
from app.schemas.job import JobRead
from app.schemas.volume import Volume, VolumeCreate, VolumeListing
from app.services import docker_service, job_service, tasks, volume_files_service

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


# Volume files can hold secrets (configs, databases), so reading them is admin only.
@router.get("/{name}/files", response_model=VolumeListing, dependencies=[Depends(require_admin)])
def list_volume_files(name: str, path: str = Query(default="/")) -> VolumeListing:
    return volume_files_service.list_dir(name, path)


@router.get("/{name}/files/download", dependencies=[Depends(require_admin)])
def download_volume_file(name: str, path: str = Query()) -> StreamingResponse:
    file = volume_files_service.open_file(name, path)
    return StreamingResponse(
        file.chunks,
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(file.size),
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file.name)}",
        },
    )
