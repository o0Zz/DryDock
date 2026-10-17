"""docker_service.get_container_detail, against a fake Docker client."""

from types import SimpleNamespace

import pytest
from docker.errors import NotFound

from app.services import docker_service

ATTRS = {
    "Created": "2026-01-02T03:04:05.123456789Z",
    "Image": "sha256:nginx",
    "RestartCount": 2,
    "State": {
        "Status": "running",
        "StartedAt": "2026-01-02T03:04:06Z",
        "FinishedAt": "0001-01-01T00:00:00Z",
        "ExitCode": 0,
        "Health": {"Status": "healthy"},
    },
    "Config": {
        "Image": "nginx:latest",
        "Cmd": ["nginx", "-g", "daemon off;"],
        "Entrypoint": "/docker-entrypoint.sh",
        "Env": ["PATH=/usr/bin", "DB_PASSWORD=hunter2"],
        "Labels": {"com.docker.compose.project": "web"},
        "WorkingDir": "",
        "Hostname": "abc123",
    },
    "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
    "Mounts": [
        {"Type": "bind", "Source": "/srv/www", "Destination": "/usr/share/nginx", "RW": False},
        {"Type": "volume", "Name": "data", "Destination": "/data", "Mode": "z", "RW": True},
    ],
    "NetworkSettings": {
        "Ports": {},
        "Networks": {"web_default": {"IPAddress": "172.18.0.2", "Gateway": "172.18.0.1"}},
    },
}


class FakeContainers:
    def get(self, container_id: str) -> SimpleNamespace:
        if container_id != "abc":
            raise NotFound("missing")
        return SimpleNamespace(id="abc", name="web", status="running", image=None, attrs=ATTRS)


@pytest.fixture(autouse=True)
def fake(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SimpleNamespace(containers=FakeContainers())
    monkeypatch.setattr(docker_service, "_client", lambda: client)


def test_detail_maps_inspect_fields() -> None:
    detail = docker_service.get_container_detail("abc", privileged=True)

    assert detail.name == "web" and detail.image == "nginx:latest"
    assert detail.compose_project == "web"
    assert detail.restart_policy == "unless-stopped"
    assert detail.command == ["nginx", "-g", "daemon off;"]
    assert detail.entrypoint == ["/docker-entrypoint.sh"]
    assert detail.working_dir is None
    assert detail.started_at is not None and detail.started_at.year == 2026
    assert detail.finished_at is None  # zero time means "never"
    assert detail.health == "healthy"
    assert detail.restart_count == 2
    assert [(mount.type, mount.source, mount.rw) for mount in detail.mounts] == [
        ("bind", "/srv/www", False),
        ("volume", "data", True),
    ]
    assert [(network.name, network.ip_address) for network in detail.networks] == [
        ("web_default", "172.18.0.2")
    ]


def test_admin_sees_env_and_raw() -> None:
    detail = docker_service.get_container_detail("abc", privileged=True)
    assert {variable.key: variable.value for variable in detail.env}["DB_PASSWORD"] == "hunter2"
    assert detail.env_revealed is True
    assert detail.raw == ATTRS


def test_non_admin_gets_masked_env_and_no_raw() -> None:
    detail = docker_service.get_container_detail("abc", privileged=False)
    assert [variable.key for variable in detail.env] == ["PATH", "DB_PASSWORD"]
    assert all(variable.value == docker_service.MASKED_VALUE for variable in detail.env)
    assert detail.env_revealed is False
    assert detail.raw is None


@pytest.mark.parametrize(
    ("image", "labels", "expected"),
    [
        ("nginx:latest", {}, None),
        ("linuxserver/sonarr:latest", {"org.opencontainers.image.version": "4.0.9"}, "4.0.9"),
        # Inherited from the ubuntu base image, not this image's version.
        (
            "myapp:latest",
            {
                "org.opencontainers.image.version": "24.04",
                "org.opencontainers.image.ref.name": "ubuntu",
            },
            None,
        ),
        (
            "ubuntu:noble",
            {
                "org.opencontainers.image.version": "24.04",
                "org.opencontainers.image.ref.name": "ubuntu",
            },
            "24.04",
        ),
        # Some images put the tag in ref.name.
        (
            "app:stable",
            {
                "org.opencontainers.image.version": "1.2.3",
                "org.opencontainers.image.ref.name": "1.2.3",
            },
            "1.2.3",
        ),
    ],
)
def test_image_version_label(image: str, labels: dict[str, str], expected: str | None) -> None:
    assert docker_service._image_version(image, labels) == expected


def test_missing_container() -> None:
    with pytest.raises(docker_service.DockerUnavailable):
        docker_service.get_container_detail("nope", privileged=True)
