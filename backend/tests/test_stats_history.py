"""In-memory stats history behind the containers page sparklines."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.schemas.container import ContainerStats
from app.services import docker_service, stats_history_service

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _stats(container_id: str = "abc", cpu: float = 1.0) -> ContainerStats:
    return ContainerStats(
        id=container_id,
        name=container_id,
        cpu_percent=cpu,
        memory_usage=100,
        memory_limit=1000,
        memory_percent=10.0,
        network_rx=0,
        network_tx=0,
        block_read=0,
        block_write=0,
    )


@pytest.fixture(autouse=True)
def empty() -> Iterator[None]:
    stats_history_service.clear()
    yield
    stats_history_service.clear()


def test_keeps_the_last_samples_only() -> None:
    for step in range(stats_history_service.MAX_SAMPLES + 5):
        stats_history_service.record([_stats(cpu=step)], now=T0 + timedelta(seconds=5 * step))

    samples = stats_history_service.snapshot()["abc"]
    assert len(samples) == stats_history_service.MAX_SAMPLES
    assert samples[0].cpu_percent == 5 and samples[-1].cpu_percent == 64


def test_a_second_tab_does_not_double_the_samples() -> None:
    stats_history_service.record([_stats(cpu=1)], now=T0)
    stats_history_service.record([_stats(cpu=2)], now=T0 + timedelta(seconds=1))

    assert [s.cpu_percent for s in stats_history_service.snapshot()["abc"]] == [1]


def test_gone_containers_are_dropped_after_a_window() -> None:
    stats_history_service.record([_stats("old"), _stats("web")], now=T0)
    # "old" misses one poll: kept.
    stats_history_service.record([_stats("web")], now=T0 + timedelta(seconds=5))
    assert set(stats_history_service.snapshot()) == {"old", "web"}

    stats_history_service.record([_stats("web")], now=T0 + timedelta(minutes=6))
    assert set(stats_history_service.snapshot()) == {"web"}


def test_stats_route_feeds_the_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_service, "running_stats", lambda: [_stats(cpu=12.5)])
    app.dependency_overrides[get_current_user] = lambda: None
    try:
        client = TestClient(app)
        assert client.get("/api/containers/stats").status_code == 200
        history = client.get("/api/containers/stats/history").json()
    finally:
        app.dependency_overrides.clear()

    assert [sample["cpu_percent"] for sample in history["abc"]] == [12.5]
