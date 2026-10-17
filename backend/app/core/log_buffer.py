"""In-memory ring buffer of recent application log lines, served to the UI."""

from __future__ import annotations

import logging
import threading
from collections import deque

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
MAX_LINES = 2000


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = MAX_LINES) -> None:
        super().__init__()
        self._lines: deque[tuple[int, str]] = deque(maxlen=capacity)
        self._seq = 0
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)
            return
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, line))

    def since(self, seq: int) -> list[tuple[int, str]]:
        """Lines with a sequence number greater than `seq`, oldest first."""
        with self._lock:
            return [entry for entry in self._lines if entry[0] > seq]

    def tail(self, count: int) -> list[tuple[int, str]]:
        with self._lock:
            return list(self._lines)[-count:] if count else []

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq


buffer = RingBufferHandler()
buffer.setFormatter(logging.Formatter(LOG_FORMAT))


def install() -> None:
    """Capture app logs (root) plus uvicorn's startup/error logs. Access logs
    are left out on purpose: UI polling would drown everything else."""
    for name in ("", "uvicorn"):
        target = logging.getLogger(name)
        if buffer not in target.handlers:
            target.addHandler(buffer)
