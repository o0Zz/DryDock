from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.image import Image
from app.schemas.volume import PruneResult
from app.services import docker_service

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("", response_model=list[Image])
def list_images() -> list[Image]:
    try:
        return docker_service.list_images()
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


@router.post("/prune", response_model=PruneResult)
def prune_images(
    all_unused: bool = Query(
        default=False,
        alias="all",
        description="Remove every image without a container, not only dangling ones",
    ),
) -> PruneResult:
    try:
        return docker_service.prune_images(all_unused=all_unused)
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


# Image references contain "/" and ":", so they travel as a query parameter.
@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    image: str = Query(min_length=1, description="Tag or ID of the image to remove"),
    force: bool = Query(default=False),
) -> None:
    try:
        docker_service.remove_image(image, force=force)
    except docker_service.ImageNotFound as exc:
        raise HTTPException(status_code=404, detail=f"image {exc} not found") from exc
    except docker_service.ImageInUse as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc
