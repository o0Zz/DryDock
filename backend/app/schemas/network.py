from datetime import datetime

from pydantic import BaseModel, Field


class NetworkUser(BaseModel):
    """A container attached to the network, in any state."""

    id: str
    name: str
    running: bool
    ip_address: str | None = None


class Network(BaseModel):
    id: str
    name: str
    driver: str
    scope: str | None = None
    subnets: list[str] = Field(default_factory=list)
    gateways: list[str] = Field(default_factory=list)
    internal: bool = False
    created_at: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    compose_project: str | None = None
    # bridge, host and none: Docker's own networks, which cannot be removed.
    predefined: bool = False
    used_by: list[NetworkUser] = Field(default_factory=list)
