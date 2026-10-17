from fastapi import APIRouter, status

from app.models.job import Job, JobKind
from app.schemas.job import JobRead
from app.schemas.network import Network
from app.services import docker_service, job_service, tasks

router = APIRouter(prefix="/api/networks", tags=["networks"])


@router.get("", response_model=list[Network])
def list_networks() -> list[Network]:
    return docker_service.list_networks()


@router.post("/prune", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def prune_networks() -> Job:
    return job_service.submit(
        JobKind.NETWORK_PRUNE, "Prune unused networks", tasks.network_prune_runner()
    )


@router.delete("/{network_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_network(network_id: str) -> None:
    docker_service.remove_network(network_id)
