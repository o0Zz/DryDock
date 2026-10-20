"""Schema migrations, applied automatically at startup.

Alembic owns the schema. Revisions live in ``backend/migrations/versions``.
After changing a model, generate a revision from ``backend/`` and review it:

    uv run alembic revision --autogenerate -m "add foo to scans"
"""

import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

from app.core.config import settings

logger = logging.getLogger(__name__)

# backend/migrations in dev, /app/migrations in the image.
MIGRATIONS_PATH = Path(__file__).resolve().parents[2] / "migrations"
# Pre-migration snapshots kept under <data>/backups/db; older ones are pruned.
KEEP_BACKUPS = 5


def alembic_config() -> Config:
    """Alembic config built in code, so startup does not depend on alembic.ini."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    return config


def create_migration_engine() -> Engine:
    """A dedicated engine for schema changes, separate from the app engine."""
    migration_engine = create_engine(f"sqlite:///{settings.db_path}", poolclass=NullPool)

    @event.listens_for(migration_engine, "connect")
    def _connect(
        dbapi_connection: sqlite3.Connection, connection_record: ConnectionPoolEntry
    ) -> None:
        # pysqlite commits on its own before DDL, which would leave a failed
        # migration half applied. Take over so each upgrade is one transaction.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            # Batch mode rebuilds a table by copying it and dropping the
            # original. With FKs on, that DROP cascade-deletes the child rows.
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    @event.listens_for(migration_engine, "begin")
    def _begin(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return migration_engine


def upgrade_database() -> None:
    """Upgrade the database to the latest revision, backing it up first."""
    config = alembic_config()
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()

    settings.data_path.mkdir(parents=True, exist_ok=True)
    migration_engine = create_migration_engine()
    try:
        with migration_engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
            has_tables = bool(inspect(connection).get_table_names())

        if current == head:
            return
        known_revisions = {step.revision for step in script.walk_revisions()}
        if current is not None and current not in known_revisions:
            raise RuntimeError(
                f"Database is at revision {current!r}, which this DryDock version does not "
                "know. It was likely written by a newer release: upgrade DryDock, or restore "
                f"a backup from {settings.backups_path / 'db'}."
            )
        if has_tables:
            _backup_database(current)

        logger.info("Migrating database from %s to %s", current or "an unversioned schema", head)
        with migration_engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        migration_engine.dispose()


def _backup_database(revision: str | None) -> None:
    """Snapshot the database with SQLite's online backup API (WAL-safe)."""
    backup_dir = settings.backups_path / "db"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"drydock-{stamp}-{revision or 'unversioned'}.db"

    with (
        closing(sqlite3.connect(settings.db_path)) as source,
        closing(sqlite3.connect(target)) as destination,
    ):
        source.backup(destination)
    logger.info("Backed up database to %s", target)

    # The timestamp prefix makes name order chronological.
    for old_backup in sorted(backup_dir.glob("drydock-*.db"))[:-KEEP_BACKUPS]:
        old_backup.unlink()
