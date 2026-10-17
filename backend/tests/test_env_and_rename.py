""".env editing for a stack, and renaming a container."""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from docker.errors import APIError
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import get_current_user
from app.main import app
from app.services import compose_service, docker_service

COMPOSE = "services:\n  web:\n    image: nginx\n"


# --- .env validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "",
        "# comment\n\nTZ=Europe/Paris\n",
        "export PORT=8080\nEMPTY=\nSPACED = value\nYAML_STYLE: value\nINHERITED\n",
        "QUOTED=\"a # not a comment\"\nSINGLE='x'\n",
        'MULTI="line one\nline two"\nAFTER=1\n',
        'ESCAPED="say \\"hi\\"\nstill open"\n',
    ],
)
def test_valid_env_files(content: str) -> None:
    compose_service._validate_env(content)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("OK=1\nnot an assignment\n", "Line 2"),
        ("1BAD=x\n", "Line 1"),
        ("KEY value\n", "Line 1"),
        ('A=1\nB="never closed\nC=3\n', "Line 2: quoted value is never closed"),
    ],
)
def test_invalid_env_files(content: str, message: str) -> None:
    with pytest.raises(compose_service.ComposeError, match=message):
        compose_service._validate_env(content)


# --- .env routes -------------------------------------------------------------------


@pytest.fixture
def stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, str, Path]]:
    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    compose_path = repo / "web" / "docker-compose.yml"
    compose_path.write_text(COMPOSE, encoding="utf-8")
    monkeypatch.setattr(settings, "repo_path", repo)
    monkeypatch.setattr(settings, "data_path", tmp_path / "data")
    monkeypatch.setattr(docker_service, "list_containers", lambda **kwargs: [])
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        client = TestClient(app)
        project_id = client.get("/api/projects").json()[0]["id"]
        yield client, project_id, compose_path.parent / ".env"
    finally:
        app.dependency_overrides.clear()


def test_env_is_created_then_backed_up_on_change(stack: tuple[TestClient, str, Path]) -> None:
    client, project_id, env_file = stack

    assert client.get(f"/api/projects/{project_id}/env").json() == {"content": "", "exists": False}

    first = client.put(f"/api/projects/{project_id}/env", json={"content": "A=1\n"})
    assert first.status_code == 200
    assert first.json() == {"backup_path": None}
    assert env_file.read_text(encoding="utf-8") == "A=1\n"

    second = client.put(f"/api/projects/{project_id}/env", json={"content": "A=2\n"})
    backup = Path(second.json()["backup_path"])
    assert backup.name.endswith(".env")
    assert backup.read_text(encoding="utf-8") == "A=1\n"
    assert client.get(f"/api/projects/{project_id}/env").json() == {
        "content": "A=2\n",
        "exists": True,
    }


def test_invalid_env_is_not_written(stack: tuple[TestClient, str, Path]) -> None:
    client, project_id, env_file = stack

    response = client.put(f"/api/projects/{project_id}/env", json={"content": "not valid\n"})

    assert response.status_code == 400
    assert "Line 1" in response.json()["detail"]
    assert not env_file.exists()


def test_env_is_admin_only(stack: tuple[TestClient, str, Path]) -> None:
    client, project_id, _ = stack
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2, is_admin=False)

    assert client.get(f"/api/projects/{project_id}/env").status_code == 403
    assert client.put(f"/api/projects/{project_id}/env", json={"content": ""}).status_code == 403


# --- rename ------------------------------------------------------------------------


class _FakeContainer:
    def __init__(self, error: Exception | None = None) -> None:
        self.name = "old"
        self.error = error

    def rename(self, name: str) -> None:
        if self.error:
            raise self.error
        self.name = name

    def reload(self) -> None:
        pass


def test_rename(monkeypatch: pytest.MonkeyPatch) -> None:
    container = _FakeContainer()
    monkeypatch.setattr(docker_service, "_get_container", lambda container_id: container)

    monkeypatch.setattr(docker_service, "_to_schema", lambda container: container.name)

    assert docker_service.rename_container("abc", "new") == "new"


def test_rename_to_a_taken_name_is_a_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    error = APIError("conflict", response=SimpleNamespace(status_code=409), explanation="in use")
    monkeypatch.setattr(
        docker_service, "_get_container", lambda container_id: _FakeContainer(error)
    )

    with pytest.raises(docker_service.ContainerConflict, match="in use"):
        docker_service.rename_container("abc", "taken")


def test_rename_route_checks_the_name(monkeypatch: pytest.MonkeyPatch) -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        response = TestClient(app).post("/api/containers/abc/rename", json={"name": "bad name"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
