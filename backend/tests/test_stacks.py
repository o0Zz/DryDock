"""Deleting, renaming and duplicating stacks: files on disk, job bodies and routes."""

import subprocess
import tarfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import get_current_user
from app.main import app
from app.models.job import JobKind
from app.schemas.project import Project
from app.services import (
    compose_service,
    docker_service,
    job_service,
    repo_service,
    stack_service,
    tasks,
)

COMPOSE = "services:\n  app:\n    image: nginx\n"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    # web owns its folder; media.yml and tools.yml share the repo root.
    (root / "web" / "data").mkdir(parents=True)
    (root / "web" / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    (root / "web" / "docker-compose.override.yml").write_text(COMPOSE, encoding="utf-8")
    (root / "web" / ".env").write_text("A=1\n", encoding="utf-8")
    (root / "web" / "data" / "db.sqlite").write_bytes(b"data")
    (root / "media.yml").write_text(COMPOSE, encoding="utf-8")
    (root / "media.override.yml").write_text(COMPOSE, encoding="utf-8")
    (root / "tools.yml").write_text(COMPOSE, encoding="utf-8")
    (root / ".env").write_text("SHARED=1\n", encoding="utf-8")
    monkeypatch.setattr(settings, "repo_path", root)
    monkeypatch.setattr(settings, "data_path", tmp_path / "data")
    return root.resolve()


def _project(name: str) -> Project:
    return next(project for project in repo_service.discover_projects() if project.name == name)


def _names() -> list[str]:
    return [project.name for project in repo_service.discover_projects()]


def test_layout_tells_owned_folders_from_shared_ones(repo: Path) -> None:
    web = stack_service.layout(_project("web"))
    assert web.folder == repo / "web"
    assert [path.name for path in web.files] == [
        "docker-compose.yml",
        "docker-compose.override.yml",
    ]

    media = stack_service.layout(_project("media"))
    assert media.folder is None
    assert [path.name for path in media.files] == ["media.yml", "media.override.yml"]


def test_a_folder_with_a_nested_stack_is_shared(repo: Path) -> None:
    (repo / "web" / "extra").mkdir()
    (repo / "web" / "extra" / "compose.yml").write_text(COMPOSE, encoding="utf-8")

    assert stack_service.layout(_project("web")).folder is None


def test_delete_owned_folder_archives_it_first(repo: Path) -> None:
    project = _project("web")

    backup = Path(stack_service.delete(project))

    assert not (repo / "web").exists()
    assert backup.parent == settings.backups_path / project.id
    with tarfile.open(backup) as tar:
        assert "web/data/db.sqlite" in tar.getnames()
        assert "web/.env" in tar.getnames()


def test_delete_in_a_shared_folder_removes_only_the_stack_files(repo: Path) -> None:
    project = _project("media")

    backup_dir = Path(stack_service.delete(project))

    assert not (repo / "media.yml").exists()
    assert not (repo / "media.override.yml").exists()
    assert (repo / "tools.yml").exists() and (repo / ".env").exists()
    assert sorted(path.name.split("-", 1)[1] for path in backup_dir.iterdir()) == [
        "media.override.yml",
        "media.yml",
    ]


def test_rename_owned_folder_moves_it(repo: Path) -> None:
    project = _project("web")

    new_path = stack_service.rename(project, "site")

    assert new_path == repo / "site" / "docker-compose.yml"
    assert not (repo / "web").exists()
    assert (repo / "site" / "data" / "db.sqlite").read_bytes() == b"data"
    assert "site" in _names() and "web" not in _names()
    assert repo_service.project_id(new_path) == _project("site").id


def test_rename_freely_named_files_in_a_shared_folder(repo: Path) -> None:
    new_path = stack_service.rename(_project("media"), "films")

    assert new_path == repo / "films.yml"
    assert (repo / "films.override.yml").exists()
    assert not (repo / "media.yml").exists()
    assert (repo / ".env").read_text(encoding="utf-8") == "SHARED=1\n"


def test_duplicate_copies_without_touching_the_original(repo: Path) -> None:
    stack_service.duplicate(_project("web"), "web2")
    stack_service.duplicate(_project("media"), "media2")

    assert (repo / "web" / "docker-compose.yml").exists()
    assert (repo / "web2" / "data" / "db.sqlite").read_bytes() == b"data"
    assert (repo / "web2" / ".env").exists()
    assert (repo / "media.yml").exists() and (repo / "media2.yml").exists()
    assert (repo / "media2.override.yml").exists()
    assert sorted(_names()) == ["media", "media2", "tools", "web", "web2"]


@pytest.mark.parametrize("taken", ["tools", "web", "TOOLS"])
def test_new_name_must_be_free(repo: Path, taken: str) -> None:
    with pytest.raises(compose_service.ComposeExists, match="already exists"):
        stack_service.check_new_name(_project("media"), taken)


def test_new_name_must_not_hit_an_existing_path(repo: Path) -> None:
    (repo / "site").mkdir()  # a plain folder, not a stack

    with pytest.raises(compose_service.ComposeExists, match="site already exists"):
        stack_service.check_new_name(_project("web"), "site")


# --- job bodies --------------------------------------------------------------------


class _Ctx:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.output: str | None = None

    def set_total(self, total: int, message: str | None = None) -> None:
        pass

    def advance(self, message: str | None = None) -> None:
        if message:
            self.messages.append(message)

    def note(self, message: str) -> None:
        self.messages.append(message)

    def set_output(self, output: str) -> None:
        self.output = output


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "Removed")

    monkeypatch.setattr(compose_service.subprocess, "run", fake_run)
    return calls


