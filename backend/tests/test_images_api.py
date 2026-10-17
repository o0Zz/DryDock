"""/api/images routes, with docker_service stubbed out."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.schemas.image import ContainerRef, Image
from app.services import docker_service


@pytest.fixture
def client():
    # No `with`: the lifespan (DB init, scheduler) is not needed for these routes.
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _raise(exc):
    def fn(*args, **kwargs):
        raise exc

    return fn


def test_requires_login():
    anon = TestClient(app)
    assert anon.get("/api/images").status_code == 401
    assert anon.delete("/api/images", params={"image": "nginx"}).status_code == 401
    assert anon.post("/api/images/prune").status_code == 401


def test_list(client, monkeypatch):
    image = Image(
        id="sha256:1",
        tags=["nginx:latest"],
        size=42,
        used_by=[ContainerRef(name="web", running=True)],
    )
    monkeypatch.setattr(docker_service, "list_images", lambda: [image])

    res = client.get("/api/images")

    assert res.status_code == 200
    assert res.json() == [
        {
            "id": "sha256:1",
            "tags": ["nginx:latest"],
            "size": 42,
            "created_at": None,
            "used_by": [{"name": "web", "running": True}],
        }
    ]


def test_list_docker_down(client, monkeypatch):
    monkeypatch.setattr(
        docker_service, "list_images", _raise(docker_service.DockerUnavailable("down"))
    )
    res = client.get("/api/images")
    assert res.status_code == 503
    assert "down" in res.json()["detail"]


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
def test_delete_passes_reference_and_force(client, monkeypatch, params, expected):
    calls = []
    monkeypatch.setattr(
        docker_service, "remove_image", lambda image, force: calls.append((image, force))
    )

    res = client.delete("/api/images", params=params)

    assert res.status_code == 204
    assert calls == [expected]


def test_delete_requires_image(client):
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
def test_delete_errors(client, monkeypatch, exc, code):
    monkeypatch.setattr(docker_service, "remove_image", _raise(exc))
    res = client.delete("/api/images", params={"image": "ghost:1"})
    assert res.status_code == code
