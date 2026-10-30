import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

import app.models  # noqa: F401
from app.core import migrations
from app.core.config import settings
from app.core.database import Base


@pytest.fixture(autouse=True)
def data_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give each test its own empty database file."""
    monkeypatch.setattr(settings, "data_path", tmp_path)
    return tmp_path


def _head() -> str:
    return ScriptDirectory.from_config(migrations.alembic_config()).get_current_head()


def _schema_diff() -> list:
    engine = migrations.create_migration_engine()
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            return compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()


def _revision() -> str | None:
    with sqlite3.connect(settings.db_path) as connection:
        return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _backups() -> list[Path]:
    return sorted((settings.backups_path / "db").glob("*.db"))


def test_single_head() -> None:
    script = ScriptDirectory.from_config(migrations.alembic_config())
    assert len(script.get_heads()) == 1


def test_fresh_database_matches_models() -> None:
    migrations.upgrade_database()

    assert _revision() == _head()
    assert _schema_diff() == []
    # Nothing to lose on a fresh install, so no backup.
    assert _backups() == []


def test_upgrade_at_head_is_noop() -> None:
    migrations.upgrade_database()
    migrations.upgrade_database()

    assert _revision() == _head()
    assert _backups() == []


def test_refuses_revision_from_newer_release() -> None:
    migrations.upgrade_database()
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'ffffffffffff'")

    with pytest.raises(RuntimeError, match="does not know"):
        migrations.upgrade_database()


def test_downgrade_to_base_and_back() -> None:
    config = migrations.alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    with sqlite3.connect(settings.db_path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in rows}
    assert tables == {"alembic_version"}

    command.upgrade(config, "head")
    assert _schema_diff() == []


def test_failed_migration_rolls_back_ddl() -> None:
    engine = migrations.create_migration_engine()
    try:
        with pytest.raises(RuntimeError), engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE half_done (id INTEGER)")
            raise RuntimeError("migration failed")
        with engine.connect() as connection:
            found = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE name = 'half_done'"
            )
            assert found.all() == []
    finally:
        engine.dispose()
