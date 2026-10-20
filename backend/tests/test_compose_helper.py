"""Compose jobs run in a helper container, and a restart resumes them."""

import shlex
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from docker.errors import NotFound
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.job import Job, JobKind, JobStatus
from app.services import compose_service, docker_service, host_path_service, job_service, tasks

COMPOSE = Path("/repo/web/docker-compose.yml")


class FakeJobContext:
    def __init__(self) -> None:
        self.job = SimpleNamespace(id="job1", total=1, done=0)
        self.outputs: list[str] = []
        self.messages: list[str] = []

    def set_output(self, output: str) -> None:
        self.outputs.append(output)

    def note(self, message: str) -> None:
        self.messages.append(message)


@pytest.fixture
def helper(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """DryDock runs in container `self`; the helper prints `output` and exits with `exit_code`."""
    state = SimpleNamespace(started=[], removed=[], exit_code=0, output="Recreated\n")
    monkeypatch.setattr(host_path_service, "own_container_id", lambda: "self")
    monkeypatch.setattr(docker_service, "container_image", lambda container_id: "sha256:dd")
    monkeypatch.setattr(compose_service.registry_auth_service, "subprocess_env", lambda: None)

    def start(script: str, **kwargs: Any) -> str:
        state.started.append((script, kwargs))
        return "helper1"

    def follow(
        helper_id: str,
        on_output: Callable[[str], None],
        *,
        timeout: float,
        stop: threading.Event,
    ) -> int | None:
        state.timeout = timeout
        on_output(state.output)
        return state.exit_code

    monkeypatch.setattr(docker_service, "start_compose_helper", start)
    monkeypatch.setattr(docker_service, "follow_helper", follow)
    monkeypatch.setattr(docker_service, "remove_helper", state.removed.append)
    return state


def test_job_runs_all_steps_in_one_helper(helper: SimpleNamespace) -> None:
    ctx = FakeJobContext()

    result = compose_service.run_action(COMPOSE, "reload", project_name="web", ctx=ctx)

    [(script, kwargs)] = helper.started
    base = shlex.join(["docker", "compose", "-f", str(COMPOSE), "-p", "web"])
    # Both steps in one helper: a `stop` of DryDock's own stack must still be followed by `up`.
    assert script == f"{base} stop && {base} up -d"
    assert kwargs["job_id"] == "job1" and kwargs["parent_id"] == "self"
    assert helper.timeout == 300 + compose_service.PULL_TIMEOUT
    assert ctx.outputs == ["Recreated\n"]
    assert result["exit_code"] == 0 and result["stderr"] == "Recreated\n"
    assert helper.removed == ["helper1"]


def test_helper_failure_raises_for_single_steps(helper: SimpleNamespace) -> None:
    helper.exit_code, helper.output = 1, "no such service\n"

    with pytest.raises(compose_service.ComposeError, match="no such service"):
        compose_service.recreate_service(COMPOSE, "nginx", ctx=FakeJobContext())
    assert helper.removed == ["helper1"]


def test_shutdown_leaves_the_helper_running(helper: SimpleNamespace) -> None:
    helper.exit_code = None  # follow_helper saw the stop event

    with pytest.raises(job_service.Interrupted):
        compose_service.run_action(COMPOSE, "up", ctx=FakeJobContext())
    assert helper.removed == []


def test_without_a_job_compose_runs_locally(
    helper: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        compose_service,
        "_compose",
        lambda compose_path, args, **kwargs: (
            calls.append(args) or SimpleNamespace(stdout="", stderr="", returncode=0)
        ),
    )

    compose_service.run_action(COMPOSE, "up")

    assert calls == [["up", "-d"]] and helper.started == []


def test_outside_docker_compose_runs_locally(
    helper: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host_path_service, "own_container_id", lambda: None)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        compose_service,
        "_compose",
        lambda compose_path, args, **kwargs: (
            calls.append(args) or SimpleNamespace(stdout="", stderr="", returncode=0)
        ),
    )

    compose_service.run_action(COMPOSE, "up", ctx=FakeJobContext())

    assert calls == [["up", "-d"]] and helper.started == []