def test_delete_runner_downs_with_volumes_then_deletes(
    repo: Path, commands: list[list[str]]
) -> None:
    ctx = _Ctx()

    tasks.stack_delete_runner(_project("web"), project_name=None, stop=False, remove_volumes=True)(
        ctx
    )

    assert commands[0][-3:] == ["down", "--remove-orphans", "--volumes"]
    assert ctx.output == "Removed"
    assert not (repo / "web").exists()
    assert ctx.messages[-1].startswith("Deleted web. Backup: ")


def test_delete_runner_skips_down_for_a_stack_that_is_not_deployed(
    repo: Path, commands: list[list[str]]
) -> None:
    tasks.stack_delete_runner(
        _project("tools"), project_name=None, stop=False, remove_volumes=False
    )(_Ctx())

    assert commands == []
    assert not (repo / "tools.yml").exists()


def test_rename_runner_stops_the_stack_first(repo: Path, commands: list[list[str]]) -> None:
    tasks.stack_rename_runner(_project("media"), "films", project_name="media", stop=True)(_Ctx())

    assert commands[0][-4:] == ["-p", "media", "down", "--remove-orphans"]
    assert (repo / "films.yml").exists()


def test_failed_down_keeps_the_files(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "boom")

    monkeypatch.setattr(compose_service.subprocess, "run", fail)

    with pytest.raises(compose_service.ComposeError, match="boom"):
        tasks.stack_delete_runner(
            _project("web"), project_name=None, stop=True, remove_volumes=False
        )(_Ctx())
    assert (repo / "web" / "docker-compose.yml").exists()


# --- routes ------------------------------------------------------------------------


@pytest.fixture
def client(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(docker_service, "list_containers", lambda **kwargs: [])
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=False)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def submit(kind: str, label: str, runner: Any) -> SimpleNamespace:
        calls.append((kind, label))
        return SimpleNamespace(
            id="job1",
            kind=kind,
            label=label,
            status="pending",
            total=0,
            done=0,
            message=None,
            error=None,
            output=None,
            trigger="manual",
            created_at="2026-01-01T00:00:00Z",
            started_at=None,
            finished_at=None,
        )

    monkeypatch.setattr(job_service, "submit", submit)
    return calls


def test_routes_queue_jobs(client: TestClient, submitted: list[tuple[str, str]]) -> None:
    web = _project("web")

    deleted = client.delete(f"/api/projects/{web.id}", params={"remove_volumes": True})
    renamed = client.post(f"/api/projects/{web.id}/rename", json={"name": "site"})
    copied = client.post(f"/api/projects/{web.id}/duplicate", json={"name": "web2"})

    assert [deleted.status_code, renamed.status_code, copied.status_code] == [202, 202, 202]
    assert renamed.json()["project_id"] == repo_service.project_id(
        Path(web.compose_path).parent.parent / "site" / "docker-compose.yml"
    )
    assert submitted == [
        (JobKind.STACK_CHANGE, "Delete web"),
        (JobKind.STACK_CHANGE, "Rename web to site"),
        (JobKind.STACK_CHANGE, "Duplicate web as web2"),
    ]


def test_routes_check_the_new_name_before_queueing(
    client: TestClient, submitted: list[tuple[str, str]]
) -> None:
    web = _project("web")

    assert client.post(f"/api/projects/{web.id}/rename", json={"name": "tools"}).status_code == 409
    assert client.post(f"/api/projects/{web.id}/rename", json={"name": "Bad"}).status_code == 422
    assert submitted == []
