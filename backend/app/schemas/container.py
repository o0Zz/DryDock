from datetime import datetime

from pydantic import BaseModel


class ContainerPort(BaseModel):
    private_port: int
    public_port: int | None = None
    protocol: str = "tcp"
    host_ip: str | None = None


class Container(BaseModel):
    id: str
    name: str
    image: str
    status: str
    state: str
    created_at: datetime
    ports: list[ContainerPort]
    compose_project: str | None = None
    compose_service: str | None = None
    # Compose file(s) this container was deployed from, per Docker's label.
    compose_config_files: str | None = None
    restart_policy: str | None = None
