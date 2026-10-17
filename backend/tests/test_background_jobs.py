"""Compose actions and prunes run as background jobs: routes and job bodies."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import images as images_api
from app.api import projects as projects_api
from app.api import volumes as volumes_api
from app.core.security import get_current_user
from app.main import app
from app.models.job import JobKind
from app.schemas.project import Project
from app.schemas.volume import PruneResult
from app.services import compose_service, docker_service, tasks

COMPOSE = Path("/repo/web/docker-compose.yml")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


# --- job bodies -------------------------------------------------------------------


class FakeCtx:
    def __init__(self):
        self.db = object()
        self.total = 0
        self.done = 0
        self.messages = []
        self.output = None

    def set_total(self, total, message=None):
        self.total = total
        self.messages.append(message)

    def advance(self, message=None):
        self.done += 1
        self.messages.append(message)

    def note(self, message):
        self.messages.append(message)

    def set_output(self, output):
        self.output = output


def _action_result(monkeypatch, code, out, err):
    calls = []

    def run_action(path, action):
        calls.append((path, action))
        return {"action": action, "exit_code": code, "stdout": out, "stderr": err}

    monkeypatch.setattr(compose_service, "run_action", run_action)
    return calls


def test_project_action_runner_keeps_output(monkeypatch):
    calls = _action_result(monkeypatch, 0, "", "Container web-1 Started")
    ctx = FakeCtx()

    tasks.project_action_runner(COMPOSE, "up")(ctx)

    assert calls == [(COMPOSE, "up")]
    assert ctx.output == "Container web-1 Started"
    assert (ctx.done, ctx.total) == (1, 1)


def test_project_action_runner_fails_on_non_zero_exit(monkeypatch):
    _action_result(monkeypatch, 1, "partial", "pull access denied")
    ctx = FakeCtx()

    with pytest.raises(compose_service.ComposeError, match="pull access denied"):
        tasks.project_action_runner(COMPOSE, "pull")(ctx)
    # Output is stored before the failure, so the UI can still show it.
    assert ctx.output == "partial\npull access denied"


def test_image_prune_runner_summary(monkeypatch):
    calls = []

    def prune(*, all_unused):
        calls.append(all_unused)
        return PruneResult(deleted=["sha256:a", "sha256:b"], space_reclaimed=3 * 1024 * 1024)

    monkeypatch.setattr(docker_service, "prune_images", prune)
    ctx = FakeCtx()

    tasks.image_prune_runner(all_unused=True)(ctx)

    assert calls == [True]
    assert ctx.messages == ["Pruned 2 image(s), reclaimed 3.0 MB"]


def test_volume_prune_runner_summary(monkeypatch):
    monkeypatch.setattr(
        docker_service, "prune_volumes", lambda: PruneResult(deleted=[], space_reclaimed=0)
    )
    ctx = FakeCtx()

    tasks.volume_prune_runner()(ctx)

    assert ctx.messages == ["Pruned 0 volume(s), reclaimed 0 B"]


def test_prune_runner_propagates_docker_down(monkeypatch):
    def down(**kwargs):
        raise docker_service.DockerUnavailable("down")

    monkeypatch.setattr(docker_service, "prune_images", down)
    with pytest.raises(docker_service.DockerUnavailable):
        tasks.image_prune_runner(all_unused=False)(FakeCtx())


# --- routes -----------------------------------------------------------------------


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def submitted(monkeypatch):
    calls = []

    def submit(kind, label, runner):
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
def project(monkeypatch):
    web = Project(
        id="web",
        name="web",
        compose_path=str(COMPOSE),
        relative_path="web/docker-compose.yml",
        modified_at=NOW,
        services=[],
    )
    monkeypatch.setattr(projects_api.repo_service, "discover_projects", lambda: [web])
    return web


def test_routes_require_login():
    anon = TestClient(app)
    assert anon.post("/api/projects/web/up").status_code == 401
    assert anon.post("/api/volumes/prune").status_code == 401


@pytest.mark.parametrize("action", sorted(compose_service.ALLOWED_ACTIONS))
def test_project_action_queues_job(client, submitted, project, action):
    res = client.post(f"/api/projects/web/{action}")

    assert res.status_code == 202
    assert res.json()["id"] == "job1"
    assert submitted == [(JobKind.PROJECT_ACTION, f"{action.capitalize()} web")]


def test_project_action_rejects_unknown_action(client, submitted, project):
    assert client.post("/api/projects/web/explode").status_code == 400
    assert submitted == []


def test_project_action_unknown_project(client, submitted, project):
    assert client.post("/api/projects/nope/up").status_code == 404
    assert submitted == []


@pytest.mark.parametrize(
    ("query", "label"),
    [("", "Prune dangling images"), ("?all=true", "Prune unused images")],
)
def test_image_prune_queues_job(client, submitted, query, label):
    res = client.post(f"/api/images/prune{query}")

    assert res.status_code == 202
    assert submitted == [(JobKind.IMAGE_PRUNE, label)]


def test_volume_prune_queues_job(client, submitted):
    res = client.post("/api/volumes/prune")

    assert res.status_code == 202
    assert submitted == [(JobKind.VOLUME_PRUNE, "Prune unused volumes")]
