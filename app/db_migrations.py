"""Lightweight SQLite migration runner for Erfassung."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Callable, Iterable

from . import database
from . import models  # noqa: F401 - ensure models are imported for side-effects

try:
    # ensure_schema lives in app.main and maintains legacy structures
    from .main import ensure_schema
except Exception:  # pragma: no cover - fallback if import fails
    ensure_schema = None  # type: ignore[assignment]

MigrationFn = Callable[[sqlite3.Connection], None]


def _baseline(_connection: sqlite3.Connection) -> None:
    """Baseline migration keeps hook for future schema steps."""
    # No-op by design; user_version will be set by the runner.
    return None


def _add_group_time_report_permission(connection: sqlite3.Connection) -> None:
    cursor = connection.execute("PRAGMA table_info('groups')")
    columns = {row[1] for row in cursor.fetchall()}
    if "can_view_time_reports" not in columns:
        connection.execute(
            "ALTER TABLE groups ADD COLUMN can_view_time_reports INTEGER DEFAULT 0"
        )
        connection.execute(
            "UPDATE groups SET can_view_time_reports = 1 WHERE is_admin = 1"
        )
        connection.commit()


def _add_time_entry_external_columns(connection: sqlite3.Connection) -> None:
    cursor = connection.execute("PRAGMA table_info('time_entries')")
    columns = {row[1] for row in cursor.fetchall()}
    if "source" not in columns:
        connection.execute("ALTER TABLE time_entries ADD COLUMN source TEXT")
    if "external_id" not in columns:
        connection.execute("ALTER TABLE time_entries ADD COLUMN external_id TEXT")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_time_entries_source_external ON time_entries(source, external_id)"
    )
    connection.commit()




def _add_offline_sync_columns(connection: sqlite3.Connection) -> None:
    def _columns(table: str) -> set[str]:
        cursor = connection.execute(f"PRAGMA table_info('{table}')")
        return {row[1] for row in cursor.fetchall()}

    for table in ("companies", "users", "holidays", "vacation_requests"):
        cols = _columns(table)
        if "updated_at" not in cols:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN updated_at DATETIME")
            connection.execute(f"UPDATE {table} SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_operation_logs (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            operation_id VARCHAR NOT NULL UNIQUE,
            operation_type VARCHAR NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'synced',
            message VARCHAR DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS ix_sync_operation_logs_user_id ON sync_operation_logs(user_id)")
    connection.commit()

MIGRATIONS: list[tuple[int, MigrationFn]] = [
    (1, _baseline),
    (2, _add_group_time_report_permission),
    (3, _add_time_entry_external_columns),
    (4, _add_offline_sync_columns),
]


def _apply_migrations(connection: sqlite3.Connection, migrations: Iterable[tuple[int, MigrationFn]]) -> None:
    cursor = connection.execute("PRAGMA user_version")
    row = cursor.fetchone()
    current_version = int(row[0]) if row else 0
    for version, upgrade in migrations:
        if version <= current_version:
            continue
        upgrade(connection)
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()


def run(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if ensure_schema is not None:
        ensure_schema()
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _apply_migrations(connection, MIGRATIONS)


def main(argv: list[str] | None = None) -> None:
    default_path = Path(database.SQLALCHEMY_DATABASE_URL.replace("sqlite:///", ""))
    parser = argparse.ArgumentParser(description="Führt SQLite-Migrationen für Erfassung aus.")
    parser.add_argument("--database", default=str(default_path), help="Pfad zur SQLite-Datenbank")
    args = parser.parse_args(argv)
    run(Path(args.database))


if __name__ == "__main__":
    main()
