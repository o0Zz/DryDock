"""Which files and project name `docker compose` runs with, plus small action tweaks."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from docker.errors import APIError
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import get_current_user
from app.main import app
from app.schemas.container import Container
from app.schemas.project import Project
from app.services import compose_service, docker_service, repo_service, trivy_service

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(compose_service.subprocess, "run", fake_run)
    monkeypatch.setattr(trivy_service.subprocess, "run", fake_run)
    return calls


# --- override merge ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("main", "override"),
    [
        ("docker-compose.yml", "docker-compose.override.yml"),
        ("compose.yaml", "compose.override.yaml"),
        ("media.yml", "media.override.yaml"),
    ],
)
def test_override_file_is_merged(
    tmp_path: Path, commands: list[list[str]], main: str, override: str
) -> None:
    (tmp_path / main).write_text("services: {}", encoding="utf-8")
    (tmp_path / override).write_text("services: {}", encoding="utf-8")

    compose_service.run_action(tmp_path / main, "up")

    assert commands[0][:6] == [
        "docker",
        "compose",
        "-f",
        str(tmp_path / main),
        "-f",
        str(tmp_path / override),
    ]


def test_no_override_file(tmp_path: Path, commands: list[list[str]]) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}", encoding="utf-8")
    # Another stack's override in the same folder must not be picked up.
    (tmp_path / "media.override.yml").write_text("services: {}", encoding="utf-8")

    compose_service.run_action(compose, "up", project_name="web")

    assert commands[0] == ["docker", "compose", "-f", str(compose), "-p", "web", "up", "-d"]


# --- project name -----------------------------------------------------------------


def _project(compose_path: str, name: str, running: str | None = None) -> Project:
    containers = []
    if running:
        containers.append(
            Container(
                id="abc",
                name=f"{running}-app-1",
                image="nginx",
                status="running",
                state="running",
                created_at=NOW,
                ports=[],
                compose_project=running,
                compose_service="app",
            )
        )
    return Project(
        id="p1",
        name=name,
        compose_path=compose_path,
        relative_path=compose_path.removeprefix("/repo/"),
        modified_at=NOW,
        services=[],
        containers=containers,
    )


@pytest.mark.parametrize(
    ("project", "expected"),
    [
        # Canonical files keep Compose's default, the folder name.
        (_project("/repo/web/docker-compose.yml", "web"), None),
        # Freely named files get their own name, at the repo root or in a folder.
        (_project("/repo/adguard.yml", "adguard"), "adguard"),
        (_project("/repo/apps/My.Media_App.yaml", "My.Media_App"), "mymedia_app"),
        # A running stack keeps the name it was started with.
        (_project("/repo/adguard.yml", "adguard", running="repo"), "repo"),
    ],
)
def test_compose_project_name(project: Project, expected: str | None) -> None:
    assert repo_service.compose_project_name(project) == expected


def test_project_action_passes_project_name(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("/repo/adguard.yml", "adguard")
    monkeypatch.setattr(repo_service, "discover_projects", lambda: [project])
    monkeypatch.setattr(repo_service, "attach_containers", lambda projects: projects)
    captured: dict[str, Any] = {}

    def runner(compose_path: Path, action: str, *, project_name: str | None = None) -> None:
        captured["project_name"] = project_name

    monkeypatch.setattr("app.api.projects.tasks.project_action_runner", runner)
    monkeypatch.setattr(
        "app.api.projects.job_service.submit",
        lambda kind, label, body: SimpleNamespace(
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
            created_at=NOW,
            started_at=None,
            finished_at=None,
        ),
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        assert TestClient(app).post("/api/projects/p1/up").status_code == 202
    finally:
        app.dependency_overrides.clear()
    assert captured["project_name"] == "adguard"


# --- trivy cache ------------------------------------------------------------------


def test_trivy_cache_on_data(commands: list[list[str]]) -> None:
    trivy_service.scan_image("nginx:latest")

    command = commands[0]
    assert command[command.index("--cache-dir") + 1] == str(settings.data_path / "trivy-cache")


# --- container actions ------------------------------------------------------------


class _FakeContainer:
    name = "web-1"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.called: list[str] = []

    def _act(self, action: str) -> None:
        if self.error:
            raise self.error
        self.called.append(action)

    def kill(self) -> None:
        self._act("kill")

    def pause(self) -> None:
        self._act("pause")

    def unpause(self) -> None:
        self._act("unpause")


@pytest.mark.parametrize("action", ["kill", "pause", "unpause"])
def test_new_container_actions(monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    container = _FakeContainer()
    monkeypatch.setattr(docker_service, "_get_container", lambda container_id: container)

    docker_service.perform_action("abc", action)

    assert container.called == [action]


def test_action_in_wrong_state_is_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    error = APIError(
        "conflict",
        response=SimpleNamespace(status_code=409),  # type: ignore[arg-type]
        explanation="container is not running",
    )
    monkeypatch.setattr(
        docker_service, "_get_container", lambda container_id: _FakeContainer(error)
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        response = TestClient(app).post("/api/containers/abc/kill")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "container is not running" in response.json()["detail"]
