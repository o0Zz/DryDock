"""Host package updates and fail2ban bans, with the helper containers faked."""

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.core.security import get_current_user
from app.main import app
from app.services import docker_service, fail2ban_service, host_updates_service

APT_OUTPUT = """@@kernel 6.12.47+rpt-rpi-2712
@@lists 1792224583
@@auto 0
Listing...
bsdutils/stable,stable-security 1:2.41.5-0+deb13u1 arm64 [upgradable from: 1:2.41-5]
7zip/stable 25.01+dfsg-1~deb13u2 arm64 [upgradable from: 25.01+dfsg-1~deb13u1]
"""

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


@pytest.fixture
def helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_updates_service.volume_files_service, "_image", "helper")


def test_parse_apt_output() -> None:
    result = host_updates_service.parse(APT_OUTPUT)

    assert result.supported
    assert result.kernel == "6.12.47+rpt-rpi-2712"
    assert result.lists_updated_at == datetime.fromtimestamp(1792224583, tz=UTC)
    assert not result.reboot_required
    assert result.auto_upgrades is False
    # Security updates first.
    assert [(package.name, package.security) for package in result.packages] == [
        ("bsdutils", True),
        ("7zip", False),
    ]
    assert result.packages[0].current == "1:2.41-5"
    assert result.packages[0].candidate == "1:2.41.5-0+deb13u1"


def test_parse_reboot_and_unsupported() -> None:
    assert host_updates_service.parse("@@kernel 6.1\n@@reboot\n@@lists\n").reboot_required
    assert not host_updates_service.parse("@@unsupported\n").supported


@pytest.mark.usefixtures("helper")
def test_check_stores_counts_and_keeps_history_short(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(docker_service, "run_on_host", lambda script, image: APT_OUTPUT)
    monkeypatch.setattr(host_updates_service, "HISTORY", 2)

    for _ in range(3):
        host_updates_service.check(db)
    latest = host_updates_service.latest(db)

    assert latest is not None
    assert (latest.upgradable, latest.security) == (2, 1)
    assert latest.packages[0].name == "bsdutils"
    assert db.query(host_updates_service.HostUpdateCheck).count() == 2


@pytest.mark.usefixtures("helper")
def test_check_records_a_failure(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(script: str, image: str) -> str:
        raise docker_service.HostCommandFailed("chroot: exit 1")

    monkeypatch.setattr(docker_service, "run_on_host", fail)

    row = host_updates_service.check(db)

    assert row.error == "chroot: exit 1"
    assert row.upgradable == 0


def _epoch(hours_ago: float) -> int:
    return int(NOW.timestamp() - hours_ago * 3600)


def _fail2ban_db() -> bytes:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE jails(name TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE bans(jail TEXT NOT NULL, ip TEXT, timeofban INTEGER NOT NULL,
            bantime INTEGER NOT NULL, bancount INTEGER NOT NULL default 1, data JSON);
        CREATE TABLE bips(ip TEXT NOT NULL, jail TEXT NOT NULL, timeofban INTEGER NOT NULL,
            bantime INTEGER NOT NULL, bancount INTEGER NOT NULL default 1, data JSON,
            PRIMARY KEY(ip, jail));
        INSERT INTO jails VALUES ('sshd', 1), ('nginx-botsearch', 1), ('old', 0);
        """
    )
    lines = [
        "sshd[1]: Invalid user admin from 1.1.1.1 port 1",
        "sshd[1]: Failed password for invalid user admin from 1.1.1.1 port 1 ssh2",
        "sshd[2]: Failed password for root from 2.2.2.2 port 2 ssh2",
    ]
    rows = [
        # Active, banned 1h ago for 24h.
        ("sshd", "1.1.1.1", _epoch(1), 86400, 2, json.dumps({"matches": lines[:2]})),
        # Expired: banned 30h ago for 24h.
        ("sshd", "2.2.2.2", _epoch(30), 86400, 1, json.dumps({"matches": lines[2:]})),
        # Permanent.
        ("nginx-botsearch", "3.3.3.3", _epoch(50), -1, 1, None),
    ]
    db.executemany("INSERT INTO bans VALUES (?, ?, ?, ?, ?, ?)", rows)
    db.executemany(
        "INSERT INTO bips (jail, ip, timeofban, bantime, bancount, data) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    data = db.serialize()
    db.close()
    return data


def test_fail2ban_report() -> None:
    report = fail2ban_service.parse_database(_fail2ban_db(), NOW)

    assert [ban.ip for ban in report.active_bans] == ["1.1.1.1", "3.3.3.3"]
    assert report.active_bans[1].expires_at is None
    assert report.active_bans[0].ban_count == 2
    assert [ban.ip for ban in report.recent_bans] == ["1.1.1.1", "2.2.2.2", "3.3.3.3"]
    jails = {jail.name: jail for jail in report.jails}
    assert (jails["sshd"].active_bans, jails["sshd"].bans) == (1, 2)
    assert jails["sshd"].last_ban_at == datetime.fromtimestamp(_epoch(1), tz=UTC)
    assert not jails["old"].enabled
    assert jails["old"].bans == 0
    assert [(user.name, user.count) for user in report.top_users] == [("admin", 2), ("root", 1)]
    assert report.history_since == datetime.fromtimestamp(_epoch(50), tz=UTC)


def test_fail2ban_rejects_another_database() -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE other(x)")
    data = db.serialize()

    with pytest.raises(fail2ban_service.Fail2banError):
        fail2ban_service.parse_database(data, NOW)
    with pytest.raises(fail2ban_service.Fail2banError):
        fail2ban_service.parse_database(b"not sqlite at all" * 100, NOW)


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_fail2ban_is_admin_only(client: TestClient) -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2, is_admin=False)

    assert client.get("/api/host/fail2ban").status_code == 403


@pytest.mark.usefixtures("helper")
def test_fail2ban_missing_database_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(path: str, image: str) -> bytes:
        raise docker_service.DockerNotFound("/var/lib/fail2ban does not exist on the host")

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    monkeypatch.setattr(docker_service, "read_host_file", missing)

    response = client.get("/api/host/fail2ban")

    assert response.status_code == 404
    assert "does not exist" in response.json()["detail"]
