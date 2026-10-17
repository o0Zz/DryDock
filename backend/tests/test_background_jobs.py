"""Compose actions and prunes run as background jobs: routes and job bodies."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient

from app.api import images as images_api
from app.api import projects as projects_api
from app.api import volumes as volumes_api
from app.core.security import get_current_user
from app.main import app
from app.models.job import JobKind
from app.schemas.common import PruneResult
from app.schemas.project import Project
from app.services import compose_service, docker_service, tasks
from app.services.job_service import JobRunner

COMPOSE = Path("/repo/web/docker-compose.yml")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


# --- job bodies -------------------------------------------------------------------


class FakeJobContext:
    def __init__(self) -> None:
        self.db = object()
        self.total = 0
        self.done = 0
        self.messages: list[str | None] = []
        self.output: str | None = None

    def set_total(self, total: int, message: str | None = None) -> None:
        self.total = total
        self.messages.append(message)

    def advance(self, message: str | None = None) -> None:
        self.done += 1
        self.messages.append(message)

    def note(self, message: str) -> None:
        self.messages.append(message)

    def set_output(self, output: str) -> None:
        self.output = output


def _action_result(
    monkeypatch: pytest.MonkeyPatch, exit_code: int, stdout: str, stderr: str
) -> list[tuple[Path, str]]:
    calls: list[tuple[Path, str]] = []

    def run_action(
        compose_path: Path, action: str, *, project_name: str | None = None
    ) -> dict[str, str | int]:
        calls.append((compose_path, action))
        return {"action": action, "exit_code": exit_code, "stdout": stdout, "stderr": stderr}

    monkeypatch.setattr(compose_service, "run_action", run_action)
    return calls


def test_project_action_runner_keeps_output(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _action_result(monkeypatch, 0, "", "Container web-1 Started")
    ctx = FakeJobContext()

    tasks.project_action_runner(COMPOSE, "up")(ctx)

    assert calls == [(COMPOSE, "up")]
    assert ctx.output == "Container web-1 Started"
    assert (ctx.done, ctx.total) == (1, 1)


def test_project_action_runner_fails_on_non_zero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    _action_result(monkeypatch, 1, "partial", "pull access denied")
    ctx = FakeJobContext()

    with pytest.raises(compose_service.ComposeError, match="pull access denied"):
        tasks.project_action_runner(COMPOSE, "pull")(ctx)
    # Output is stored before the failure, so the UI can still show it.
    assert ctx.output == "partial\npull access denied"


def test_image_prune_runner_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def prune(*, all_unused: bool) -> PruneResult:
        calls.append(all_unused)
        return PruneResult(deleted=["sha256:a", "sha256:b"], space_reclaimed=3 * 1024 * 1024)

    monkeypatch.setattr(docker_service, "prune_images", prune)
    ctx = FakeJobContext()

    tasks.image_prune_runner(all_unused=True)(ctx)

    assert calls == [True]
    assert ctx.messages == ["Pruned 2 image(s), reclaimed 3.0 MB"]


def test_volume_prune_runner_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_service, "prune_volumes", lambda: PruneResult(deleted=[], space_reclaimed=0)
    )
    ctx = FakeJobContext()

    tasks.volume_prune_runner()(ctx)

    assert ctx.messages == ["Pruned 0 volume(s), reclaimed 0 B"]


def test_network_prune_runner_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_service, "prune_networks", lambda: ["old_default", "tmp"])
    ctx = FakeJobContext()

    tasks.network_prune_runner()(ctx)

    assert ctx.messages == ["Pruned 2 network(s): old_default, tmp"]


def test_prune_runner_propagates_docker_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(**kwargs: Any) -> NoReturn:
        raise docker_service.DockerUnavailable("down")

    monkeypatch.setattr(docker_service, "prune_images", down)
    with pytest.raises(docker_service.DockerUnavailable):
        tasks.image_prune_runner(all_unused=False)(FakeJobContext())


# --- routes -----------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def submit(kind: str, label: str, runner: JobRunner) -> SimpleNamespace:
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
            created_at=NOW,
            started_at=None,
            finished_at=None,
        )

    for module in (projects_api, images_api, volumes_api):
        monkeypatch.setattr(module.job_service, "submit", submit)
    return calls


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch) -> Project:
    web = Project(
        id="web",
        name="web",
        compose_path=str(COMPOSE),
        relative_path="web/docker-compose.yml",
        modified_at=NOW,
        services=[],
    )
    monkeypatch.setattr(projects_api.repo_service, "discover_projects", lambda: [web])
    monkeypatch.setattr(projects_api.repo_service, "attach_containers", lambda projects: projects)
    return web


def test_routes_require_login() -> None:
    anonymous = TestClient(app)
    assert anonymous.post("/api/projects/web/up").status_code == 401
    assert anonymous.post("/api/volumes/prune").status_code == 401
    assert anonymous.post("/api/networks/prune").status_code == 401


@pytest.mark.parametrize("action", sorted(compose_service.ALLOWED_ACTIONS))
def test_project_action_queues_job(
    client: TestClient, submitted: list[tuple[str, str]], project: Project, action: str
) -> None:
    response = client.post(f"/api/projects/web/{action}")

    assert response.status_code == 202
    assert response.json()["id"] == "job1"
    assert submitted == [(JobKind.PROJECT_ACTION, f"{action.capitalize()} web")]


def test_project_action_rejects_unknown_action(
    client: TestClient, submitted: list[tuple[str, str]], project: Project
) -> None:
    assert client.post("/api/projects/web/explode").status_code == 400
    assert submitted == []


def test_project_action_unknown_project(
    client: TestClient, submitted: list[tuple[str, str]], project: Project
) -> None:
    assert client.post("/api/projects/nope/up").status_code == 404
    assert submitted == []


@pytest.mark.parametrize(
    ("query", "label"),
    [("", "Prune dangling images"), ("?all=true", "Prune unused images")],
)
def test_image_prune_queues_job(
    client: TestClient, submitted: list[tuple[str, str]], query: str, label: str
) -> None:
    response = client.post(f"/api/images/prune{query}")

    assert response.status_code == 202
    assert submitted == [(JobKind.IMAGE_PRUNE, label)]


def test_volume_prune_queues_job(client: TestClient, submitted: list[tuple[str, str]]) -> None:
    response = client.post("/api/volumes/prune")

    assert response.status_code == 202
    assert submitted == [(JobKind.VOLUME_PRUNE, "Prune unused volumes")]


def test_network_prune_queues_job(client: TestClient, submitted: list[tuple[str, str]]) -> None:
    response = client.post("/api/networks/prune")

    assert response.status_code == 202
    assert submitted == [(JobKind.NETWORK_PRUNE, "Prune unused networks")]
