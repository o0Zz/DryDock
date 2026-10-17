from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.setting import Setting

logger = logging.getLogger(__name__)

# Runtime-editable settings and their defaults. Anything not listed here is
# rejected by set_many, so the API can accept a partial dict safely.
DEFAULTS: dict[str, Any] = {
    # Scheduled CVE scans of all running images.
    "scan_schedule_enabled": True,
    "scan_interval_hours": 24,
    # Scheduled registry digest comparison for all known images.
    "update_check_enabled": True,
    "update_check_interval_hours": 24,
    # Optional webhook fired after a scheduled run finds something notable.
    "notify_webhook_url": "",
    "notify_on_critical": True,
    "notify_on_update": True,
}

# Interval bounds keep a fat-fingered value from hammering a Pi or a registry.
_INT_BOUNDS = {
    "scan_interval_hours": (1, 24 * 30),
    "update_check_interval_hours": (1, 24 * 30),
}


class SettingsError(ValueError):
    """Raised when a settings payload is rejected."""


def _coerce(key: str, value: Any) -> Any:
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        raise SettingsError(f"{key} must be a boolean")
    if isinstance(default, int):
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise SettingsError(f"{key} must be a whole number") from exc
        low, high = _INT_BOUNDS.get(key, (None, None))
        if low is not None and not (low <= number <= high):
            raise SettingsError(f"{key} must be between {low} and {high}")
        return number
    if isinstance(default, str):
        if not isinstance(value, str):
            raise SettingsError(f"{key} must be a string")
        return value.strip()
    return value


def get_all(db: Session) -> dict[str, Any]:
    """Every setting, with stored values layered over the defaults."""
    values = dict(DEFAULTS)
    for row in db.scalars(select(Setting)):
        if row.key not in DEFAULTS:
            continue  # stale key from an older version - ignore it
        try:
            values[row.key] = json.loads(row.value)
        except json.JSONDecodeError:
            logger.warning("Setting %r holds invalid JSON; using default", row.key)
    return values


def set_many(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(values) - set(DEFAULTS))
    if unknown:
        raise SettingsError(f"Unknown setting(s): {', '.join(unknown)}")

    for key, raw in values.items():
        coerced = _coerce(key, raw)
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=json.dumps(coerced)))
        else:
            row.value = json.dumps(coerced)
    db.commit()
    return get_all(db)
