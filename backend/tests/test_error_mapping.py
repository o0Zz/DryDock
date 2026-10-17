"""Service exceptions map to HTTP statuses through the handlers in app.main."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.services import compose_service, docker_service


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _raise(exc):
    def fn(*args, **kwargs):
        raise exc

    return fn


@pytest.mark.parametrize(
    ("exc", "code", "detail"),
    [
        (docker_service.DockerNotFound("container x not found"), 404, "container x not found"),
        (docker_service.DockerUnavailable("down"), 503, "Docker unavailable: down"),
    ],
)
def test_not_found_and_daemon_down_differ(client, monkeypatch, exc, code, detail):
    monkeypatch.setattr(docker_service, "get_container", _raise(exc))
    res = client.get("/api/containers/x")
    assert res.status_code == code
    assert res.json() == {"detail": detail}


def test_container_running_is_conflict(client, monkeypatch):
    monkeypatch.setattr(
        docker_service, "remove_container", _raise(docker_service.ContainerRunning("running"))
    )
    assert client.delete("/api/containers/x").status_code == 409


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (compose_service.ComposeExists("exists"), 409),
        (compose_service.ComposeError("Invalid YAML"), 400),
    ],
)
def test_compose_errors(client, monkeypatch, exc, code):
    monkeypatch.setattr(compose_service, "create_compose", _raise(exc))
    res = client.post("/api/projects", json={"name": "web", "content": "services: {}"})
    assert res.status_code == code
