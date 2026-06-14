"""Versioned, dialect-aware migration runner for Erfassung.

Works on both SQLite (default) and MySQL 8+/MariaDB. Migration state is tracked
in the portable ``schema_migrations`` table (see :mod:`app.db_schema`). Each
migration is idempotent and forward-only; existing data is always preserved.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from sqlalchemy.engine import Engine

from . import database, db_schema
from . import models  # noqa: F401 - ensure models are imported for side-effects

try:  # ensure_schema lives in app.main and maintains legacy structures
    from .main import ensure_schema
except Exception:  # pragma: no cover - fallback if import fails
    ensure_schema = None  # type: ignore[assignment]

LOGGER = logging.getLogger("erfassung.application")

MigrationFn = Callable[[Engine], None]


def _baseline(_engine: Engine) -> None:
    """Baseline migration keeps a hook for future schema steps."""
    return None


def _add_group_time_report_permission(engine: Engine) -> None:
    if db_schema.add_column(
        engine, "groups", "can_view_time_reports", "INTEGER", default="0"
    ):
        with engine.begin() as connection:
            from sqlalchemy import text

            connection.execute(
                text("UPDATE groups SET can_view_time_reports = 1 WHERE is_admin = 1")
            )


def _add_time_entry_external_columns(engine: Engine) -> None:
    db_schema.add_column(engine, "time_entries", "source", "VARCHAR(255)")
    db_schema.add_column(engine, "time_entries", "external_id", "VARCHAR(255)")
    # The unique index is created dialect-safely by ensure_schema/create_all.


def _add_user_auto_break_deduction(engine: Engine) -> None:
    # Default 1 keeps the existing behaviour (statutory breaks applied) for
    # every user created before this migration.
    db_schema.add_column(
        engine, "users", "auto_break_deduction", "BOOLEAN", default="1", backfill_null_to="1"
    )


def _add_holiday_source(engine: Engine) -> None:
    """Distinguish statutory (auto-loaded) holidays from custom ones (§22).

    Existing rows default to 'custom' so that nothing an administrator entered
    manually is ever overwritten by the "Feiertage übernehmen" action. Freshly
    loaded statutory holidays are written with source='statutory'.
    """

    db_schema.add_column(
        engine,
        "holidays",
        "source",
        "VARCHAR(20)",
        default="'custom'",
        backfill_null_to="'custom'",
    )


def _add_backup_job_tables(engine: Engine) -> None:
    """Create the job-based backup tables (§0.9.2) if they do not exist yet.

    ``create_all`` only adds missing tables and is dialect-agnostic, so this is
    idempotent and safe on both SQLite and MySQL.
    """

    models.Base.metadata.create_all(
        bind=engine,
        tables=[models.BackupJob.__table__, models.BackupRun.__table__],
    )


def _add_restore_history_table(engine: Engine) -> None:
    """Create the restore history table (§0.9.4)."""

    models.Base.metadata.create_all(bind=engine, tables=[models.RestoreRun.__table__])


def _add_restore_run_details(engine: Engine) -> None:
    """Add duration/log-token columns to the restore history (§0.9.5)."""

    db_schema.add_column(engine, "restore_runs", "duration_seconds", "FLOAT", default="0")
    db_schema.add_column(engine, "restore_runs", "log_token", "VARCHAR(40)", default="''")


def _add_terminal_tables(engine: Engine) -> None:
    """Create the generic terminal-management tables (§0.9.8).

    ``create_all`` only adds missing tables and is dialect-agnostic, so this is
    idempotent and safe on SQLite and MySQL/MariaDB/PostgreSQL. Afterwards the
    legacy ``config/timemoto.json`` (if present) is migrated into a terminal row
    so existing TimeMoto installations keep working without reconfiguration and
    without any data loss.
    """

    models.Base.metadata.create_all(
        bind=engine,
        tables=[models.Terminal.__table__, models.TerminalSyncRun.__table__],
    )
    _migrate_legacy_timemoto_config(engine)


def _migrate_legacy_timemoto_config(engine: Engine) -> None:
    """Carry a pre-0.9.8 ``timemoto.json`` over into the terminals table.

    Looks in the canonical config volume (``paths.CONFIG_DIR``) as well as the
    package-local ``config`` directory the old integration historically used, so
    the existing TimeMoto setup survives the upgrade without reconfiguration.
    """

    import json

    from sqlalchemy.orm import Session

    from . import paths
    from .integrations import timemoto

    candidates = [
        paths.CONFIG_DIR / "timemoto.json",
        timemoto._CONFIG_PATH,  # type: ignore[attr-defined]
        timemoto._LEGACY_CONFIG_PATH,  # type: ignore[attr-defined]
    ]
    payload: dict | None = None
    for candidate in candidates:
        try:
            if candidate.exists():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("host"):
                    payload = data
                    break
        except (OSError, ValueError):  # pragma: no cover - defensive
            continue
    if not payload:
        return

    config = timemoto.TimeMotoConfig()
    config.update_from_dict(payload)
    if not config.host:
        return

    with Session(bind=engine) as session:
        existing = session.execute(
            models.Terminal.__table__.select().where(
                models.Terminal.__table__.c.type == "timemoto"
            )
        ).first()
        if existing:
            return
        extra = {
            "login_path": config.login_path,
            "users_path": config.users_path,
            "events_path": config.events_path,
            "events_limit": config.events_limit,
            "timeout": config.timeout,
        }
        last_sync = None
        if config.last_sync_at:
            try:
                last_sync = datetime.fromisoformat(config.last_sync_at)
            except ValueError:
                last_sync = None
        session.add(
            models.Terminal(
                name="TimeMoto TM-616",
                type="timemoto",
                active=True,
                host=config.host,
                port=config.port,
                username=config.username,
                password=config.password,
                use_ssl=config.use_ssl,
                verify_ssl=config.verify_ssl,
                timezone=config.timezone,
                sync_interval_minutes=60,
                config_json=json.dumps(extra),
                status="unknown",
                last_sync_at=last_sync,
                last_event_id=config.last_event_id,
            )
        )
        session.commit()
        LOGGER.info("Legacy-TimeMoto-Konfiguration in Terminalverwaltung übernommen")


MIGRATIONS: list[tuple[int, MigrationFn]] = [
    (1, _baseline),
    (2, _add_group_time_report_permission),
    (3, _add_time_entry_external_columns),
    (4, _add_user_auto_break_deduction),
    (5, _add_holiday_source),
    (6, _add_backup_job_tables),
    (7, _add_restore_history_table),
    (8, _add_restore_run_details),
    (9, _add_terminal_tables),
]


def _apply_migrations(engine: Engine, migrations: Iterable[tuple[int, MigrationFn]]) -> None:
    applied = db_schema.applied_versions(engine)
    for version, upgrade in migrations:
        if version in applied:
            continue
        LOGGER.info("Migration %s wird angewendet", version)
        upgrade(engine)
        db_schema.mark_applied(engine, version)


def run(database_path: Path | None = None) -> None:
    if database.IS_SQLITE and database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
    if ensure_schema is not None:
        ensure_schema()
    _apply_migrations(database.engine, MIGRATIONS)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Führt Datenbankmigrationen für Erfassung aus.")
    parser.add_argument(
        "--database",
        default=None,
        help="Optionaler Pfad zur SQLite-Datenbank (nur für SQLite relevant)",
    )
    args = parser.parse_args(argv)
    run(Path(args.database) if args.database else None)


if __name__ == "__main__":
    main()
