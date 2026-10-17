"""One-click container update: compose helpers, job body and API route."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import containers as containers_api
from app.core.security import get_current_user
from app.main import app
from app.models.job import JobKind
from app.schemas.container import Container
from app.schemas.project import Project
from app.services import compose_service, docker_service, repo_service, tasks

COMPOSE = Path("/repo/web/docker-compose.yml")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _container(cid="abc", name="web-nginx-1", *, service="nginx", project="web", files=None):
    return Container(
        id=cid,
        name=name,
        image="nginx:latest",
        status="running",
        state="running",
        created_at=NOW,
        ports=[],
        compose_project=project if service else None,
        compose_service=service,
        compose_config_files=files,
    )


def _project(pid="web", path=COMPOSE):
    return Project(
        id=pid,
        name=pid,
        compose_path=str(path),
        relative_path=f"{pid}/docker-compose.yml",
        modified_at=NOW,
        services=[],
    )


# --- compose_service ----------------------------------------------------------


@pytest.fixture
def runs(monkeypatch):
    """Record subprocess.run calls; each returns the next queued result."""
    calls = []
    results = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        result = results.pop(0) if results else (0, "", "")
        if isinstance(result, Exception):
            raise result
        code, out, err = result
        return subprocess.CompletedProcess(cmd, code, out, err)

    monkeypatch.setattr(compose_service.subprocess, "run", fake_run)
    return SimpleNamespace(calls=calls, results=results)


def test_pull_service_command(runs):
    compose_service.pull_service(COMPOSE, "nginx", project_name="web")

    [(cmd, kwargs)] = runs.calls
    assert cmd == ["docker", "compose", "-f", str(COMPOSE), "-p", "web", "pull", "nginx"]
    assert kwargs["cwd"] == COMPOSE.parent
    assert kwargs["timeout"] == compose_service.PULL_TIMEOUT


def test_recreate_service_only_touches_that_service(runs):
    compose_service.recreate_service(COMPOSE, "nginx", project_name="web")

    [(cmd, _)] = runs.calls
    assert cmd == [
        "docker",
        "compose",
        "-f",
        str(COMPOSE),
        "-p",
        "web",
        "up",
        "-d",
        "--no-deps",
        "nginx",
    ]


def test_project_name_is_optional(runs):
    compose_service.pull_service(COMPOSE, "nginx")
    assert "-p" not in runs.calls[0][0]


@pytest.mark.parametrize("fn", [compose_service.pull_service, compose_service.recreate_service])
def test_non_zero_exit_raises_with_stderr(runs, fn):
    runs.results.append((1, "", "manifest unknown"))
    with pytest.raises(compose_service.ComposeError, match="manifest unknown"):
        fn(COMPOSE, "nginx")


def test_missing_docker_cli(runs):
    runs.results.append(FileNotFoundError("docker"))
    with pytest.raises(compose_service.ComposeError, match="not found"):
        compose_service.pull_service(COMPOSE, "nginx")


def test_timeout(runs):
    runs.results.append(subprocess.TimeoutExpired("docker", 1800))
    with pytest.raises(compose_service.ComposeError, match="pull` timed out"):
        compose_service.pull_service(COMPOSE, "nginx")


def test_run_action_unchanged(runs):
    runs.results.append((0, "ok", ""))
    result = compose_service.run_action(COMPOSE, "up")

    assert runs.calls[0][0] == ["docker", "compose", "-f", str(COMPOSE), "up", "-d"]
    assert runs.calls[0][1]["timeout"] == compose_service.PULL_TIMEOUT
    assert result == {"action": "up", "exit_code": 0, "stdout": "ok", "stderr": ""}


def test_run_action_reports_failure_instead_of_raising(runs):
    runs.results.append((1, "", "boom"))
    assert compose_service.run_action(COMPOSE, "pull")["exit_code"] == 1


# --- job body -----------------------------------------------------------------


class FakeCtx:
    def __init__(self):
        self.db = object()
        self.total = 0
        self.done = 0
        self.messages = []

    def set_total(self, total, message=None):
        self.total = total
        self.messages.append(message)

    def advance(self, message=None):
        self.done += 1
        self.messages.append(message)

    def note(self, message):
        self.messages.append(message)


@pytest.fixture
def steps(monkeypatch):
    log = []
    monkeypatch.setattr(
        compose_service,
        "pull_service",
        lambda p, s, project_name: log.append(("pull", p, s, project_name)),
    )
    monkeypatch.setattr(
        compose_service,
        "recreate_service",
        lambda p, s, project_name: log.append(("up", p, s, project_name)),
    )
    monkeypatch.setattr(tasks, "store_update_check", lambda db, image: log.append(("check", image)))
    return log


def test_runner_pulls_recreates_then_rechecks(steps):
    ctx = FakeCtx()
    tasks.container_update_runner(COMPOSE, "nginx", "nginx:latest", project_name="web")(ctx)

    assert steps == [
        ("pull", COMPOSE, "nginx", "web"),
        ("up", COMPOSE, "nginx", "web"),
        ("check", "nginx:latest"),
    ]
    assert (ctx.done, ctx.total) == (3, 3)
    assert ctx.messages[-1] == "nginx updated to the latest nginx:latest"


def test_runner_stops_when_pull_fails(steps, monkeypatch):
    def fail(*args, **kwargs):
        raise compose_service.ComposeError("pull failed")

    monkeypatch.setattr(compose_service, "pull_service", fail)

    with pytest.raises(compose_service.ComposeError):
        tasks.container_update_runner(COMPOSE, "nginx", "nginx:latest")(FakeCtx())
    # The running container is left untouched.
    assert steps == []


# --- project_for_container ------------------------------------------------------


def test_project_for_container_matches_by_config_file(monkeypatch):
    monkeypatch.setattr(
        repo_service,
        "discover_projects",
        lambda: [_project("other", Path("/repo/other/compose.yml")), _project()],
    )
    monkeypatch.setattr(
        repo_service.docker_service,
        "list_containers",
        lambda all_states=True: [_container(files=str(COMPOSE))],
    )

    assert repo_service.project_for_container("abc").id == "web"
    assert repo_service.project_for_container("nope") is None


def test_project_for_container_docker_down(monkeypatch):
    def down(all_states=True):
        raise docker_service.DockerUnavailable("down")

    monkeypatch.setattr(repo_service, "discover_projects", lambda: [_project()])
    monkeypatch.setattr(repo_service.docker_service, "list_containers", down)

    assert repo_service.project_for_container("abc") is None


# --- API -------------------------------------------------------------------------


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
        calls.append((kind, label, runner))
        return SimpleNamespace(
            id="job1",
            kind=kind,
            label=label,
            status="pending",
            total=0,
            done=0,
            message=None,
            error=None,
            trigger="manual",
            created_at=NOW,
            started_at=None,
            finished_at=None,
        )

    monkeypatch.setattr(containers_api.job_service, "submit", submit)
    return calls


def test_update_requires_login():
    assert TestClient(app).post("/api/containers/abc/update").status_code == 401


def test_update_queues_job(client, submitted, monkeypatch):
    monkeypatch.setattr(containers_api.docker_service, "get_container", lambda cid: _container())
    monkeypatch.setattr(repo_service, "project_for_container", lambda cid: _project())
    built = {}
    monkeypatch.setattr(
        containers_api.tasks,
        "container_update_runner",
        lambda path, service, image, project_name: (
            built.update(path=path, service=service, image=image, project_name=project_name)
            or "runner"
        ),
    )

    res = client.post("/api/containers/abc/update")

    assert res.status_code == 202
    assert res.json()["id"] == "job1"
    assert submitted == [(JobKind.CONTAINER_UPDATE, "Update web-nginx-1", "runner")]
    assert built == {
        "path": COMPOSE,
        "service": "nginx",
        "image": "nginx:latest",
        "project_name": "web",
    }


def test_update_unknown_container(client, submitted, monkeypatch):
    def missing(cid):
        raise docker_service.DockerNotFound("container x not found")

    monkeypatch.setattr(containers_api.docker_service, "get_container", missing)
    assert client.post("/api/containers/x/update").status_code == 404
    assert submitted == []


def test_update_refuses_plain_container(client, submitted, monkeypatch):
    monkeypatch.setattr(
        containers_api.docker_service, "get_container", lambda cid: _container(service=None)
    )
    res = client.post("/api/containers/abc/update")
    assert res.status_code == 409
    assert "not managed by Docker Compose" in res.json()["detail"]
    assert submitted == []


def test_update_refuses_compose_container_outside_repo(client, submitted, monkeypatch):
    monkeypatch.setattr(containers_api.docker_service, "get_container", lambda cid: _container())
    monkeypatch.setattr(repo_service, "project_for_container", lambda cid: None)
    res = client.post("/api/containers/abc/update")
    assert res.status_code == 409
    assert "No Compose file" in res.json()["detail"]
    assert submitted == []


def test_other_actions_still_routed(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        containers_api.docker_service, "perform_action", lambda cid, a: calls.append((cid, a))
    )
    assert client.post("/api/containers/abc/restart").status_code == 200
    assert calls == [("abc", "restart")]
