"""Scheduled auto-update of the services labelled `drydock.update=auto`."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import updates as updates_api
from app.models.job import JobKind
from app.schemas.container import Container
from app.schemas.project import Project
from app.services import compose_service, docker_service, repo_service, tasks

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LABEL = "drydock.update=auto"


def _container(
    container_id: str,
    service: str,
    *,
    project: str = "infra",
    image: str | None = None,
    state: str = "running",
    health: str | None = None,
    restarts: int = 0,
) -> Container:
    return Container(
        id=container_id,
        name=f"{project}-{service}-1",
        image=image or f"{service}:latest",
        status=state,
        state=state,
        created_at=NOW,
        ports=[],
        compose_project=project,
        compose_service=service,
        restart_count=restarts,
        health=health,
        auto_update=True,
    )


def _project(name: str, containers: list[Container]) -> Project:
    return Project(
        id=name,
        name=name,
        compose_path=f"/repo/{name}/docker-compose.yml",
        relative_path=f"{name}/docker-compose.yml",
        modified_at=NOW,
        services=[],
        containers=containers,
    )


class FakeJobContext:
    def __init__(self) -> None:
        self.db = object()
        self.total = 0
        self.done = 0
        self.output = ""
        self.messages: list[str | None] = []

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


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A fake host: labelled containers, their projects, update checks and Compose steps."""
    state = SimpleNamespace(
        labelled=[],  # what the label filter returns
        after={},  # service -> containers seen after the recreate
        projects=[],
        updates={},  # image -> (update_available, error)
        own=None,
        steps=[],
        notified=[],
        list_calls=[],
    )

    def list_containers(*, all_states: bool = True, label: str | None = None) -> list[Container]:
        state.list_calls.append((all_states, label))
        if label == LABEL:
            return state.labelled
        service = (label or "").removeprefix("com.docker.compose.service=")
        return state.after.get(service, [])

    def store_update_check(db: Any, image: str, git: Any = None, built: bool = False) -> Any:
        state.steps.append(("check", image, built))
        available, error = state.updates.get(image, (False, None))
        return SimpleNamespace(update_available=available and not built, error=error)

    def step(name: str) -> Any:
        return lambda compose_path, service, project_name, **_: state.steps.append(
            (name, service)
        )

    monkeypatch.setattr(docker_service, "list_containers", list_containers)
    monkeypatch.setattr(repo_service, "discover_projects", lambda: state.projects)
    monkeypatch.setattr(repo_service, "attach_containers", lambda projects: projects)
    monkeypatch.setattr(tasks.host_path_service, "own_container_id", lambda: state.own)
    monkeypatch.setattr(tasks, "git_images", lambda compose_path=None: {})
    monkeypatch.setattr(tasks, "store_update_check", store_update_check)
    monkeypatch.setattr(compose_service, "pull_service", step("pull"))
    monkeypatch.setattr(compose_service, "build_service", step("build"))
    monkeypatch.setattr(compose_service, "recreate_service", step("up"))
    monkeypatch.setattr(tasks.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(tasks, "AUTO_UPDATE_HEALTH_TIMEOUT", 0)
    monkeypatch.setattr(
        tasks,
        "_notify",
        lambda db, flag, event, payload: state.notified.append((event, payload)),
    )
    return state


def _setup(host: SimpleNamespace, *containers: Container) -> None:
    host.labelled = list(containers)
    by_project: dict[str, list[Container]] = {}
    for container in containers:
        by_project.setdefault(container.compose_project or "", []).append(container)
    host.projects = [_project(name, members) for name, members in by_project.items()]
    for container in containers:
        host.after.setdefault(container.compose_service, [container])


def test_updates_only_services_with_a_same_tag_update(host: SimpleNamespace) -> None:
    _setup(host, _container("a", "traefik"), _container("b", "swag"))
    host.updates = {"traefik:latest": (True, None)}
    ctx = FakeJobContext()

    tasks.auto_update_runner(notify=True)(ctx)

    assert host.steps == [
        ("check", "swag:latest", False),
        ("check", "traefik:latest", False),
        ("pull", "traefik"),
        ("build", "traefik"),
        ("up", "traefik"),
        # The re-check clears the badge; `built` is only for git images.
        ("check", "traefik:latest", False),
    ]
    # Stopped containers never count: an update must not start a stack.
    assert host.list_calls[0] == (False, LABEL)
    assert ctx.output == "infra/swag: up to date\ninfra/traefik: updated"
    assert host.notified == [("update.applied", {"updated": ["infra/traefik"], "failed": []})]


def test_nothing_to_update_sends_nothing(host: SimpleNamespace) -> None:
    _setup(host, _container("a", "traefik"))
    tasks.auto_update_runner(notify=True)(FakeJobContext())
    assert host.notified == []
    assert ("pull", "traefik") not in host.steps


def test_failed_check_skips_the_service(host: SimpleNamespace) -> None:
    _setup(host, _container("a", "traefik"))
    host.updates = {"traefik:latest": (True, "registry down")}
    ctx = FakeJobContext()
    tasks.auto_update_runner()(ctx)
    assert ("pull", "traefik") not in host.steps
    assert "skipped, update check failed: registry down" in ctx.output


def test_scaled_service_is_updated_once(host: SimpleNamespace) -> None:
    _setup(host, _container("a", "worker"), _container("b", "worker"))
    host.updates = {"worker:latest": (True, None)}
    tasks.auto_update_runner()(FakeJobContext())
    assert host.steps.count(("up", "worker")) == 1


def test_container_outside_the_repo_is_skipped(host: SimpleNamespace) -> None:
    stray = _container("a", "traefik")
    host.labelled = [stray]
    ctx = FakeJobContext()
    tasks.auto_update_runner()(ctx)
    assert ctx.total == 0
    assert "no Compose file in the repo matches it" in ctx.output


@pytest.mark.parametrize(
    ("after", "problem"),
    [
        ([], "no container after the recreate"),
        ([_container("n", "app", state="exited")], "infra-app-1 is exited"),
        ([_container("n", "app", restarts=2)], "infra-app-1 restarted 2 time(s)"),
        ([_container("n", "app", health="unhealthy")], "infra-app-1 is unhealthy"),
    ],
)
def test_service_that_does_not_come_up_fails_the_job(
    host: SimpleNamespace, after: list[Container], problem: str
) -> None:
    _setup(host, _container("a", "app"), _container("b", "proxy"))
    host.after["app"] = after
    host.updates = {"app:latest": (True, None), "proxy:latest": (True, None)}
    ctx = FakeJobContext()

    with pytest.raises(tasks.AutoUpdateFailed, match="1 of 2 update"):
        tasks.auto_update_runner(notify=True)(ctx)

    # One failure does not stop the others.
    assert ("up", "proxy") in host.steps
    assert f"infra/app: failed: {problem}" in ctx.output
    assert host.notified == [
        (
            "update.applied",
            {"updated": ["infra/proxy"], "failed": [{"service": "infra/app", "error": problem}]},
        )
    ]


def test_compose_failure_is_reported(
    host: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(host, _container("a", "app"))
    host.updates = {"app:latest": (True, None)}

    def fail(*args: Any, **kwargs: Any) -> None:
        raise compose_service.ComposeError("pull access denied")

    monkeypatch.setattr(compose_service, "pull_service", fail)
    ctx = FakeJobContext()
    with pytest.raises(tasks.AutoUpdateFailed):
        tasks.auto_update_runner()(ctx)
    assert "infra/app: failed: pull access denied" in ctx.output


def test_drydock_itself_goes_last_and_reports_first(
    host: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(
        host,
        _container("aaa111", "drydock", image="ghcr.io/o0zz/drydock:latest"),
        _container("bbb222", "traefik"),
    )
    host.own = "aaa111"
    host.updates = {"ghcr.io/o0zz/drydock:latest": (True, None), "traefik:latest": (True, None)}

    def recreate(compose_path: Path, service: str, project_name: str | None, **_: Any) -> None:
        host.steps.append(("up", service))
        if service == "drydock":
            # Compose stopping DryDock: nothing after this point runs.
            assert host.notified, "the summary must go out before DryDock stops"

    monkeypatch.setattr(compose_service, "recreate_service", recreate)
    tasks.auto_update_runner(notify=True)(FakeJobContext())

    ups = [step for step in host.steps if step[0] == "up"]
    assert ups == [("up", "traefik"), ("up", "drydock")]
    assert host.notified[0][1]["updated"] == ["infra/traefik", "infra/drydock"]


def test_label_sets_the_flag() -> None:
    attrs = {
        "Config": {"Labels": {"drydock.update": "auto"}, "Image": "traefik:v3"},
        "Created": "2026-01-01T00:00:00Z",
        "State": {"Status": "running"},
    }
    container = SimpleNamespace(id="a", name="t", status="running", attrs=attrs, image=None)
    assert docker_service._to_schema(container).auto_update is True  # type: ignore[arg-type]
    attrs["Config"]["Labels"] = {"drydock.update": "manual"}
    assert docker_service._to_schema(container).auto_update is False  # type: ignore[arg-type]


def test_route_queues_the_job(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: list[tuple[str, str]] = []

    def submit(kind: str, label: str, runner: Any, **_: Any) -> SimpleNamespace:
        submitted.append((kind, label))
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

    monkeypatch.setattr(updates_api.job_service, "submit", submit)
    response = client.post("/api/updates/auto")
    assert response.status_code == 202
    assert submitted == [(JobKind.AUTO_UPDATE, tasks.AUTO_UPDATE_LABEL)]


def test_auto_update_hour_is_bounded(client: TestClient) -> None:
    assert client.put("/api/settings", json={"auto_update_hour": 24}).status_code == 422
