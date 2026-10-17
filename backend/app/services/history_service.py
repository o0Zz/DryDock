"""Reads over the append-only scan and update-check tables."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models.scan import Scan
from app.models.update import UpdateCheck


def _rows(db: Session, model: type, timestamp: InstrumentedAttribute, image: str | None) -> list:
    """Every row for `image`, or else the newest row per image; newest first."""
    if image:
        stmt = select(model).where(model.image == image)
    else:
        newest = select(func.max(model.id)).group_by(model.image)
        stmt = select(model).where(model.id.in_(newest))
    return list(db.scalars(stmt.order_by(timestamp.desc())))


def scans(db: Session, image: str | None = None) -> list[Scan]:
    return _rows(db, Scan, Scan.scanned_at, image)


def update_checks(db: Session, image: str | None = None) -> list[UpdateCheck]:
    return _rows(db, UpdateCheck, UpdateCheck.checked_at, image)
