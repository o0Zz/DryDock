"""/api/dashboard counts, with Docker, the repo and the history tables stubbed out."""

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import dashboard as dashboard_api
from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.schemas.container import Container
from app.schemas.dashboard import HostInfo
from app.services import docker_service

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    app.dependency_overrides[get_db] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _container(name: str, state: str, status: str) -> Container:
    return Container(
        id=name, name=name, image="nginx", status=status, state=state, created_at=NOW, ports=[]
    )


def _scan(image: str, critical: int, high: int) -> SimpleNamespace:
    return SimpleNamespace(image=image, critical=critical, high=high, scanned_at=NOW)


def _check(image: str, *, rebuilt: bool, newest_tag: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        image=image,
        update_available=rebuilt,
        newest_tag=newest_tag,
        has_update=rebuilt or bool(newest_tag),
        checked_at=NOW,
    )


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    containers = [
        _container("web", "running", "Up 2 hours"),
        _container("db", "running", "Up 2 hours (unhealthy)"),
        _container("worker", "restarting", "Restarting (1) 5 seconds ago"),
        _container("old", "exited", "Exited (0) 3 days ago"),
    ]
    monkeypatch.setattr(dashboard_api.repo_service, "discover_projects", lambda: [])
    monkeypatch.setattr(docker_service, "list_containers", lambda all_states: containers)
    monkeypatch.setattr(docker_service, "list_volumes", lambda: [])
    monkeypatch.setattr(docker_service, "host_info", lambda: HostInfo(cpus=4))
    monkeypatch.setattr(
        dashboard_api.tasks, "all_known_images", lambda: ["nginx:1.27", "postgres:16"]
    )
    monkeypatch.setattr(
        dashboard_api.history_service,
        "scans",
        lambda db: [
            _scan("nginx:1.27", critical=2, high=5),
            _scan("postgres:16", critical=0, high=1),
            # Replaced by nginx:1.27, so its findings no longer count.
            _scan("nginx:1.25", critical=9, high=9),
        ],
    )
    monkeypatch.setattr(
        dashboard_api.history_service,
        "update_checks",
        lambda db: [
            _check("nginx:1.27", rebuilt=False, newest_tag="1.29"),
            _check("postgres:16", rebuilt=False, newest_tag=None),
            _check("nginx:1.25", rebuilt=True, newest_tag="1.29"),
        ],
    )


@pytest.mark.usefixtures("stubbed")
def test_counts(client: TestClient) -> None:
    stats = client.get("/api/dashboard").json()

    assert stats["containers_running"] == 2
    assert stats["containers_stopped"] == 2
    assert [alert["name"] for alert in stats["unhealthy_containers"]] == ["db", "worker"]
    assert stats["images_tracked"] == 2
    assert stats["images_scanned"] == 2
    assert stats["critical_total"] == 2
    assert stats["high_total"] == 6
    assert stats["images_critical"] == 1
    assert stats["images_high"] == 2
    assert stats["most_vulnerable"] == [
        {"image": "nginx:1.27", "critical": 2, "high": 5},
        {"image": "postgres:16", "critical": 0, "high": 1},
    ]
    assert stats["updates_available"] == 1
    assert stats["updates"] == [{"image": "nginx:1.27", "newest_tag": "1.29", "rebuilt": False}]
    assert stats["host"]["cpus"] == 4
