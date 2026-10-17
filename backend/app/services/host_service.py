"""Live load of the Docker host, read from /proc and /sys.

DryDock runs in a container, but /proc/stat, /proc/meminfo, /proc/loadavg and
/proc/uptime are not namespaced, so they describe the whole host, and the
thermal zones come from the host's sysfs. Every reading is None where the file
is missing: a Windows dev box, or a VM without a temperature sensor.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.schemas.dashboard import HostUsage

PROC = Path("/proc")
THERMAL = Path("/sys/class/thermal")

# CPU usage is the busy share between two /proc/stat samples taken this far apart.
CPU_SAMPLE_SECONDS = 0.25

# Zone types that measure the CPU: Raspberry Pi, other ARM boards, Intel.
CPU_ZONE_TYPES = ("cpu", "soc", "x86_pkg_temp")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _cpu_times() -> tuple[int, int] | None:
    """(total, idle) jiffies of the aggregate `cpu` line."""
    text = _read(PROC / "stat")
    if not text:
        return None
    # user nice system idle iowait irq softirq steal; guest time is already in user.
    fields = [int(value) for value in text.splitlines()[0].split()[1:9]]
    return sum(fields), fields[3] + fields[4]


def _cpu_percent() -> float | None:
    first = _cpu_times()
    if first is None:
        return None
    time.sleep(CPU_SAMPLE_SECONDS)
    second = _cpu_times()
    if second is None:
        return None
    total = second[0] - first[0]
    if total <= 0:
        return None
    return round(100 * (total - (second[1] - first[1])) / total, 1)


def _memory() -> tuple[int | None, int | None]:
    """(total, used) bytes. Used excludes the page cache, like `free`'s "available"."""
    text = _read(PROC / "meminfo")
    if not text:
        return None, None
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            values[key] = int(parts[0]) * 1024  # reported in kB
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if total is None or available is None:
        return total, None
    return total, total - available


def _first_number(path: Path) -> float | None:
    text = _read(path)
    try:
        return float(text.split()[0]) if text else None
    except ValueError:
        return None


def _temperature_c() -> float | None:
    readings: list[tuple[str, float]] = []
    for zone in sorted(THERMAL.glob("thermal_zone*")):
        raw = _first_number(zone / "temp")
        if raw is not None:
            readings.append(((_read(zone / "type") or "").strip().lower(), raw / 1000))
    for kind, celsius in readings:
        if any(name in kind for name in CPU_ZONE_TYPES):
            return round(celsius, 1)
    return round(readings[0][1], 1) if readings else None


def usage() -> HostUsage:
    memory_total, memory_used = _memory()
    return HostUsage(
        cpu_percent=_cpu_percent(),
        load_1m=_first_number(PROC / "loadavg"),
        memory_total=memory_total,
        memory_used=memory_used,
        uptime_seconds=_first_number(PROC / "uptime"),
        temperature_c=_temperature_c(),
    )
