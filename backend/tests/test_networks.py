"""docker_service networks, against a fake Docker client, and the routes."""

from types import SimpleNamespace
from typing import Any

import pytest
from docker.errors import NotFound
from fastapi.testclient import TestClient

from app.services import docker_service


class _FakeNetwork:
    def __init__(self, name: str, *, subnet: str | None = None, project: str | None = None) -> None:
        self.id = f"id-{name}"
        self.name = name
        labels = {"com.docker.compose.project": project} if project else {}
        ipam = [{"Subnet": subnet, "Gateway": subnet.rsplit(".", 2)[0] + ".0.1"}] if subnet else []
        self.attrs = {
            "Driver": "bridge",
            "Scope": "local",
            "Labels": labels,
            "IPAM": {"Config": ipam},
        }
        self.removed = False

    def remove(self) -> None:
        self.removed = True


def _container(name: str, status: str, networks: dict[str, dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"c-{name}", name=name, status=status, attrs={"NetworkSettings": {"Networks": networks}}
    )


@pytest.fixture
def networks(monkeypatch: pytest.MonkeyPatch) -> dict[str, _FakeNetwork]:
    fakes = {
        name: _FakeNetwork(name, subnet=subnet, project=project)
        for name, subnet, project in [
            ("bridge", "172.17.0.0/16", None),
            ("host", None, None),
            ("web_default", "172.18.0.0/16", "web"),
            ("idle_default", "172.19.0.0/16", "idle"),
            ("orphan", "172.20.0.0/16", None),
        ]
    }
    containers = [
        _container("web-app", "running", {"web_default": {"IPAddress": "172.18.0.2"}}),
        # Never started: Docker has not filled in the NetworkID yet.
        _container("idle-app", "created", {"idle_default": {"NetworkID": "", "IPAddress": ""}}),
    ]

    def get(network_id: str) -> _FakeNetwork:
        for network in fakes.values():
            if network_id in (network.id, network.name):
                return network
        raise NotFound("missing")

    client = SimpleNamespace(
        networks=SimpleNamespace(
            list=lambda greedy=False: [n for n in fakes.values() if not n.removed], get=get
        ),
        containers=SimpleNamespace(list=lambda all=False: containers),
    )
    monkeypatch.setattr(docker_service, "_client", lambda: client)
    return fakes


def test_list_shows_subnets_projects_and_users_in_any_state(
    networks: dict[str, _FakeNetwork],
) -> None:
    listed = {network.name: network for network in docker_service.list_networks()}

    assert list(listed) == ["bridge", "host", "idle_default", "orphan", "web_default"]
    assert listed["bridge"].predefined and not listed["orphan"].predefined
    assert listed["web_default"].subnets == ["172.18.0.0/16"]
    assert listed["web_default"].compose_project == "web"
    assert [(u.name, u.running, u.ip_address) for u in listed["web_default"].used_by] == [
        ("web-app", True, "172.18.0.2")
    ]
    assert [(u.name, u.running) for u in listed["idle_default"].used_by] == [("idle-app", False)]


def test_remove_refuses_used_and_predefined_networks(networks: dict[str, _FakeNetwork]) -> None:
    with pytest.raises(docker_service.NetworkInUse, match="used by idle-app"):
        docker_service.remove_network("idle_default")
    with pytest.raises(docker_service.NetworkInUse, match="Docker's own"):
        docker_service.remove_network("bridge")
    with pytest.raises(docker_service.DockerNotFound):
        docker_service.remove_network("nope")

    docker_service.remove_network("id-orphan")
    assert networks["orphan"].removed


def test_prune_keeps_networks_of_stopped_stacks(networks: dict[str, _FakeNetwork]) -> None:
    assert docker_service.prune_networks() == ["orphan"]
    assert [name for name, network in networks.items() if network.removed] == ["orphan"]


def test_delete_route_maps_in_use_to_conflict(
    client: TestClient, networks: dict[str, _FakeNetwork]
) -> None:
    response = client.delete("/api/networks/web_default")

    assert response.status_code == 409
    assert response.json() == {"detail": "network web_default is used by web-app"}
    assert client.delete("/api/networks/orphan").status_code == 204
