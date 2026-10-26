import ipaddress
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.fail2ban import _HOST_PATH

FIREHOL_LEVEL1 = "https://iplists.firehol.org/files/firehol_level1.netset"


class IpBlocklistConfig(BaseModel):
    enabled: bool = False
    # Lists of IPs and CIDR ranges, one per line, `#` comments.
    sources: list[str] = Field(default=[FIREHOL_LEVEL1], max_length=5)
    # Host path of the proxy sync's allowlist: its IPs are never blocked. Empty: none.
    allowlist_file: str = Field(
        default="/data/proxy/allowlist.txt", pattern=r"^$|" + _HOST_PATH, max_length=500
    )
    # Never blocked either, on top of the private ranges, which always are.
    ignore_ips: list[str] = []

    @field_validator("sources")
    @classmethod
    def _urls(cls, value: list[str]) -> list[str]:
        for url in value:
            if not url.startswith(("https://", "http://")) or any(c.isspace() for c in url):
                raise ValueError(f"not an http(s) URL: {url}")
        return value

    @field_validator("ignore_ips")
    @classmethod
    def _networks(cls, value: list[str]) -> list[str]:
        for item in value:
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError as exc:
                raise ValueError(f"not an IP or network: {item}") from exc
        return value


class IpBlocklistSource(BaseModel):
    url: str
    # Ranges this source gave at its last successful download.
    entries: int = 0
    fetched_at: datetime | None = None
    # The last download's error; the previous ranges are still used.
    error: str | None = None


class IpBlocklistStatus(BaseModel):
    # Last time the list was loaded on the host.
    applied_at: datetime | None = None
    # Ranges loaded, after merging and dropping private ones.
    entries: int = 0
    sources: list[IpBlocklistSource] = []


class IpBlocklistHost(BaseModel):
    # Whether DryDock's nftables table is on the host; None when the host is unreadable.
    active: bool | None = None
    # Packets dropped since the table was last loaded.
    dropped: int | None = None
    error: str | None = None


class IpBlocklistRead(BaseModel):
    config: IpBlocklistConfig
    status: IpBlocklistStatus | None = None
    host: IpBlocklistHost


class IpBlocklistCheck(BaseModel):
    ip: str
    blocked: bool
    # The blocklist range the IP falls in.
    network: str | None = None
    # The never-blocked range that lets it through anyway.
    allowed_by: str | None = None
