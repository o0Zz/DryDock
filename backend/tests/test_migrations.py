import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

import app.models  # noqa: F401
from app.core import migrations
from app.core.config import settings
from app.core.database import Base


@pytest.fixture(autouse=True)
def data_path(tmp_path, monkeypatch):
    """Give each test its own empty database file."""
    monkeypatch.setattr(settings, "data_path", tmp_path)
    return tmp_path


def _head() -> str:
    return ScriptDirectory.from_config(migrations.alembic_config()).get_current_head()


def _schema_diff() -> list:
    engine = migrations.create_migration_engine()
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={"compare_type": True})
            return compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()


def _revision() -> str | None:
    with sqlite3.connect(settings.db_path) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _backups() -> list:
    return sorted((settings.backups_path / "db").glob("*.db"))


def test_single_head():
    script = ScriptDirectory.from_config(migrations.alembic_config())
    assert len(script.get_heads()) == 1


def test_fresh_database_matches_models():
    migrations.upgrade_database()

    assert _revision() == _head()
    assert _schema_diff() == []
    # Nothing to lose on a fresh install, so no backup.
    assert _backups() == []


def test_upgrade_at_head_is_noop():
    migrations.upgrade_database()
    migrations.upgrade_database()

    assert _revision() == _head()
    assert _backups() == []


def test_adopts_pre_alembic_database():
    # Simulate an install built by create_all before update_checks gained its
    # tag columns, with data that must survive.
    legacy = create_engine(f"sqlite:///{settings.db_path}")
    Base.metadata.create_all(legacy)
    with legacy.begin() as conn:
        for column in ("newest_tag", "newest_same_major_tag", "tag_error"):
            conn.execute(text(f"ALTER TABLE update_checks DROP COLUMN {column}"))
        # Added after the move to Alembic, so no legacy database has it.
        conn.execute(text("ALTER TABLE jobs DROP COLUMN output"))
        conn.execute(
            text(
                "INSERT INTO users (username, hashed_password, is_admin, is_active, created_at) "
                "VALUES ('admin', 'x', 1, 1, '2026-01-01 00:00:00')"
            )
        )
    legacy.dispose()

    migrations.upgrade_database()

    assert _revision() == _head()
    assert _schema_diff() == []
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT username FROM users").fetchall() == [("admin",)]
    [backup] = _backups()
    assert backup.name.endswith("-unversioned.db")


def test_refuses_revision_from_newer_release():
    migrations.upgrade_database()
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("UPDATE alembic_version SET version_num = 'ffffffffffff'")

    with pytest.raises(RuntimeError, match="does not know"):
        migrations.upgrade_database()


def test_downgrade_to_base_and_back():
    config = migrations.alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    with sqlite3.connect(settings.db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"alembic_version"}

    command.upgrade(config, "head")
    assert _schema_diff() == []


def test_failed_migration_rolls_back_ddl():
    engine = migrations.create_migration_engine()
    try:
        with pytest.raises(RuntimeError), engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE half_done (id INTEGER)")
            raise RuntimeError("migration failed")
        with engine.connect() as conn:
            found = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE name = 'half_done'")
            assert found.all() == []
    finally:
        engine.dispose()
