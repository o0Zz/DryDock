"""Alembic environment, shared by the CLI and app startup (app/core/migrations.py)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.database import Base, engine
from app.core.migrations import create_migration_engine

config = context.config

# Only the CLI configures logging from alembic.ini. At app startup a connection
# is passed in, and the app's own logging setup must stay in place.
if config.config_file_name is not None and "connection" not in config.attributes:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(**kwargs) -> None:  # noqa: ANN003
    context.configure(
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things in place. Batch mode rebuilds the
        # table instead, so autogenerate must emit batch operations.
        render_as_batch=True,
        compare_type=True,
        # SQLite DDL is transactional once pysqlite stops auto-committing,
        # which create_migration_engine() arranges. Run each upgrade as one unit.
        transactional_ddl=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (``alembic upgrade --sql``)."""
    _configure(url=str(engine.url), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
        # foreign_keys is OFF while migrating, so check what the run left behind.
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        if violations:
            raise RuntimeError(f"Migration left foreign key violations: {violations[:10]}")


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    migration_engine = create_migration_engine()
    try:
        with migration_engine.connect() as connection:
            _run(connection)
    finally:
        migration_engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
