"""One-click container update: compose helpers, job body and API route."""

import subprocess
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient

from app.api import containers as containers_api
from app.core.security import get_current_user
from app.main import app
from app.models.job import JobKind
from app.schemas.container import Container
from app.schemas.project import Project
from app.services import compose_service, docker_service, repo_service, tasks
from app.services.job_service import JobRunner

COMPOSE = Path("/repo/web/docker-compose.yml")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _container(
    container_id: str = "abc",
    name: str = "web-nginx-1",
    *,
    service: str | None = "nginx",
    project: str = "web",
    files: str | None = None,
) -> Container:
    return Container(
        id=container_id,
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


def _project(project_id: str = "web", compose_path: Path = COMPOSE) -> Project:
    return Project(
        id=project_id,
        name=project_id,
        compose_path=str(compose_path),
        relative_path=f"{project_id}/docker-compose.yml",
        modified_at=NOW,
        services=[],
    )


# --- compose_service ----------------------------------------------------------


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Record subprocess.run calls; each returns the next queued result."""
    calls: list[tuple[list[str], dict[str, Any]]] = []
    results: list[tuple[int, str, str] | Exception] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        result = results.pop(0) if results else (0, "", "")
        if isinstance(result, Exception):
            raise result
        exit_code, stdout, stderr = result
        return subprocess.CompletedProcess(command, exit_code, stdout, stderr)

    monkeypatch.setattr(compose_service.subprocess, "run", fake_run)
    return SimpleNamespace(calls=calls, results=results)


def test_pull_service_command(runs: SimpleNamespace) -> None:
    compose_service.pull_service(COMPOSE, "nginx", project_name="web")

    [(command, kwargs)] = runs.calls
    base = ["docker", "compose", "-f", str(COMPOSE), "-p", "web"]
    # A `build:` service has nothing to pull; build_service handles it.
    assert command == [*base, "pull", "--ignore-buildable", "nginx"]
    assert kwargs["cwd"] == COMPOSE.parent
    assert kwargs["timeout"] == compose_service.PULL_TIMEOUT


def test_recreate_service_only_touches_that_service(runs: SimpleNamespace) -> None:
    compose_service.recreate_service(COMPOSE, "nginx", project_name="web")

    [(command, _)] = runs.calls
    assert command == [
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


def test_project_name_is_optional(runs: SimpleNamespace) -> None:
    compose_service.pull_service(COMPOSE, "nginx")
    assert "-p" not in runs.calls[0][0]


@pytest.mark.parametrize(
    "compose_step", [compose_service.pull_service, compose_service.recreate_service]
)
def test_non_zero_exit_raises_with_stderr(
    runs: SimpleNamespace, compose_step: Callable[[Path, str], None]
) -> None:
    runs.results.append((1, "", "manifest unknown"))
    with pytest.raises(compose_service.ComposeError, match="manifest unknown"):
        compose_step(COMPOSE, "nginx")


def test_missing_docker_cli(runs: SimpleNamespace) -> None:
    runs.results.append(FileNotFoundError("docker"))
    with pytest.raises(compose_service.ComposeError, match="not found"):
        compose_service.pull_service(COMPOSE, "nginx")


def test_timeout(runs: SimpleNamespace) -> None:
    runs.results.append(subprocess.TimeoutExpired("docker", 1800))
    with pytest.raises(compose_service.ComposeError, match="pull` timed out"):
        compose_service.pull_service(COMPOSE, "nginx")


def test_run_action_unchanged(runs: SimpleNamespace) -> None:
    runs.results.append((0, "ok", ""))
    result = compose_service.run_action(COMPOSE, "up")

    assert runs.calls[0][0] == ["docker", "compose", "-f", str(COMPOSE), "up", "-d"]
    assert runs.calls[0][1]["timeout"] == compose_service.PULL_TIMEOUT
    assert result == {"action": "up", "exit_code": 0, "stdout": "ok", "stderr": ""}


def test_run_action_reports_failure_instead_of_raising(runs: SimpleNamespace) -> None:
    runs.results.append((1, "", "boom"))
    assert compose_service.run_action(COMPOSE, "pull")["exit_code"] == 1


def test_reload_stops_then_ups(runs: SimpleNamespace) -> None:
    runs.results += [(0, "", "Stopped\n"), (0, "", "Recreated\n")]

    result = compose_service.run_action(COMPOSE, "reload", project_name="web")

    base = ["docker", "compose", "-f", str(COMPOSE), "-p", "web"]
    assert [command for command, _ in runs.calls] == [base + ["stop"], base + ["up", "-d"]]
    assert result == {
        "action": "reload",
        "exit_code": 0,
        "stdout": "",
        "stderr": "Stopped\nRecreated\n",
    }


def test_reload_skips_up_when_stop_fails(runs: SimpleNamespace) -> None:
    runs.results.append((1, "", "cannot stop"))

    result = compose_service.run_action(COMPOSE, "reload")

    assert len(runs.calls) == 1
    assert result["exit_code"] == 1
    assert result["stderr"] == "cannot stop"


def test_pull_skips_buildable_services_then_builds(runs: SimpleNamespace) -> None:
    runs.results += [(0, "", "Pulled\n"), (0, "", "Built\n")]

    result = compose_service.run_action(COMPOSE, "pull")

    base = ["docker", "compose", "-f", str(COMPOSE)]
    assert [command for command, _ in runs.calls] == [
        base + ["pull", "--ignore-buildable"],
        base + ["build", "--pull"],
    ]
    # Builds on a Pi are as slow as pulls.
    assert all(kwargs["timeout"] == compose_service.PULL_TIMEOUT for _, kwargs in runs.calls)
    assert result["exit_code"] == 0
    assert result["stderr"] == "Pulled\nBuilt\n"


def test_pull_reports_build_failure(runs: SimpleNamespace) -> None:
    runs.results += [(0, "", "Pulled\n"), (17, "", "failed to solve\n")]

    result = compose_service.run_action(COMPOSE, "pull")

    assert result["exit_code"] == 17
    assert result["stderr"].endswith("failed to solve\n")


def test_restart_is_no_longer_a_project_action() -> None:
    # `docker compose restart` ignores Compose file edits; `reload` replaces it.
    assert "restart" not in compose_service.ALLOWED_ACTIONS
    with pytest.raises(compose_service.ComposeError):
        compose_service.run_action(COMPOSE, "restart")


# --- job body -----------------------------------------------------------------


class FakeJobContext:
    def __init__(self) -> None:
        self.db = object()
        self.total = 0
        self.done = 0
        self.messages: list[str | None] = []

    def set_total(self, total: int, message: str | None = None) -> None:
        self.total = total
        self.messages.append(message)

    def advance(self, message: str | None = None) -> None:
        self.done += 1
        self.messages.append(message)

    def note(self, message: str) -> None:
        self.messages.append(message)


@pytest.fixture
def steps(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    log: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        compose_service,
        "pull_service",
        lambda compose_path, service, project_name: log.append(
            ("pull", compose_path, service, project_name)
        ),
    )
    monkeypatch.setattr(
        compose_service,
        "build_service",
        lambda compose_path, service, project_name: log.append(
            ("build", compose_path, service, project_name)
        ),
    )
    monkeypatch.setattr(
        compose_service,
        "recreate_service",
        lambda compose_path, service, project_name, ctx: log.append(
            ("up", compose_path, service, project_name)
        ),
    )
    monkeypatch.setattr(tasks, "git_images", lambda compose_path=None: {})
    monkeypatch.setattr(
        tasks,
        "store_update_check",
        lambda db, image, git=None, built=False: log.append(("check", image, built)),
    )
    return log


def test_runner_pulls_recreates_then_rechecks(steps: list[tuple[Any, ...]]) -> None:
    ctx = FakeJobContext()
    tasks.container_update_runner(COMPOSE, "nginx", "nginx:latest", project_name="web")(ctx)

    assert steps == [
        ("pull", COMPOSE, "nginx", "web"),
        ("build", COMPOSE, "nginx", "web"),
        ("up", COMPOSE, "nginx", "web"),
        ("check", "nginx:latest", False),
    ]
    assert (ctx.done, ctx.total) == (4, 4)
    assert ctx.messages[-1] == "nginx updated to the latest nginx:latest"


def test_runner_stops_when_pull_fails(
    steps: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> NoReturn:
        raise compose_service.ComposeError("pull failed")

    monkeypatch.setattr(compose_service, "pull_service", fail)

    with pytest.raises(compose_service.ComposeError):
        tasks.container_update_runner(COMPOSE, "nginx", "nginx:latest")(FakeJobContext())
    # The running container is left untouched.
    assert steps == []


# --- project_for_container ------------------------------------------------------


def test_project_for_container_matches_by_config_file(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_project_for_container_docker_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(all_states: bool = True) -> NoReturn:
        raise docker_service.DockerUnavailable("down")

    monkeypatch.setattr(repo_service, "discover_projects", lambda: [_project()])
    monkeypatch.setattr(repo_service.docker_service, "list_containers", down)

    assert repo_service.project_for_container("abc") is None


# --- API -------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, JobRunner]]:
    calls: list[tuple[str, str, JobRunner]] = []

    def submit(kind: str, label: str, runner: JobRunner) -> SimpleNamespace:
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


def test_update_requires_login() -> None:
    assert TestClient(app).post("/api/containers/abc/update").status_code == 401


def test_update_queues_job(
    client: TestClient,
    submitted: list[tuple[str, str, JobRunner]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        containers_api.docker_service, "get_container", lambda container_id: _container()
    )
    monkeypatch.setattr(repo_service, "project_for_container", lambda container_id: _project())
    built: dict[str, Any] = {}
    monkeypatch.setattr(
        containers_api.tasks,
        "container_update_runner",
        lambda compose_path, service, image, project_name: (
            built.update(
                compose_path=compose_path, service=service, image=image, project_name=project_name
            )
            or "runner"
        ),
    )

    response = client.post("/api/containers/abc/update")

    assert response.status_code == 202
    assert response.json()["id"] == "job1"
    assert submitted == [(JobKind.CONTAINER_UPDATE, "Update web-nginx-1", "runner")]
    assert built == {
        "compose_path": COMPOSE,
        "service": "nginx",
        "image": "nginx:latest",
        "project_name": "web",
    }


def test_update_unknown_container(
    client: TestClient,
    submitted: list[tuple[str, str, JobRunner]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(container_id: str) -> NoReturn:
        raise docker_service.DockerNotFound("container x not found")

    monkeypatch.setattr(containers_api.docker_service, "get_container", missing)
    assert client.post("/api/containers/x/update").status_code == 404
    assert submitted == []


def test_update_refuses_plain_container(
    client: TestClient,
    submitted: list[tuple[str, str, JobRunner]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        containers_api.docker_service,
        "get_container",
        lambda container_id: _container(service=None),
    )
    response = client.post("/api/containers/abc/update")
    assert response.status_code == 409
    assert "not managed by Docker Compose" in response.json()["detail"]
    assert submitted == []


def test_update_refuses_compose_container_outside_repo(
    client: TestClient,
    submitted: list[tuple[str, str, JobRunner]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        containers_api.docker_service, "get_container", lambda container_id: _container()
    )
    monkeypatch.setattr(repo_service, "project_for_container", lambda container_id: None)
    response = client.post("/api/containers/abc/update")
    assert response.status_code == 409
    assert "No Compose file" in response.json()["detail"]
    assert submitted == []


def test_other_actions_still_routed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        containers_api.docker_service,
        "perform_action",
        lambda container_id, action: calls.append((container_id, action)),
    )
    assert client.post("/api/containers/abc/restart").status_code == 200
    assert calls == [("abc", "restart")]
