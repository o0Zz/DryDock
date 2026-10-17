from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


class HostUpdateCheck(Base):
    """Pending OS package updates on the Docker host, read from its apt state.

    Rows are append-only, like update checks: the latest row is current.
    """

    __tablename__ = "host_update_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    # False when the host has no apt (not Debian or Ubuntu, or Docker Desktop's VM).
    supported: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    upgradable: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    security: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # JSON list of {name, current, candidate, security}.
    packages: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    # When the host last ran `apt update`: the list above is only as fresh as this.
    lists_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reboot_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    kernel: Mapped[str | None] = mapped_column(String, nullable=True)
    # unattended-upgrades installed and switched on (APT::Periodic::Unattended-Upgrade).
    auto_upgrades: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
