from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Access log formats: one text line per request (Traefik, nginx/SWAG), or JSON (Caddy).
LogFormat = Literal["text", "json"]

# A jail name is also a file name (`jail.d/<name>.local`, `filter.d/<name>.conf`).
JAIL_NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$"
# An absolute host path, on one line: it ends up in fail2ban's config and a shell script.
_HOST_PATH = r"^/[^\n\r'\"$`]*$"


class Fail2banJailConfig(BaseModel):
    """A jail as the host's fail2ban sees it, from its files and `fail2ban-client -d`."""

    name: str
    # DryDock created its files: `jail.d/<name>.local` and `filter.d/<name>.conf`.
    managed: bool
    enabled: bool
    # `systemd` reads the journal: no log path.
    backend: str | None = None
    # The filter.d file of its regexes; None when DryDock cannot tell (interpolated).
    filter: str | None = None
    logpath: list[str] = []
    failregex: list[str] = []
    ignoreregex: list[str] = []
    maxretry: str = ""
    findtime: str = ""
    bantime: str = ""
    # field -> `file:line` that sets it.
    sources: dict[str, str] = {}
    # Its lines of `fail2ban-client -d`, raw. Empty when the jail is off.
    dump: list[str] = []


class Fail2banTemplate(BaseModel):
    """A starting point for a new jail on the proxy's access log."""

    # The filter.d file the new filter includes for its variables, if any.
    before: str | None = None
    failregex: dict[LogFormat, str]


class Fail2banJails(BaseModel):
    jails: list[Fail2banJailConfig]
    # The single `jail.d/drydock.local` of older DryDock versions is still there.
    legacy: bool = False
    templates: dict[str, Fail2banTemplate] = {}


class Fail2banNewJail(BaseModel):
    template: str
    log_format: LogFormat = "text"
    # Docker publishes the proxy's ports, so its traffic is forwarded, not input.
    ban_hook: Literal["forward", "input"] = "forward"


class Fail2banJailChange(BaseModel):
    """What changes in one jail. A field left None stays as it is."""

    name: str = Field(pattern=JAIL_NAME)
    # Set to create the jail; DryDock then owns its two files.
    create: Fail2banNewJail | None = None
    # Only a jail DryDock created can be deleted. Any jail can be turned off.
    delete: bool = False
    enabled: bool | None = None
    logpath: list[str] | None = None
    failregex: list[str] | None = None
    ignoreregex: list[str] | None = None
    maxretry: str | None = Field(default=None, pattern=r"^\d{1,4}$")
    # fail2ban's time values: seconds, `10m`, `1d`, `-1` for ever.
    findtime: str | None = Field(default=None, pattern=r"^-?\d+[smhdwy]?$")
    bantime: str | None = Field(default=None, pattern=r"^-?\d+[smhdwy]?$")

    @field_validator("logpath", "failregex", "ignoreregex")
    @classmethod
    def _lines(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        lines = [line.strip() for line in value if line.strip()]
        for line in lines:
            if "\n" in line or "\r" in line or len(line) > 2000:
                raise ValueError("one line per item, 2000 characters at most")
        return lines


class Fail2banEdit(BaseModel):
    changes: list[Fail2banJailChange] = []
    # Split the old `jail.d/drydock.local` into one file per jail.
    convert_legacy: bool = False


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
    failregex: list[str]
    ignoreregex: list[str] = []
    # The jail's filter: its other settings (prefregex, datepattern) apply too.
    filter: str | None = Field(default=None, pattern=JAIL_NAME)
    # For a new jail: the template's include and the log format's date pattern.
    template: str | None = None
    log_format: LogFormat = "text"

    @field_validator("failregex", "ignoreregex")
    @classmethod
    def _lines(cls, value: list[str]) -> list[str]:
        return Fail2banJailChange._lines(value) or []


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
