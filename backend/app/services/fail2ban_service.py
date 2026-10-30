"""Bans and the log lines behind them, from the host's fail2ban.

fail2ban keeps its state in an SQLite file on the host. A helper container
copies that file out (read-only mount, never started) and DryDock opens the
copy in memory, so nothing on the host changes and no fail2ban client is
needed. The history only goes back `dbpurgeage`, one day by default.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.schemas.host import Fail2banBan, Fail2banJail, Fail2banReport, Fail2banUser
from app.services import docker_service, volume_files_service

RECENT_BANS = 100
TOP_USERS = 15
# Log lines kept per ban, the newest ones.
MATCHES_PER_BAN = 10
MATCH_LENGTH = 500

# sshd: `Invalid user admin from`, `Failed password for (invalid user) root from`.
_SSH_USER = re.compile(r"(?:Invalid user|Failed \S+ for(?: invalid user)?) (\S+) from ")


class Fail2banError(Exception):
    """Raised when the file is not a fail2ban database DryDock can read."""


def report(now: datetime | None = None) -> Fail2banReport:
    data = docker_service.read_host_file(
        settings.fail2ban_db, image=volume_files_service.helper_image()
    )
    return parse_database(data, now or datetime.now(UTC))


def _time(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


def _matches(raw: Any) -> list[str]:
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return []
    lines = []
    # fail2ban 0.10 stored each match as a list of tokens.
    for match in (data or {}).get("matches") or []:
        line = "".join(match) if isinstance(match, list) else str(match)
        lines.append(line[:MATCH_LENGTH])
    return lines


def _ban(row: sqlite3.Row) -> Fail2banBan:
    bantime = row["bantime"]
    return Fail2banBan(
        ip=row["ip"],
        jail=row["jail"],
        banned_at=_time(row["timeofban"]),
        expires_at=None if bantime < 0 else _time(row["timeofban"] + bantime),
        ban_count=row["bancount"],
        matches=_matches(row["data"])[-MATCHES_PER_BAN:],
    )


def _tables(db: sqlite3.Connection) -> set[str]:
    return {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def parse_database(data: bytes, now: datetime) -> Fail2banReport:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.deserialize(data)
        tables = _tables(db)
        if not {"jails", "bans", "bips"} <= tables:
            raise Fail2banError(f"{settings.fail2ban_db} is not a fail2ban 0.11+ database")
        history = list(db.execute("SELECT * FROM bans ORDER BY timeofban DESC"))
        # bips holds the current ban per IP, including long bans older than the purge age.
        current = list(db.execute("SELECT * FROM bips ORDER BY timeofban DESC"))
        jail_rows = list(db.execute("SELECT name, enabled FROM jails ORDER BY name"))
    except sqlite3.DatabaseError as exc:
        raise Fail2banError(f"cannot read {settings.fail2ban_db}: {exc}") from exc
    finally:
        db.close()

    active: list[Fail2banBan] = []
    seen: set[tuple[str, str]] = set()
    for row in current:
        ban = _ban(row)
        key = (ban.jail, ban.ip)
        if key in seen or (ban.expires_at is not None and ban.expires_at <= now):
            continue
        seen.add(key)
        active.append(ban)

    jails = [Fail2banJail(name=name, enabled=bool(enabled)) for name, enabled in jail_rows]
    by_name = {jail.name: jail for jail in jails}
    for ban in active:
        if ban.jail in by_name:
            by_name[ban.jail].active_bans += 1
    for row in history:
        jail = by_name.get(row["jail"])
        if jail is None:
            continue
        jail.bans += 1
        banned_at = _time(row["timeofban"])
        if jail.last_ban_at is None or banned_at > jail.last_ban_at:
            jail.last_ban_at = banned_at

    # The same log line can sit in a ban and in its bips row; count it once.
    lines = {line for row in [*history, *current] for line in _matches(row["data"])}
    users = Counter(match[1] for line in lines if (match := _SSH_USER.search(line)))

    return Fail2banReport(
        database=settings.fail2ban_db,
        history_since=_time(history[-1]["timeofban"]) if history else None,
        jails=jails,
        active_bans=active,
        recent_bans=[_ban(row) for row in history[:RECENT_BANS]],
        top_users=[
            Fail2banUser(name=name, count=count) for name, count in users.most_common(TOP_USERS)
        ],
    )
