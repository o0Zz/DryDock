from pydantic import BaseModel, Field


class ServiceExposure(BaseModel):
    service: str
    exposed: bool
    # Traefik router that carries the service, when it has one.
    router: str | None = None
    hosts: list[str] = []
    # Container port Traefik forwards to.
    port: int | None = None
    # Reachable from the internet: on the `wan` entrypoint, or on every entrypoint.
    public: bool = False
    # Ports the service declares (`ports` targets, `expose`), to suggest one.
    ports: list[int] = []
    # Why the service cannot be exposed (e.g. `network_mode: host`), or None.
    blocked: str | None = None


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


class ProxyOverview(BaseModel):
    domain: str
    network: str
    # None when Docker is unreachable; the route list still comes from the files.
    traefik: ProxyContainer | None = None
    network_exists: bool | None = None
    docker_available: bool = True
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
