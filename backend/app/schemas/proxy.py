from pydantic import BaseModel, Field


class ServiceExposure(BaseModel):
    service: str
    exposed: bool
    hosts: list[str] = []
    # Container port the proxy forwards to.
    port: int | None = None
    # Reachable from any IP: `expose.private=false`.
    public: bool = False
    # Ports the service declares (`ports` targets, `expose`), to suggest one.
    ports: list[int] = []
    # Why the service cannot be exposed (e.g. `network_mode: service:vpn`), or None.
    blocked: str | None = None
    # It still has labels of an older proxy setup (`traefik.*`, `swag*`); exposing drops them.
    legacy: bool = False
    # `drydock.update=auto`: the scheduled auto-update may recreate it.
    auto_update: bool = False


class ProxyRoute(BaseModel):
    project_id: str
    project_name: str
    service: str
    hosts: list[str]
    port: int | None = None
    public: bool
    running: bool


class ProxyContainer(BaseModel):
    id: str
    name: str
    running: bool
    # For the proxy: traefik, swag or caddy (its `drydock.proxy` label, else its image).
    kind: str | None = None


class ProxyOverview(BaseModel):
    domain: str
    network: str
    # None when Docker is unreachable; the route list still comes from the files.
    container: ProxyContainer | None = None
    # The proxy sync, which turns the expose.* labels into the proxy's config.
    sync: ProxyContainer | None = None
    network_exists: bool | None = None
    docker_available: bool = True
    # Image the proxy stack template runs the sync from: DryDock's own.
    drydock_image: str
    routes: list[ProxyRoute] = []


class ExposureContent(BaseModel):
    # The editor's content, saved or not: the change lands in the editor first.
    content: str


class ExposeRequest(ExposureContent):
    service: str = Field(min_length=1, max_length=255)
    # A full host name, or a bare sub-domain completed with the proxy domain.
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    public: bool = False


class UnexposeRequest(ExposureContent):
    service: str = Field(min_length=1, max_length=255)


class AutoUpdateRequest(ExposureContent):
    service: str = Field(min_length=1, max_length=255)
    enabled: bool
