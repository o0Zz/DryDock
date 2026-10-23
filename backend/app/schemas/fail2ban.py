import ipaddress
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Ready-made detections, or `custom` with the user's own failregex.
Fail2banRule = Literal["auth", "forbidden", "botsearch", "badbots", "custom"]
# Access log formats: one text line per request (Traefik, nginx/SWAG), or JSON (Caddy).
LogFormat = Literal["text", "json"]

# An absolute host path, on one line: it ends up in fail2ban's config and a shell script.
_HOST_PATH = r"^/[^\n\r'\"$`]*$"


class Fail2banJailConfig(BaseModel):
    # Becomes the jail and filter name, `drydock-<name>`.
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    enabled: bool = True
    rule: Fail2banRule
    # Only for `custom`. <HOST> marks the client IP, as in any fail2ban filter.
    failregex: str = Field(default="", max_length=2000)
    maxretry: int = Field(default=5, ge=1, le=1000)
    # Seconds.
    findtime: int = Field(default=600, ge=60, le=30 * 86400)
    bantime: int = Field(default=86400, ge=60, le=365 * 86400)


class Fail2banConfig(BaseModel):
    # Host path of the proxy's access log.
    log_path: str = Field(pattern=_HOST_PATH, max_length=500)
    log_format: LogFormat = "text"
    # Host path of the proxy sync's allowlist: its IPs are never banned. Empty: none.
    allowlist_file: str = Field(default="", pattern=r"^$|" + _HOST_PATH, max_length=500)
    ignore_ips: list[str] = []
    # Docker publishes the proxy's ports, so its traffic is forwarded, not input.
    ban_hook: Literal["forward", "input"] = "forward"
    jails: list[Fail2banJailConfig] = []

    @field_validator("ignore_ips")
    @classmethod
    def _networks(cls, value: list[str]) -> list[str]:
        for item in value:
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError as exc:
                raise ValueError(f"not an IP or network: {item}") from exc
        return value

    @field_validator("jails")
    @classmethod
    def _unique(cls, value: list[Fail2banJailConfig]) -> list[Fail2banJailConfig]:
        names = [jail.name for jail in value]
        if len(names) != len(set(names)):
            raise ValueError("jail names must be unique")
        for jail in value:
            if jail.rule == "custom" and "<HOST>" not in jail.failregex:
                raise ValueError(f"{jail.name}: a custom failregex needs <HOST>")
        return value


class Fail2banConfigRead(BaseModel):
    config: Fail2banConfig
    # Whether the host's jail file is the one this config renders; None when unreadable.
    applied: bool | None = None


class Fail2banTestRequest(BaseModel):
    config: Fail2banConfig
    jail: Fail2banJailConfig


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
