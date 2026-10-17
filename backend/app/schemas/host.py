from typing import Literal

from pydantic import BaseModel

from app.schemas.common import UtcDatetime


class HostPackage(BaseModel):
    name: str
    current: str
    candidate: str
    # Comes from a security suite (`trixie-security`, `noble-security`).
    security: bool = False


class HostUpdates(BaseModel):
    """The latest check of the host's pending OS package updates."""

    checked_at: UtcDatetime
    # False when the host has no apt: not Debian or Ubuntu, or Docker Desktop's VM.
    supported: bool
    error: str | None = None
    upgradable: int = 0
    security: int = 0
    packages: list[HostPackage] = []
    # When the host last ran `apt update`. The list is only as fresh as this.
    lists_updated_at: UtcDatetime | None = None
    reboot_required: bool = False
    kernel: str | None = None


class HostUpgradeStatus(BaseModel):
    """The host upgrade systemd unit, read straight from the host.

    It outlives DryDock: a Docker upgrade restarts DryDock but not the unit.
    """

    # none: never run, or gone after a reboot.
    state: Literal["none", "running", "success", "failed"]
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    exit_code: int | None = None
    # The tail of the unit's journal.
    log: str = ""


class Fail2banJail(BaseModel):
    name: str
    enabled: bool
    active_bans: int = 0
    # Bans still in fail2ban's history, which only goes back `dbpurgeage`.
    bans: int = 0
    last_ban_at: UtcDatetime | None = None


class Fail2banBan(BaseModel):
    ip: str
    jail: str
    banned_at: UtcDatetime
    # None for a permanent ban.
    expires_at: UtcDatetime | None = None
    # How many times fail2ban has banned this IP in this jail.
    ban_count: int = 1
    # The log lines that triggered the ban, newest last.
    matches: list[str] = []


class Fail2banUser(BaseModel):
    """A user name tried in failed SSH logins."""

    name: str
    count: int


class Fail2banReport(BaseModel):
    database: str
    # Oldest ban in fail2ban's history, so the UI can say how far back it goes.
    history_since: UtcDatetime | None = None
    jails: list[Fail2banJail] = []
    active_bans: list[Fail2banBan] = []
    recent_bans: list[Fail2banBan] = []
    top_users: list[Fail2banUser] = []
