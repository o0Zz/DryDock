"""initial schema

Baseline for every DryDock database. Installs from before Alembic were built
by ``create_all`` plus an ad-hoc "add missing nullable columns" step, so they
have no ``alembic_version`` table and start here too. To adopt them, this
revision creates only what is missing instead of failing on existing tables.

Later revisions must not do this: they run against a known schema.

Revision ID: 974c41908761
Revises:
Create Date: 2026-10-17 08:04:22.101072+00:00
"""

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import SchemaItem

revision: str = "974c41908761"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jobs() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    ]


def _scans() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image", sa.String(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(), nullable=False),
        sa.Column("critical", sa.Integer(), nullable=False),
        sa.Column("high", sa.Integer(), nullable=False),
        sa.Column("medium", sa.Integer(), nullable=False),
        sa.Column("low", sa.Integer(), nullable=False),
        sa.Column("unknown", sa.Integer(), nullable=False),
        sa.Column("fixable", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scans")),
    ]


def _settings() -> list[SchemaItem]:
    return [
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    ]


def _update_checks() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image", sa.String(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("local_digest", sa.String(), nullable=True),
        sa.Column("remote_digest", sa.String(), nullable=True),
        sa.Column("update_available", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("newest_tag", sa.String(), nullable=True),
        sa.Column("newest_same_major_tag", sa.String(), nullable=True),
        sa.Column("tag_error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_update_checks")),
    ]


def _users() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    ]


def _scan_findings() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("vulnerability_id", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("package_name", sa.String(), nullable=False),
        sa.Column("installed_version", sa.String(), nullable=True),
        sa.Column("fixed_version", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("primary_url", sa.String(), nullable=True),
        sa.Column("target", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["scans.id"],
            name=op.f("fk_scan_findings_scan_id_scans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_findings")),
    ]


# (table, schema items, indexes as (name, columns, unique)), parents before children.
TABLES: list[tuple[str, Callable[[], list[SchemaItem]], list[tuple[str, list[str], bool]]]] = [
    ("jobs", _jobs, [("ix_jobs_kind", ["kind"], False), ("ix_jobs_status", ["status"], False)]),
    ("scans", _scans, [("ix_scans_image", ["image"], False)]),
    ("settings", _settings, []),
    ("update_checks", _update_checks, [("ix_update_checks_image", ["image"], False)]),
    ("users", _users, [("ix_users_username", ["username"], True)]),
    (
        "scan_findings",
        _scan_findings,
        [
            ("ix_scan_findings_scan_id", ["scan_id"], False),
            ("ix_scan_findings_vulnerability_id", ["vulnerability_id"], False),
        ],
    ),
]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    for table, items, indexes in TABLES:
        if table not in existing_tables:
            op.create_table(table, *items())
        else:
            _add_missing_columns(inspector, table, items())
        for name, columns, unique in indexes:
            op.create_index(op.f(name), table, columns, unique=unique, if_not_exists=True)


def _add_missing_columns(inspector: sa.Inspector, table: str, items: list[SchemaItem]) -> None:
    """Bring a pre-Alembic table up to the baseline."""
    existing = {c["name"] for c in inspector.get_columns(table)}
    missing = [i for i in items if isinstance(i, sa.Column) and i.name not in existing]
    required = [c.name for c in missing if not c.nullable]
    if required:
        # The old startup code only ever added nullable columns, so this means
        # the database did not come from DryDock.
        raise RuntimeError(f"Cannot adopt table {table!r}: missing NOT NULL columns {required}")
    for column in missing:
        op.add_column(table, column)


def downgrade() -> None:
    for table, _items, indexes in reversed(TABLES):
        for name, _columns, _unique in indexes:
            op.drop_index(op.f(name), table_name=table)
        op.drop_table(table)
