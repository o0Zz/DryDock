from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import require_admin
from app.schemas.registry import RegistryCredentialCreate, RegistryCredentialRead
from app.services import docker_service, registry_auth_service

# Credentials reach private images, so only admins manage them.
router = APIRouter(
    prefix="/api/registries", tags=["registries"], dependencies=[Depends(require_admin)]
)


@router.get("", response_model=list[RegistryCredentialRead])
def list_registries() -> list[RegistryCredentialRead]:
    return [
        RegistryCredentialRead(registry=registry, username=username)
        for registry, username in registry_auth_service.list_registries()
    ]


@router.post("", response_model=RegistryCredentialRead, status_code=status.HTTP_201_CREATED)
def add_registry(body: RegistryCredentialCreate) -> RegistryCredentialRead:
    """Check the credentials with the registry, then store them."""
    registry = registry_auth_service.normalize(body.registry)
    docker_service.registry_login(registry, body.username, body.password)
    registry_auth_service.set_credentials(registry, body.username, body.password)
    return RegistryCredentialRead(registry=registry, username=body.username)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def remove_registry(registry: str = Query()) -> None:
    if not registry_auth_service.remove_credentials(registry):
        raise HTTPException(status_code=404, detail=f"No credentials for {registry}")
