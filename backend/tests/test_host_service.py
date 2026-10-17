"""Host load read from a fake /proc and /sys tree."""

from pathlib import Path

import pytest

from app.services import host_service

STAT_BEFORE = "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 2 3 4\n"
# 100 more busy jiffies and 300 more idle ones: 25% busy.
STAT_AFTER = "cpu  150 0 150 950 150 0 0 0 0 0\ncpu0 1 2 3 4\n"


@pytest.fixture
def fake_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text(STAT_BEFORE)
    (proc / "meminfo").write_text(
        "MemTotal:        4000000 kB\nMemFree:          500000 kB\nMemAvailable:    3000000 kB\n"
    )
    (proc / "loadavg").write_text("0.52 0.40 0.30 1/200 1234\n")
    (proc / "uptime").write_text("3600.50 7000.00\n")
    thermal = tmp_path / "thermal"
    for name, kind, temp in (
        ("thermal_zone0", "acpitz", "30000"),
        ("thermal_zone1", "cpu-thermal", "52345"),
    ):
        (thermal / name).mkdir(parents=True)
        (thermal / name / "type").write_text(kind + "\n")
        (thermal / name / "temp").write_text(temp + "\n")

    monkeypatch.setattr(host_service, "PROC", proc)
    monkeypatch.setattr(host_service, "THERMAL", thermal)
    # Swap the second CPU sample in instead of waiting.
    monkeypatch.setattr(
        host_service.time, "sleep", lambda seconds: (proc / "stat").write_text(STAT_AFTER)
    )
    return tmp_path


@pytest.mark.usefixtures("fake_host")
def test_usage() -> None:
    usage = host_service.usage()

    assert usage.cpu_percent == 25.0
    assert usage.load_1m == 0.52
    assert usage.memory_total == 4000000 * 1024
    assert usage.memory_used == 1000000 * 1024
    assert usage.uptime_seconds == 3600.5
    assert usage.temperature_c == 52.3


def test_usage_without_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_service, "PROC", tmp_path / "missing")
    monkeypatch.setattr(host_service, "THERMAL", tmp_path / "missing")

    usage = host_service.usage()

    assert usage.model_dump() == {
        "cpu_percent": None,
        "load_1m": None,
        "memory_total": None,
        "memory_used": None,
        "uptime_seconds": None,
        "temperature_c": None,
    }
