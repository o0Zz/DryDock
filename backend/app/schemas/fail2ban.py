from typing import Literal

from pydantic import BaseModel, Field

# A jail name is also a file name (`jail.d/<name>.local`, `filter.d/<name>.conf`).
JAIL_NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$"
# An absolute host path, on one line: it ends up in fail2ban's config and a shell script.
_HOST_PATH = r"^/[^\n\r'\"$`]*$"
# A file DryDock may write, relative to /etc/fail2ban. The planner refuses the package's
# `.conf` files on top of this.
WRITABLE_PATH = (
    r"^(?:jail\.local|jail\.d/[A-Za-z0-9_.-]+\.local|filter\.d/[A-Za-z0-9_.-]+\.(?:conf|local))$"
)
# Every file fail2ban reads is small; this keeps a paste from filling the request.
_MAX_TEXT = 200_000


class Fail2banBlock(BaseModel):
    """A piece of fail2ban's config as it is in its file."""

    # Path under /etc/fail2ban.
    path: str
    # The jail's `[section]` in a jail file; None for a whole filter file.
    section: str | None
    # Line of the section's header; None for a whole file, or a block not written yet.
    line: int | None = None
    # Empty for a block not written yet: where an override of the jail would go.
    text: str
    # `package`: apt owns it, read only. `local`: the owner's. `drydock`: DryDock made it.
    owner: Literal["package", "local", "drydock"]


class Fail2banJailConfig(BaseModel):
    """A jail of the host: what fail2ban makes of it, and the blocks that define it."""

    name: str
    # DryDock created its files: `jail.d/<name>.local` and `filter.d/<name>.conf`.
    managed: bool
    enabled: bool
    # `systemd` reads the journal: no log path.
    backend: str | None = None
    # The filter.d file of its regexes; None when DryDock cannot tell (interpolated).
    filter: str | None = None
    # Effective values, from `fail2ban-client -d` when the jail is on.
    logpath: list[str] = []
    maxretry: str = ""
    findtime: str = ""
    bantime: str = ""
    # In the order fail2ban reads them: the last value of a key wins.
    blocks: list[Fail2banBlock] = []
    # Its lines of `fail2ban-client -d`, raw. Empty when the jail is off.
    dump: list[str] = []


class Fail2banJails(BaseModel):
    jails: list[Fail2banJailConfig]
    # Starting points for a new jail.
    templates: list[str] = []


class Fail2banNewJail(BaseModel):
    """A jail on a log, rendered from a template into its own two files."""

    name: str = Field(pattern=JAIL_NAME)
    template: str
    # Docker publishes the proxy's ports, so its traffic is forwarded, not input.
    ban_hook: Literal["forward", "input"] = "forward"
    logpath: str = Field(default="/data/proxy/logs/access.log", pattern=_HOST_PATH)


class Fail2banFileEdit(BaseModel):
    path: str = Field(pattern=WRITABLE_PATH)
    # Set: replace that `[section]` block of the file. None: replace the whole file.
    section: str | None = Field(default=None, pattern=JAIL_NAME)
    # The new text; empty removes the section. None removes the whole file.
    text: str | None = Field(default=None, max_length=_MAX_TEXT)
    # The file must not exist yet: a new jail.
    new: bool = False


class Fail2banEdit(BaseModel):
    files: list[Fail2banFileEdit] = []


class Fail2banFileChange(BaseModel):
    # Path under /etc/fail2ban.
    path: str
    # None: the file does not exist before, or is removed after.
    before: str | None
    after: str | None


class Fail2banPlan(BaseModel):
    files: list[Fail2banFileChange]


class Fail2banTestRequest(BaseModel):
    logpath: str = Field(pattern=_HOST_PATH, max_length=500)
    # The filter.d file to test, as fail2ban loads it: with its `.local` and includes.
    filter: str = Field(pattern=JAIL_NAME)
    # Filter files as edited, path -> text: they replace the host's for the test.
    files: dict[str, str] = {}


class Fail2banHit(BaseModel):
    ip: str
    count: int


class Fail2banTestResult(BaseModel):
    # Lines read from the end of the log, and how many the rule matched.
    lines: int
    matched: int
    top_ips: list[Fail2banHit] = []
    # A few matched lines, the newest last.
    samples: list[str] = []
