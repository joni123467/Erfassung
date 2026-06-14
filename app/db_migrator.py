"""Cross-database migration engine (§0.9.7).

Moves *all* business data from the currently active database into a freshly
selected target backend (SQLite ⇄ MySQL ⇄ MariaDB ⇄ PostgreSQL) without data
loss. The design is ORM/metadata driven so it is fully dialect agnostic:

* the schema is created on the target with ``Base.metadata.create_all`` – the
  same portable column types used everywhere else in the app,
* rows are read through the typed SQLAlchemy ``Table`` objects (so values come
  back as native Python types – ``date``/``datetime``/``bool``/…) and written
  back through the target's typed columns, so every dialect converts correctly,
* tables are copied in foreign-key dependency order (``sorted_tables``),
* the portable ``schema_migrations`` bookkeeping table is recreated and seeded
  so the migration state is identical on the target.

Safety model (no downtime, no data loss):

1. validate + connect to the target,
2. create a mandatory pre-migration safety backup (rollback point),
3. build the target schema and refuse to overwrite a non-empty target,
4. copy all data, fix PostgreSQL sequences,
5. run an integrity check (table count, per-table row counts, key entities),
6. only on success switch the live engine over and persist the selection,
7. on any failure the *source* database stays active and untouched (rollback),
8. everything is logged to ``database.log``.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine

from . import app_config, backup_manager, database, db_schema, logging_setup, models

LOGGER = logging.getLogger("erfassung.application")

# Tables whose emptiness is required on the target before a migration so we can
# never silently overwrite an existing installation (data-loss guard, §4/§6).
ProgressFn = Callable[[str, int, str], None]


def log_db(message: str, *, level: int = logging.INFO, user: object = None) -> None:
    try:
        logging_setup.log_database(message, level=level, user=user)
    except Exception:  # pragma: no cover - logging must never break a migration
        LOGGER.info(message)


# -- connection test --------------------------------------------------------

def _server_version(engine: Engine) -> Optional[str]:
    backend = engine.dialect.name
    try:
        with engine.connect() as conn:
            if backend == "sqlite":
                row = conn.execute(text("SELECT sqlite_version()")).fetchone()
            elif backend == "postgresql":
                row = conn.execute(text("SHOW server_version")).fetchone()
            else:  # mysql / mariadb
                row = conn.execute(text("SELECT VERSION()")).fetchone()
        return str(row[0]) if row else None
    except Exception:  # pragma: no cover - depends on backend
        return None


def build_target_engine(config: "app_config.DatabaseConfig") -> Engine:
    """Build an engine for ``config`` without touching the live engine."""
    conn_cfg = config.connection_config()
    url = database.build_url(conn_cfg)
    options = database._engine_options(database.normalise_type(config.type), conn_cfg)
    database._prepare_sqlite_dir(url)
    return create_engine(url, **options)


def test_connection(config: "app_config.DatabaseConfig", *, user: object = None) -> dict:
    """Verify the target is reachable; returns ``{ok, message, version}``."""
    ok_cfg, reason = app_config.validate_database_config(config)
    if not ok_cfg:
        log_db(f"Verbindungstest fehlgeschlagen: {reason}", level=logging.WARNING, user=user)
        return {"ok": False, "message": reason, "version": None}
    engine = None
    try:
        engine = build_target_engine(config)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        version = _server_version(engine)
        message = f"Verbindung erfolgreich ({config.describe()})"
        if version:
            message += f" – Version {version}"
        log_db(
            f"Verbindungstest erfolgreich: {config.type} {config.host or config.sqlite_path}"
            + (f" (Version {version})" if version else ""),
            user=user,
        )
        return {"ok": True, "message": message, "version": version}
    except ModuleNotFoundError as exc:
        message = f"Erforderlicher Datenbanktreiber fehlt: {exc.name}"
        log_db(f"Verbindungstest fehlgeschlagen: {message}", level=logging.WARNING, user=user)
        return {"ok": False, "message": message, "version": None}
    except Exception as exc:  # pragma: no cover - depends on backend
        message = f"Verbindung fehlgeschlagen: {type(exc).__name__}: {exc}"
        log_db(f"Verbindungstest fehlgeschlagen: {message}", level=logging.WARNING, user=user)
        return {"ok": False, "message": message, "version": None}
    finally:
        if engine is not None:
            engine.dispose()


# -- schema + data ----------------------------------------------------------

def _ordered_tables():
    """Business tables in FK dependency order (parents first)."""
    return list(models.Base.metadata.sorted_tables)


def _table_is_empty(engine: Engine, table) -> bool:
    with engine.connect() as conn:
        count = conn.execute(select(func.count()).select_from(table)).scalar() or 0
    return int(count) == 0


def _ensure_target_empty(engine: Engine) -> None:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    for table in _ordered_tables():
        if table.name in existing and not _table_is_empty(engine, table):
            raise RuntimeError(
                f"Zieldatenbank ist nicht leer (Tabelle '{table.name}' enthält Daten). "
                "Migration abgebrochen, um Datenverlust zu vermeiden."
            )


def _create_target_schema(target: Engine) -> None:
    models.Base.metadata.create_all(bind=target)
    # Recreate + seed the portable migration bookkeeping table so the target
    # reports the same applied versions as the source.
    db_schema._ensure_version_table(target)
    source_versions = db_schema.applied_versions(database.engine)
    target_versions = db_schema.applied_versions(target)
    for version in sorted(source_versions - target_versions):
        db_schema.mark_applied(target, version)


def _copy_table(source: Engine, target: Engine, table, batch_size: int = 500) -> int:
    """Copy all rows of ``table`` from source to target. Returns row count."""
    copied = 0
    with source.connect() as src_conn:
        result = src_conn.execution_options(stream_results=True).execute(table.select())
        with target.begin() as dst_conn:
            while True:
                rows = result.fetchmany(batch_size)
                if not rows:
                    break
                dst_conn.execute(table.insert(), [dict(row._mapping) for row in rows])
                copied += len(rows)
    return copied


def _fix_postgres_sequences(target: Engine) -> None:
    """Advance identity sequences past the highest copied id (PostgreSQL)."""
    if target.dialect.name != "postgresql":
        return
    with target.begin() as conn:
        for table in _ordered_tables():
            if "id" not in table.c:
                continue
            conn.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence(:tbl, 'id'), "
                    "COALESCE((SELECT MAX(id) FROM " + table.name + "), 1), "
                    "(SELECT COUNT(*) FROM " + table.name + ") > 0)"
                ),
                {"tbl": table.name},
            )


# -- integrity --------------------------------------------------------------

def _row_counts(engine: Engine) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in _ordered_tables():
            counts[table.name] = int(
                conn.execute(select(func.count()).select_from(table)).scalar() or 0
            )
    return counts


KEY_ENTITY_TABLES = {
    "users": "Benutzer",
    "groups": "Rollen",
    "time_entries": "Stempelungen/Arbeitszeiten",
    "vacation_requests": "Urlaub",
    "holidays": "Feiertage",
    "backup_runs": "Backup-Historie",
    "restore_runs": "Restore-Historie",
    "mobile_sync_actions": "Offline-Synchronisationsdaten",
}


def integrity_check(source: Engine, target: Engine) -> dict:
    """Compare source and target after a copy. Returns a structured report."""
    source_counts = _row_counts(source)
    target_counts = _row_counts(target)
    mismatches: list[dict] = []
    total_source = sum(source_counts.values())
    total_target = sum(target_counts.values())
    for name, src_count in source_counts.items():
        tgt_count = target_counts.get(name, -1)
        if src_count != tgt_count:
            mismatches.append({"table": name, "source": src_count, "target": tgt_count})

    entities = []
    for name, label in KEY_ENTITY_TABLES.items():
        if name in source_counts:
            entities.append(
                {
                    "table": name,
                    "label": label,
                    "source": source_counts[name],
                    "target": target_counts.get(name, 0),
                    "ok": source_counts[name] == target_counts.get(name, -1),
                }
            )

    ok = not mismatches and len(source_counts) == len(target_counts)
    return {
        "ok": ok,
        "table_count_source": len(source_counts),
        "table_count_target": len(target_counts),
        "records_source": total_source,
        "records_target": total_target,
        "mismatches": mismatches,
        "entities": entities,
    }


# -- pipeline ---------------------------------------------------------------

def migrate(
    target_config: "app_config.DatabaseConfig",
    *,
    username: str = "-",
    token: str = "",
    progress: Optional[ProgressFn] = None,
) -> dict:
    """Run the full migration pipeline. Never raises – returns a result dict."""

    def emit(state: str, percent: int, message: str) -> None:
        if progress:
            progress(state, percent, message)

    started = time.time()
    source_engine = database.engine
    source_type = database.DB_TYPE
    target_type = database.normalise_type(target_config.type)
    status = "error"
    message = ""
    safety_path = None
    post_backup = None
    records = 0
    report: dict = {}
    target_engine: Optional[Engine] = None

    log_db(
        f"Migration gestartet: {source_type} → {target_type} ({target_config.describe()}) "
        f"(Job {token})",
        user=username,
    )

    try:
        # Schritt 1: Zielverbindung prüfen.
        emit("testing", 10, "Zielverbindung wird geprüft")
        test = test_connection(target_config, user=username)
        if not test["ok"]:
            raise RuntimeError(test["message"])
        target_version = test.get("version")

        # Schritt 2: Sicherheitsbackup (Rollback-Punkt) – sichert die QUELLE.
        emit("creating_backup", 25, "Sicherheitsbackup wird erstellt")
        safety_path = backup_manager.create_safety_backup(
            prefix="pre_db_migration", backup_type="pre_db_migration"
        )
        log_db(f"Sicherheitsbackup erstellt: {safety_path.name} (Job {token})", user=username)

        # Schritt 3: Zielschema erzeugen (und Leerheit sicherstellen).
        emit("creating_schema", 40, "Zielschema wird erzeugt")
        target_engine = build_target_engine(target_config)
        _create_target_schema(target_engine)
        _ensure_target_empty(target_engine)

        # Schritt 4+5: Daten exportieren und importieren.
        emit("copying", 60, "Daten werden übertragen")
        for table in _ordered_tables():
            records += _copy_table(source_engine, target_engine, table)
        _fix_postgres_sequences(target_engine)
        log_db(f"Daten übertragen: {records} Datensätze (Job {token})", user=username)

        # Schritt 6: Integritätsprüfung.
        emit("verifying", 80, "Integrität wird geprüft")
        report = integrity_check(source_engine, target_engine)
        if not report["ok"]:
            detail = ", ".join(
                f"{m['table']} (Quelle {m['source']} / Ziel {m['target']})"
                for m in report["mismatches"]
            )
            raise RuntimeError(
                f"Integritätsprüfung fehlgeschlagen: abweichende Datensätze – {detail or 'Tabellenanzahl'}"
            )
        log_db(
            f"Integritätsprüfung erfolgreich: {report['table_count_target']} Tabellen, "
            f"{report['records_target']} Datensätze (Job {token})",
            user=username,
        )

        # Schritt 7: Anwendung umstellen (Engine + persistente Auswahl).
        emit("switching", 90, "Anwendung wird umgestellt")
        if target_engine is not None:
            target_engine.dispose()
            target_engine = None
        app_config.save_database_config(target_config)
        database.reconfigure(target_config.connection_config())
        log_db("Anwendung auf neue Datenbank umgestellt", user=username)

        # Schritt 8 (Teil): Sofortiger Wiederherstellungspunkt auf dem NEUEN Backend.
        try:
            post_backup = backup_manager.create_safety_backup(
                prefix="post_db_migration", backup_type="post_db_migration"
            )
            log_db(f"Backup nach Migration erstellt: {post_backup.name} (Job {token})", user=username)
        except Exception as exc:  # pragma: no cover - never fail the migration on this
            log_db(
                f"Backup nach Migration konnte nicht erstellt werden: {exc}",
                level=logging.WARNING,
                user=username,
            )

        status = "success"
        message = (
            f"Migration erfolgreich: {source_type} → {target_type}, "
            f"{report['records_target']} Datensätze in {report['table_count_target']} Tabellen"
        )
        log_db(f"Migration erfolgreich (Job {token}): {message}", user=username)
        emit("completed", 100, message)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        log_db(
            f"Migration fehlgeschlagen (Job {token}): {message}", level=logging.ERROR, user=username
        )
        log_db(
            "Rollback durchgeführt – bisherige Datenbank bleibt aktiv", level=logging.WARNING,
            user=username,
        )
        emit("failed", 100, message)
        if target_engine is not None:
            try:
                target_engine.dispose()
            except Exception:  # pragma: no cover
                pass

    duration = time.time() - started
    return {
        "status": status,
        "message": message,
        "source_type": source_type,
        "target_type": target_type,
        "records": records,
        "duration_seconds": duration,
        "safety_backup": safety_path.name if safety_path else None,
        "post_backup": post_backup.name if post_backup else None,
        "integrity": report,
    }
