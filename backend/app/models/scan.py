from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Scan(Base):
    """One CVE scan of a single image reference (e.g. ``nginx:latest``).

    Rows are append-only: the latest row per image is the current result.
    """

    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image: Mapped[str] = mapped_column(String, index=True, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    critical: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    high: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    medium: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unknown: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fixable: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(String, nullable=True)

    findings: Mapped[list["ScanFinding"]] = relationship(
        back_populates="scan",
        cascade="all, delete-orphan",
        # Findings are only ever needed on the scan-detail endpoint, never in
        # the list view, so keep them off the default SELECT.
        lazy="select",
    )


class ScanFinding(Base):
    """A single vulnerability reported by trivy for a scan.

    Stored so the UI can link out to the CVE instead of only showing counts.
    """

    __tablename__ = "scan_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vulnerability_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    package_name: Mapped[str] = mapped_column(String, nullable=False)
    installed_version: Mapped[str | None] = mapped_column(String, nullable=True)
    fixed_version: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_url: Mapped[str | None] = mapped_column(String, nullable=True)
    target: Mapped[str | None] = mapped_column(String, nullable=True)

    scan: Mapped[Scan] = relationship(back_populates="findings")
