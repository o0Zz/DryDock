"""API tokens (bearer auth) and stored registry credentials."""

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.main import app
from app.models.user import User
from app.services import docker_service, registry_auth_service, registry_service

# --- API tokens --------------------------------------------------------------------


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add_all(
        [
            User(id=1, username="alice", hashed_password="x", is_admin=True),
            User(id=2, username="bob", hashed_password="x", is_active=False),
        ]
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield session
    finally:
        app.dependency_overrides.clear()
        session.close()


def _as(db: Session, user_id: int) -> None:
    app.dependency_overrides[get_current_user] = lambda: db.get(User, user_id)


def test_token_authenticates_as_its_user(db: Session) -> None:
    client = TestClient(app)
    _as(db, 1)
    created = client.post("/api/tokens", json={"name": "ci"}).json()
    del app.dependency_overrides[get_current_user]

    token = created["token"]
    assert token.startswith("ddt_")
    assert created["prefix"] == token[:10]

    bearer = {"Authorization": f"Bearer {token}"}
    listed = client.get("/api/tokens", headers=bearer)
    assert listed.status_code == 200
    assert [(entry["name"], entry["prefix"]) for entry in listed.json()] == [("ci", token[:10])]
    assert "token" not in listed.json()[0]
    assert listed.json()[0]["last_used_at"] is not None
    # A token reaches admin-only routes when its user is an admin.
    assert client.get("/api/users", headers=bearer).status_code == 200


def test_bad_or_revoked_token_is_rejected(db: Session) -> None:
    client = TestClient(app)
    _as(db, 1)
    created = client.post("/api/tokens", json={"name": "ci"}).json()
    assert client.delete(f"/api/tokens/{created['id']}").status_code == 204
    del app.dependency_overrides[get_current_user]

    for token in (created["token"], "ddt_nope"):
        response = client.get("/api/tokens", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid API token"}


def test_token_of_a_disabled_user_is_rejected(db: Session) -> None:
    client = TestClient(app)
    _as(db, 2)
    token = client.post("/api/tokens", json={"name": "old"}).json()["token"]
    del app.dependency_overrides[get_current_user]

    response = client.get("/api/tokens", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_users_only_see_and_delete_their_own_tokens(db: Session) -> None:
    client = TestClient(app)
    _as(db, 1)
    created = client.post("/api/tokens", json={"name": "alice's"}).json()
    _as(db, 2)

    assert client.get("/api/tokens").json() == []
    assert client.delete(f"/api/tokens/{created['id']}").status_code == 404


# --- registry credentials ----------------------------------------------------------


@pytest.fixture
def data_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "data_path", tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("docker.io", registry_auth_service.DOCKER_HUB_KEY),
        ("registry-1.docker.io", registry_auth_service.DOCKER_HUB_KEY),
        ("https://index.docker.io/v1/", registry_auth_service.DOCKER_HUB_KEY),
        ("GHCR.io", "ghcr.io"),
        ("https://registry.lan:5000/", "registry.lan:5000"),
    ],
)
def test_normalize(raw: str, key: str) -> None:
    assert registry_auth_service.normalize(raw) == key


def test_credentials_round_trip_through_a_docker_config(data_path: Path) -> None:
    assert registry_auth_service.subprocess_env() is None

    registry_auth_service.set_credentials("docker.io", "me", "pa:ss")
    registry_auth_service.set_credentials("ghcr.io", "bot", "token")

    config = json.loads((data_path / "docker" / "config.json").read_text(encoding="utf-8"))
    hub = config["auths"][registry_auth_service.DOCKER_HUB_KEY]["auth"]
    assert base64.b64decode(hub).decode() == "me:pa:ss"
    assert registry_auth_service.credentials(registry_service.DOCKER_HUB) == ("me", "pa:ss")
    assert registry_auth_service.list_registries() == [
        ("ghcr.io", "bot"),
        (registry_auth_service.DOCKER_HUB_KEY, "me"),
    ]
    env = registry_auth_service.subprocess_env()
    assert env is not None and env["DOCKER_CONFIG"] == str(data_path / "docker")

    assert registry_auth_service.remove_credentials("ghcr.io")
    assert not registry_auth_service.remove_credentials("ghcr.io")
    assert registry_auth_service.credentials("ghcr.io") is None


def test_add_checks_the_login_and_never_returns_the_password(
    client: TestClient, data_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logins: list[tuple[str, str, str]] = []
    monkeypatch.setattr(docker_service, "registry_login", lambda *args: logins.append(args))

    response = client.post(
        "/api/registries", json={"registry": "ghcr.io", "username": "bot", "password": "secret"}
    )

    assert response.status_code == 201
    assert response.json() == {"registry": "ghcr.io", "username": "bot"}
    assert logins == [("ghcr.io", "bot", "secret")]
    assert client.get("/api/registries").json() == [{"registry": "ghcr.io", "username": "bot"}]
    assert client.delete("/api/registries", params={"registry": "ghcr.io"}).status_code == 204


def test_rejected_login_stores_nothing(
    client: TestClient, data_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: str) -> None:
        raise docker_service.RegistryLoginFailed("login to ghcr.io failed: denied")

    monkeypatch.setattr(docker_service, "registry_login", refuse)

    response = client.post(
        "/api/registries", json={"registry": "ghcr.io", "username": "bot", "password": "bad"}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "login to ghcr.io failed: denied"}
    assert registry_auth_service.list_registries() == []


def test_registries_are_admin_only() -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2, is_admin=False)
    try:
        assert TestClient(app).get("/api/registries").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_tag_listing_sends_credentials_to_the_token_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "auth.example":
            seen.append(request.headers.get("authorization"))
            return httpx.Response(200, json={"token": "t"})
        if request.headers.get("authorization") != "Bearer t":
            return httpx.Response(
                401,
                headers={"www-authenticate": 'Bearer realm="https://auth.example/token"'},
            )
        return httpx.Response(200, json={"tags": ["1.0", "1.1"]})

    real_client = httpx.Client
    monkeypatch.setattr(
        registry_service.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    tags = registry_service.list_tags("ghcr.io", "org/app", ("bot", "secret"))

    assert tags == ["1.0", "1.1"]
    assert seen == ["Basic " + base64.b64encode(b"bot:secret").decode()]
