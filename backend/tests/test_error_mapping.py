"""Service exceptions map to HTTP statuses through the handlers in app.main."""

from collections.abc import Callable
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient

from app.services import compose_service, docker_service


def _raise(exc: Exception) -> Callable[..., NoReturn]:
    def raise_exc(*args: Any, **kwargs: Any) -> NoReturn:
        raise exc

    return raise_exc


@pytest.mark.parametrize(
    ("exc", "code", "detail"),
    [
        (docker_service.DockerNotFound("container x not found"), 404, "container x not found"),
        (docker_service.DockerUnavailable("down"), 503, "Docker unavailable: down"),
    ],
)
def test_not_found_and_daemon_down_differ(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    code: int,
    detail: str,
) -> None:
    monkeypatch.setattr(docker_service, "get_container", _raise(exc))
    response = client.get("/api/containers/x")
    assert response.status_code == code
    assert response.json() == {"detail": detail}


def test_container_running_is_conflict(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
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
def test_compose_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, exc: Exception, code: int
) -> None:
    monkeypatch.setattr(compose_service, "create_compose", _raise(exc))
    response = client.post("/api/projects", json={"name": "web", "content": "services: {}"})
    assert response.status_code == code
