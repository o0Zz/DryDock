"""Pending OS package updates on the Docker host.

DryDock cannot reach the host's apt from its own container. A throwaway helper
container mounts the host's root read-only and chroots into it, so the host's
own `apt list --upgradable` reads the host's package state. Nothing is written:
the list is only as fresh as the host's last `apt update`, so the time of that
run is reported too.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.host_update import HostUpdateCheck
from app.schemas.host import HostPackage, HostUpdates
from app.services import docker_service, volume_files_service

# Rows kept; older checks are deleted.
HISTORY = 30

# Runs on the host. Markers (`@@`) come before apt's own output. A kernel whose
# modules folder is gone was replaced by an upgrade: the host needs a reboot.
# Debian only writes /var/run/reboot-required with unattended-upgrades; Ubuntu always.
SCRIPT = r"""
command -v apt >/dev/null 2>&1 || { echo "@@unsupported"; exit 0; }
kernel=$(uname -r)
echo "@@kernel $kernel"
if [ -n "$(ls /lib/modules 2>/dev/null)" ] && [ ! -d "/lib/modules/$kernel" ]; then
  echo "@@reboot"
fi
if [ -e /var/run/reboot-required ]; then echo "@@reboot"; fi
echo "@@lists $(stat -c %Y /var/lib/apt/lists/*Release 2>/dev/null | sort -n | tail -n 1)"
apt list --upgradable 2>/dev/null
"""

# `bsdutils/stable,stable-security 1:2.41.5-0+deb13u1 arm64 [upgradable from: 1:2.41-5]`
_PACKAGE = re.compile(
    r"^(?P<name>[^/\s]+)/(?P<suites>\S+) (?P<candidate>\S+) \S+ "
    r"\[upgradable from: (?P<current>[^\]]+)\]"
)


@dataclass
class HostUpdateResult:
    supported: bool = True
    packages: list[HostPackage] = field(default_factory=list)
    lists_updated_at: datetime | None = None
    reboot_required: bool = False
    kernel: str | None = None


def parse(output: str) -> HostUpdateResult:
    result = HostUpdateResult()
    for line in output.splitlines():
        if line == "@@unsupported":
            result.supported = False
        elif line.startswith("@@kernel "):
            result.kernel = line.removeprefix("@@kernel ").strip() or None
        elif line == "@@reboot":
            result.reboot_required = True
        elif line.startswith("@@lists"):
            stamp = line.removeprefix("@@lists").strip()
            if stamp:
                result.lists_updated_at = datetime.fromtimestamp(float(stamp), tz=UTC)
        elif match := _PACKAGE.match(line):
            result.packages.append(
                HostPackage(
                    name=match["name"],
                    current=match["current"],
                    candidate=match["candidate"],
                    security=any("security" in suite for suite in match["suites"].split(",")),
                )
            )
    result.packages.sort(key=lambda package: (not package.security, package.name))
    return result


def check(db: Session) -> HostUpdateCheck:
    """Read the host's pending updates and store the outcome, successful or not."""
    try:
        output = docker_service.run_on_host(SCRIPT, image=volume_files_service.helper_image())
        result = parse(output)
    except (docker_service.DockerUnavailable, docker_service.HostCommandFailed) as exc:
        row = HostUpdateCheck(error=str(exc)[:1000])
    else:
        row = HostUpdateCheck(
            supported=result.supported,
            upgradable=len(result.packages),
            security=sum(1 for package in result.packages if package.security),
            packages=json.dumps([package.model_dump() for package in result.packages]),
            # Stored naive, like every other timestamp; the schema stamps UTC back on.
            lists_updated_at=(
                result.lists_updated_at.replace(tzinfo=None) if result.lists_updated_at else None
            ),
            reboot_required=result.reboot_required,
            kernel=result.kernel,
        )
    db.add(row)
    db.commit()
    db.refresh(row)
    _trim(db)
    return row


def _trim(db: Session) -> None:
    keep = select(HostUpdateCheck.id).order_by(HostUpdateCheck.id.desc()).limit(HISTORY)
    db.execute(delete(HostUpdateCheck).where(HostUpdateCheck.id.not_in(keep)))
    db.commit()


def latest(db: Session) -> HostUpdates | None:
    row = db.scalar(select(HostUpdateCheck).order_by(HostUpdateCheck.id.desc()).limit(1))
    if row is None:
        return None
    return HostUpdates(
        checked_at=row.checked_at,
        supported=row.supported,
        error=row.error,
        upgradable=row.upgradable,
        security=row.security,
        packages=json.loads(row.packages),
        lists_updated_at=row.lists_updated_at,
        reboot_required=row.reboot_required,
        kernel=row.kernel,
    )
