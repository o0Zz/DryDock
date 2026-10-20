from pydantic import BaseModel, Field


class RegistryCredentialRead(BaseModel):
    # `https://index.docker.io/v1/` for Docker Hub, else the registry host.
    registry: str
    username: str


class RegistryCredentialCreate(BaseModel):
    # Host with an optional port, e.g. `ghcr.io` or `registry.lan:5000`; `docker.io` for Docker Hub.
    registry: str = Field(
        min_length=1, max_length=255, pattern=r"^(https?://)?[A-Za-z0-9.-]+(:\d+)?(/v1)?/?$"
    )
    username: str = Field(min_length=1, max_length=255)
    # Password or access token. Write-only: never returned by the API.
    password: str = Field(min_length=1, max_length=4096)


class RegistryCredentialUpdate(RegistryCredentialCreate):
    # Empty keeps the stored password: the UI never sees it.
    password: str = Field(default="", max_length=4096)