# --- restart ------------------------------------------------------------------


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """In-memory jobs table; `resume` records what it would run instead of running it."""
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(job_service, "SessionLocal", sessionmaker(bind=engine))
    with job_service.SessionLocal() as db:
        db.add_all(
            [
                Job(id="a", kind=JobKind.CONTAINER_UPDATE, label="up", status=JobStatus.RUNNING),
                Job(id="b", kind=JobKind.PROJECT_ACTION, label="pull", status=JobStatus.RUNNING),
                Job(id="c", kind=JobKind.PROJECT_ACTION, label="old", status=JobStatus.SUCCESS),
            ]
        )
        db.commit()
    submitted: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        job_service._executor, "submit", lambda fn, job_id, runner: submitted.append(job_id)
    )
    return submitted


def test_restart_resumes_jobs_whose_helper_survived(
    jobs: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[str] = []
    monkeypatch.setattr(docker_service, "compose_helpers", lambda: {"a": "h-a", "c": "h-c"})
    monkeypatch.setattr(docker_service, "remove_helper", removed.append)

    resumed = tasks.resume_compose_jobs()
    failed = job_service.fail_interrupted(keep=resumed)

    assert resumed == {"a"} and jobs == ["a"]
    # The finished job's helper is clutter.
    assert removed == ["h-c"]
    assert failed == 1
    with job_service.SessionLocal() as db:
        assert db.get(Job, "a").status == JobStatus.RUNNING
        assert db.get(Job, "b").status == JobStatus.ERROR


def test_resumed_job_finishes_from_the_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_service, "follow", lambda helper_id, ctx: (0, "Started\n"))
    ctx = FakeJobContext()
    ctx.job.total = 3

    tasks._resume_runner("h-a")(ctx)

    assert ctx.job.done == 3
    monkeypatch.setattr(compose_service, "follow", lambda helper_id, ctx: (2, "port in use\n"))
    with pytest.raises(compose_service.ComposeError, match="port in use"):
        tasks._resume_runner("h-a")(FakeJobContext())


def test_interrupted_job_stays_running(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(job_service, "SessionLocal", sessionmaker(bind=engine))
    with job_service.SessionLocal() as db:
        db.add(Job(id="a", kind=JobKind.PROJECT_ACTION, label="up", status=JobStatus.PENDING))
        db.commit()

    def runner(ctx: job_service.JobContext) -> None:
        raise job_service.Interrupted("shutting down")

    job_service._run("a", runner)

    with job_service.SessionLocal() as db:
        assert db.get(Job, "a").status == JobStatus.RUNNING


# --- helper image -------------------------------------------------------------


class FakeDocker:
    """Docker with one DryDock container and the images in `present`."""

    def __init__(self, present: set[str]) -> None:
        self.present = present
        self.created: list[dict[str, Any]] = []
        self.started = 0
        self.images = SimpleNamespace(get=self._image)
        self.containers = SimpleNamespace(get=self._container, create=self._create)

    def _image(self, reference: str) -> object:
        if reference not in self.present:
            raise NotFound("no such image")
        return object()

    def _container(self, container_id: str) -> SimpleNamespace:
        attrs = {
            "Image": "sha256:old",
            "Config": {"Image": "drydock/drydock:latest", "User": ""},
            "HostConfig": {},
        }
        return SimpleNamespace(id=container_id, attrs=attrs)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.created.append(kwargs)

        def start() -> None:
            self.started += 1

        return SimpleNamespace(id="helper1", start=start)


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        ({"sha256:old", "drydock/drydock:latest"}, "sha256:old"),
        # The tag was rebuilt and the old image removed while DryDock still runs on it.
        ({"drydock/drydock:latest"}, "drydock/drydock:latest"),
        (set(), None),
    ],
)
def test_helper_image_falls_back_to_the_tag(
    monkeypatch: pytest.MonkeyPatch, present: set[str], expected: str | None
) -> None:
    monkeypatch.setattr(docker_service, "_client", lambda: FakeDocker(present))
    assert docker_service.container_image("self") == expected


def test_helper_is_created_never_pulled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeDocker({"drydock/drydock:latest"})
    monkeypatch.setattr(docker_service, "_client", lambda: fake)

    helper = docker_service.start_compose_helper(
        "docker compose up -d",
        job_id="j",
        parent_id="self",
        mounts=[],
        working_dir="/repo",
        environment={},
    )

    assert helper == "helper1" and fake.started == 1
    [kwargs] = fake.created
    assert kwargs["image"] == "drydock/drydock:latest"


def test_no_local_image_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_service, "_client", lambda: FakeDocker(set()))
    with pytest.raises(docker_service.DockerNotFound, match="no local image"):
        docker_service.start_compose_helper(
            "true", job_id="j", parent_id="self", mounts=[], working_dir="/", environment={}
        )
