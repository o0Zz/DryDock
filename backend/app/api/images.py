from fastapi import APIRouter, Query, status

from app.models.job import Job, JobKind
from app.schemas.image import Image
from app.schemas.job import JobRead
from app.services import docker_service, job_service, tasks

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("", response_model=list[Image])
def list_images() -> list[Image]:
    return docker_service.list_images()


@router.post("/prune", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def prune_images(
    all_unused: bool = Query(
        default=False,
        alias="all",
        description="Remove every image without a container, not only dangling ones",
    ),
) -> Job:
    label = "Prune unused images" if all_unused else "Prune dangling images"
    return job_service.submit(
        JobKind.IMAGE_PRUNE, label, tasks.image_prune_runner(all_unused=all_unused)
    )


# Image references contain "/" and ":", so they travel as a query parameter.
@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    image: str = Query(min_length=1, description="Tag or ID of the image to remove"),
    force: bool = Query(default=False),
) -> None:
    docker_service.remove_image(image, force=force)
