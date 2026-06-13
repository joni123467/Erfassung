"""Dialect-aware schema helpers shared by SQLite and MySQL/MariaDB.

The versioned migration runner historically relied on SQLite's
``PRAGMA user_version``. To support MySQL 8+/MariaDB as well, migration state
is now tracked in a portable ``schema_migrations`` table. Existing SQLite
installations are migrated transparently: their ``user_version`` is read once
and back-filled into the new table so applied migrations are never re-run.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

LOGGER = logging.getLogger("erfassung.application")

_VERSION_TABLE = "schema_migrations"


def has_table(engine: Engine, table: str) -> bool:
    return inspect(engine).has_table(table)


def has_column(engine: Engine, table: str, column: str) -> bool:
    inspector = inspect(engine)
    if not inspector.has_table(table):
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def add_column(
    engine: Engine,
    table: str,
    column: str,
    column_type: str,
    *,
    default: str | None = None,
    backfill_null_to: str | None = None,
) -> bool:
    """Add ``column`` to ``table`` if missing. Returns True when it was added.

    ``column_type`` must be a portable SQL type that both SQLite and MySQL
    accept (e.g. ``INTEGER``, ``BOOLEAN``, ``FLOAT``, ``VARCHAR(255)``,
    ``TEXT``, ``DATE``, ``TIME``, ``DATETIME``). ``VARCHAR`` must always carry
    an explicit length so MySQL accepts it.
    """

    if not has_table(engine, table):
        return False
    if has_column(engine, table, column):
        return False
    ddl = f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"
    if default is not None:
        ddl += f" DEFAULT {default}"
    with engine.begin() as connection:
        connection.execute(text(ddl))
        if backfill_null_to is not None:
            connection.execute(
                text(f"UPDATE {table} SET {column} = {backfill_null_to} WHERE {column} IS NULL")
            )
    LOGGER.info("Spalte %s.%s ergänzt", table, column)
    return True


def _ensure_version_table(engine: Engine) -> None:
    if has_table(engine, _VERSION_TABLE):
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE TABLE {_VERSION_TABLE} ("
                "version INTEGER NOT NULL PRIMARY KEY, "
                "applied_at VARCHAR(40)"
                ")"
            )
        )


def _backfill_from_sqlite_user_version(engine: Engine) -> None:
    """Seed schema_migrations from a legacy SQLite ``user_version`` (once)."""

    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        existing = connection.execute(text(f"SELECT COUNT(*) FROM {_VERSION_TABLE}")).scalar()
        if existing:
            return
        user_version = connection.execute(text("PRAGMA user_version")).scalar() or 0
        for version in range(1, int(user_version) + 1):
            connection.execute(
                text(f"INSERT INTO {_VERSION_TABLE} (version, applied_at) VALUES (:v, :ts)"),
                {"v": version, "ts": datetime.utcnow().isoformat()},
            )
        if user_version:
            LOGGER.info("schema_migrations aus user_version=%s übernommen", user_version)


def applied_versions(engine: Engine) -> set[int]:
    _ensure_version_table(engine)
    _backfill_from_sqlite_user_version(engine)
    with engine.begin() as connection:
        rows = connection.execute(text(f"SELECT version FROM {_VERSION_TABLE}")).fetchall()
    return {int(row[0]) for row in rows}


def mark_applied(engine: Engine, version: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO {_VERSION_TABLE} (version, applied_at) VALUES (:v, :ts)"),
            {"v": version, "ts": datetime.utcnow().isoformat()},
        )
        if engine.dialect.name == "sqlite":
            # Keep PRAGMA user_version in sync for any external tooling.
            connection.execute(text(f"PRAGMA user_version = {int(version)}"))


def latest_applied_version(engine: Engine) -> int:
    versions = applied_versions(engine)
    return max(versions) if versions else 0
