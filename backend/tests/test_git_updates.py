"""Update checks for services built from a git repo."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.schemas.container import Container
from app.schemas.project import Project, ProjectService
from app.services import git_service, tasks
from app.services.git_service import GitSource

OLD = "a" * 40
NEW = "b" * 40
TAG_OBJECT = "c" * 40
REPO = "https://git.example.com/me/app.git"


def _pkt(line: str) -> bytes:
    data = line.encode() + b"\n"
    return f"{len(data) + 4:04x}".encode() + data


def _advertisement(head: str = NEW) -> bytes:
    return b"".join(
        [
            _pkt("# service=git-upload-pack"),
            b"0000",
            _pkt(f"{head} HEAD\0multi_ack symref=HEAD:refs/heads/main"),
            _pkt(f"{head} refs/heads/main"),
            _pkt(f"{OLD} refs/heads/old"),
            _pkt(f"{TAG_OBJECT} refs/tags/v1.0"),
            _pkt(f"{OLD} refs/tags/v1.0^{{}}"),
            b"0000",
        ]
    )


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fake git host: answers /info/refs with `body` and `status`."""
    state: dict[str, Any] = {"status": 200, "body": _advertisement(), "urls": []}

    def get(url: str, **kwargs: Any) -> httpx.Response:
        state["urls"].append((url, kwargs.get("params")))
        return httpx.Response(state["status"], content=state["body"])

    monkeypatch.setattr(git_service.httpx, "get", get)
    return state


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (f"{REPO}#main", GitSource(REPO, "main")),
        ({"context": f"{REPO}#v1.0:docker"}, GitSource(REPO, "v1.0")),
        (REPO, GitSource(REPO, None)),
        ("git@github.com:me/app.git", GitSource("git@github.com:me/app.git", None)),
        (".", None),
        ({"context": "./app", "dockerfile": "Dockerfile"}, None),
        ("https://example.com/context.tar.gz", None),
        (None, None),
    ],
)
def test_parse_build(build: object, expected: GitSource | None) -> None:
    assert git_service.parse_build(build) == expected


@pytest.mark.parametrize(
    ("ref", "commit"),
    [(None, NEW), ("main", NEW), ("old", OLD), ("v1.0", OLD)],  # a tag resolves to its commit
)
def test_remote_commit(server: dict[str, Any], ref: str | None, commit: str) -> None:
    assert git_service.remote_commit(GitSource(REPO, ref)) == commit
    assert server["urls"] == [(f"{REPO}/info/refs", {"service": "git-upload-pack"})]


def test_pinned_commit_needs_no_request(server: dict[str, Any]) -> None:
    assert git_service.remote_commit(GitSource(REPO, OLD)) == OLD
    assert server["urls"] == []


@pytest.mark.parametrize(
    ("status", "source", "message"),
    [
        (401, GitSource(REPO), "needs a login"),
        (404, GitSource(REPO), "HTTP 404"),
        (200, GitSource(REPO, "nope"), "ref nope not found"),
        (200, GitSource("git@github.com:me/app.git"), "only http"),
    ],
)
def test_remote_commit_errors(
    server: dict[str, Any], status: int, source: GitSource, message: str
) -> None:
    server["status"] = status
    with pytest.raises(git_service.GitError, match=message):
        git_service.remote_commit(source)


# --- stored checks --------------------------------------------------------------


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_new_commit_shows_as_update_until_rebuilt(server: dict[str, Any], db: Session) -> None:
    source = GitSource(REPO, "main")
    server["body"] = _advertisement(head=OLD)

    # Built before DryDock tracked it: the current commit is the baseline.
    first = tasks.store_update_check(db, "web-app", git=source)
    assert (first.local_digest, first.update_available) == (OLD, False)
    assert first.git_source == f"{REPO}#main"

    server["body"] = _advertisement(head=NEW)
    pushed = tasks.store_update_check(db, "web-app", git=source)
    assert (pushed.local_digest, pushed.remote_digest, pushed.has_update) == (OLD, NEW, True)

    # An unrelated failure keeps the baseline for the next check.
    server["status"] = 503
    failed = tasks.store_update_check(db, "web-app", git=source)
    assert failed.local_digest == OLD and failed.error

    server["status"] = 200
    rebuilt = tasks.store_update_check(db, "web-app", git=source, built=True)
    assert (rebuilt.local_digest, rebuilt.update_available) == (NEW, False)


def test_registry_checks_do_not_seed_a_git_baseline(
    server: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A registry check's digest is not a commit, so it is not taken as the built commit.
    monkeypatch.setattr(
        tasks.update_service,
        "check_image",
        lambda image: tasks.update_service.UpdateResult(image=image, local_digest="sha256:x"),
    )
    tasks.store_update_check(db, "web-app")

    check = tasks.store_update_check(db, "web-app", git=GitSource(REPO, "main"))
    assert check.local_digest == NEW and not check.update_available


def test_git_images_names_built_services_by_their_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project(
        id="p",
        name="streamity",
        compose_path="/repo/streamity.yml",
        relative_path="streamity.yml",
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
        services=[
            ProjectService(name="app", git_source=f"{REPO}#main"),
            ProjectService(name="api", image="me/api:dev", git_source=REPO),
            ProjectService(name="db", image="postgres:16"),
        ],
    )
    container = Container(
        id="c1",
        name="streamity",
        image="docker-app",  # the name Compose picked, since `app` has no image:
        status="running",
        state="running",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ports=[],
        compose_service="app",
    )
    monkeypatch.setattr(tasks.repo_service, "discover_projects", lambda: [project])
    monkeypatch.setattr(
        tasks.repo_service,
        "attach_containers",
        lambda projects: [p.model_copy(update={"containers": [container]}) for p in projects],
    )

    assert tasks.git_images() == {
        "docker-app": GitSource(REPO, "main"),
        "me/api:dev": GitSource(REPO, None),
    }
