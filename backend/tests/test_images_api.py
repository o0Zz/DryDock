"""/api/images routes, with docker_service stubbed out."""

from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.schemas.image import ContainerRef, Image
from app.services import docker_service


@pytest.fixture
def client() -> Iterator[TestClient]:
    # No `with`: the lifespan (DB init, scheduler) is not needed for these routes.
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _raise(exc: Exception) -> Callable[..., NoReturn]:
    def raise_exc(*args: Any, **kwargs: Any) -> NoReturn:
        raise exc

    return raise_exc


def test_requires_login() -> None:
    anonymous = TestClient(app)
    assert anonymous.get("/api/images").status_code == 401
    assert anonymous.delete("/api/images", params={"image": "nginx"}).status_code == 401
    assert anonymous.post("/api/images/prune").status_code == 401


def test_list(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    image = Image(
        id="sha256:1",
        tags=["nginx:latest"],
        size=42,
        used_by=[ContainerRef(name="web", running=True)],
    )
    monkeypatch.setattr(docker_service, "list_images", lambda: [image])

    response = client.get("/api/images")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "sha256:1",
            "tags": ["nginx:latest"],
            "size": 42,
            "created_at": None,
            "used_by": [{"name": "web", "running": True}],
        }
    ]


def test_list_docker_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_service, "list_images", _raise(docker_service.DockerUnavailable("down"))
    )
    response = client.get("/api/images")
    assert response.status_code == 503
    assert "down" in response.json()["detail"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (
            {"image": "ghcr.io/home-assistant/home-assistant:stable"},
            ("ghcr.io/home-assistant/home-assistant:stable", False),
        ),
        ({"image": "localhost:5000/app:1.0", "force": "true"}, ("localhost:5000/app:1.0", True)),
    ],
)
def test_delete_passes_reference_and_force(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, str],
    expected: tuple[str, bool],
) -> None:
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        docker_service, "remove_image", lambda image, force: calls.append((image, force))
    )

    response = client.delete("/api/images", params=params)

    assert response.status_code == 204
    assert calls == [expected]


def test_delete_requires_image(client: TestClient) -> None:
    assert client.delete("/api/images").status_code == 422
    assert client.delete("/api/images", params={"image": ""}).status_code == 422


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (docker_service.ImageNotFound("ghost:1"), 404),
        (docker_service.ImageInUse("used by web"), 409),
        (docker_service.DockerUnavailable("down"), 503),
    ],
)
def test_delete_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, exc: Exception, code: int
) -> None:
    monkeypatch.setattr(docker_service, "remove_image", _raise(exc))
    response = client.delete("/api/images", params={"image": "ghost:1"})
    assert response.status_code == code
