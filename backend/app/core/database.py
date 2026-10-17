from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# Deterministic constraint names. Alembic batch mode rebuilds SQLite tables to
# alter them, and it can only drop or change a constraint that has a name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Default for timestamp columns. SQLite drops the tzinfo; schemas.common adds it back."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# The rest of the API is synchronous, so we use a plain sync SQLAlchemy engine.
settings.data_path.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    """SQLite ignores FK constraints unless asked, and defaults to a slow journal.

    ON DELETE CASCADE on scan_findings depends on foreign_keys being ON, and WAL
    keeps background jobs from blocking API reads while they write.

    Bound to the app engine only: the migration engine needs foreign_keys OFF.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def init_db() -> None:
    """Bring the schema up to date. Alembic migrations own the schema, never
    ``create_all``, so every install follows the same upgrade path."""
    from app.core.migrations import upgrade_database

    upgrade_database()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
