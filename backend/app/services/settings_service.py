from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.setting import Setting

logger = logging.getLogger(__name__)

# Runtime-editable settings and their defaults. Writes are validated (types,
# interval bounds, known keys only) by SettingsUpdate in app/schemas/setting.py.
DEFAULTS: dict[str, Any] = {
    # Scheduled CVE scans of all running images.
    "scan_schedule_enabled": True,
    "scan_interval_hours": 24,
    # Scheduled update check of all known images (digest, tags, git commits) and host packages.
    "update_check_enabled": True,
    "update_check_interval_hours": 24,
    # Daily pull and recreate of the services labelled `drydock.update=auto`, at this
    # hour of the server's clock. Off by default: an update is a choice, per service.
    "auto_update_enabled": False,
    "auto_update_hour": 4,
    # Optional webhook fired after a scheduled run finds something notable.
    "notify_webhook_url": "",
    "notify_on_critical": True,
    "notify_on_update": True,
    # Reverse proxy (proxy_service): the domain bare sub-domains complete to, and the
    # Docker network Traefik shares with the stacks it exposes.
    "proxy_domain": "",
    "proxy_network": "proxy",
    # fail2ban jails DryDock manages (fail2ban_config_service); None until first saved.
    "fail2ban_config": None,
    # Known bad IPs dropped by the host's nftables (blocklist_service); None until saved.
    "ip_blocklist": None,
}

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


def set_many(db: Session, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if isinstance(value, str):
            value = value.strip()
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=json.dumps(value)))
        else:
            row.value = json.dumps(value)
    db.commit()
