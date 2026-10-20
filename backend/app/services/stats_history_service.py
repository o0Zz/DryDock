"""Short in-memory history of container stats, for the sparklines on the containers page.

There is no sampler of its own: the history fills from the stats the UI already
polls, so a Pi does no extra work when nobody looks. It is lost on restart.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime, timedelta

from app.schemas.container import ContainerStats, StatsSample

# 60 samples at the UI's 5s poll: about five minutes.
MAX_SAMPLES = 60
# Two open tabs poll twice as often; keep one sample per poll interval.
MIN_INTERVAL = timedelta(seconds=4)
# A container with no sample for this long is stopped or gone.
MAX_AGE = timedelta(minutes=5)

_lock = threading.Lock()
_history: dict[str, deque[StatsSample]] = {}


def record(stats: list[ContainerStats], *, now: datetime | None = None) -> None:
    """Add one sample per container, unless its last one is too recent."""
    now = now or datetime.now(tz=UTC)
    with _lock:
        for entry in stats:
            samples = _history.setdefault(entry.id, deque(maxlen=MAX_SAMPLES))
            if samples and now - samples[-1].at < MIN_INTERVAL:
                continue
            samples.append(
                StatsSample(at=now, cpu_percent=entry.cpu_percent, memory_usage=entry.memory_usage)
            )
        # One missed poll (a container stopping mid-poll) must not drop its history,
        # so only containers silent for a whole window go.
        stale = [cid for cid, samples in _history.items() if now - samples[-1].at > MAX_AGE]
        for container_id in stale:
            del _history[container_id]


def snapshot() -> dict[str, list[StatsSample]]:
    """Samples per container ID, oldest first."""
    with _lock:
        return {container_id: list(samples) for container_id, samples in _history.items()}


def clear() -> None:
    with _lock:
        _history.clear()
