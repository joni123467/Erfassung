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


def _add_user_auto_break_deduction(connection: sqlite3.Connection) -> None:
    cursor = connection.execute("PRAGMA table_info('users')")
    columns = {row[1] for row in cursor.fetchall()}
    if "auto_break_deduction" not in columns:
        # Default 1 keeps the existing behaviour (statutory breaks applied)
        # for every user created before this migration.
        connection.execute(
            "ALTER TABLE users ADD COLUMN auto_break_deduction INTEGER DEFAULT 1"
        )
    connection.execute(
        "UPDATE users SET auto_break_deduction = 1 WHERE auto_break_deduction IS NULL"
    )
    connection.commit()


MIGRATIONS: list[tuple[int, MigrationFn]] = [
    (1, _baseline),
    (2, _add_group_time_report_permission),
    (3, _add_time_entry_external_columns),
    (4, _add_user_auto_break_deduction),
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
