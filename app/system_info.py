"""System status, backup and health information for the administration area."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from . import __version__ as APP_VERSION
from . import database, log_tools, models, paths
from .integrations import timemoto


def _database_path() -> Optional[Path]:
    url = database.SQLALCHEMY_DATABASE_URL
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        db_path = Path(raw)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        return db_path
    return None


def database_status(db: Session) -> dict[str, object]:
    from . import db_migrations, db_schema

    backend = database.DB_BACKEND  # "sqlite" / "mysql"
    db_type = "SQLite" if backend == "sqlite" else backend.upper()
    reachable = True
    server_version = None
    try:
        db.execute(text("SELECT 1"))
        if backend == "sqlite":
            row = db.execute(text("SELECT sqlite_version()")).fetchone()
            server_version = row[0] if row else None
        else:
            row = db.execute(text("SELECT VERSION()")).fetchone()
            server_version = row[0] if row else None
    except Exception:  # pragma: no cover - depends on backend
        reachable = False

    db_path = _database_path()
    size = db_path.stat().st_size if db_path and db_path.exists() else 0

    try:
        applied = db_schema.applied_versions(database.engine)
        last_migration = max(applied) if applied else 0
        all_versions = {version for version, _ in db_migrations.MIGRATIONS}
        pending = sorted(all_versions - applied)
    except Exception:  # pragma: no cover
        last_migration = None
        pending = []

    return {
        "type": db_type,
        "backend": backend,
        "server_version": server_version,
        "reachable": reachable,
        "size_bytes": size,
        "size_human": paths.format_size(size) if backend == "sqlite" else "–",
        "schema_version": last_migration,
        "last_migration": last_migration,
        "pending_migrations": pending,
        "path": str(db_path) if db_path else database.SQLALCHEMY_DATABASE_URL,
    }


def _count(db: Session, model) -> int:
    try:
        return int(db.query(func.count(model.id)).scalar() or 0)
    except Exception:  # pragma: no cover
        return 0


def active_user_count(db: Session, days: int = 30) -> int:
    cutoff = datetime.utcnow().date() - timedelta(days=days)
    try:
        return int(
            db.query(func.count(func.distinct(models.TimeEntry.user_id)))
            .filter(models.TimeEntry.work_date >= cutoff)
            .scalar()
            or 0
        )
    except Exception:  # pragma: no cover
        return 0


def sync_status() -> dict[str, object]:
    try:
        config = timemoto.TimeMotoConfig.load()
        last_sync = config.last_sync_at
        configured = bool(config.host)
    except Exception:  # pragma: no cover
        last_sync = None
        configured = False
    error_stats = log_tools.error_overview()
    return {
        "configured": configured,
        "last_sync_at": last_sync,
        "errors_last_24h": error_stats["last_24h"],
    }


def pwa_status() -> dict[str, object]:
    sw_path = paths.PROJECT_ROOT / "static" / "sw.js"
    return {
        "service_worker_available": sw_path.exists(),
        "offline_shell_available": (paths.PROJECT_ROOT / "static" / "mobile-offline-shell.html").exists(),
    }


def processed_offline_actions(db: Session) -> int:
    """Lifetime count of offline actions the server has *already* processed.

    ``MobileSyncAction`` is an idempotency/dedup log written *after* a punch or
    vacation action has been applied – it is NOT a pending queue. The actual
    pending queue lives only in the client's IndexedDB and is drained as soon as
    the device is online.
    """
    try:
        return int(db.query(func.count(models.MobileSyncAction.id)).scalar() or 0)
    except Exception:  # pragma: no cover
        return 0


def last_offline_action_at(db: Session):
    try:
        return db.query(func.max(models.MobileSyncAction.created_at)).scalar()
    except Exception:  # pragma: no cover
        return None


def sync_diagnostics(db: Session) -> dict[str, object]:
    """Accurate synchronisation diagnostics (§24/§26).

    The server processes offline actions synchronously, so there is no
    server-side backlog: ``open_actions`` is always 0. We additionally surface
    the lifetime count of processed offline actions, the last successful sync
    and recent sync failures (parsed from ``sync.log``).
    """

    from . import log_tools

    sync_lines = log_tools.read_log("sync", limit=5000)
    last_success = None
    failed_24h = 0
    retries = 0
    now = datetime.now()
    for line in sync_lines:
        message = (line.message or "")
        is_error = line.level in {"ERROR", "CRITICAL"} or "fehlgeschlagen" in message.lower()
        if is_error:
            if line.timestamp and (now - line.timestamp).total_seconds() <= 24 * 3600:
                failed_24h += 1
        elif line.timestamp and last_success is None:
            last_success = line.timestamp
        if "wiederhol" in message.lower() or "retry" in message.lower():
            retries += 1

    try:
        config = timemoto.TimeMotoConfig.load()
        device_last_sync = config.last_sync_at
        configured = bool(config.host)
    except Exception:  # pragma: no cover
        device_last_sync = None
        configured = False

    return {
        "open_actions": 0,  # no server-side backlog (synchronous processing)
        "running_syncs": 0,  # no background sync runner
        "processed_offline_actions": processed_offline_actions(db),
        "last_offline_action_at": last_offline_action_at(db),
        "queue_size": int(db.query(func.count(models.MobileSyncAction.id)).scalar() or 0),
        "failed_syncs_24h": failed_24h,
        "retries": retries,
        "last_successful_sync": last_success.strftime("%d.%m.%Y %H:%M:%S") if last_success else None,
        "device_last_sync": device_last_sync,
        "device_configured": configured,
    }


def volume_overview() -> list[dict[str, object]]:
    overview = []
    for name, path in paths.all_directories().items():
        stats = paths.directory_stats(path)
        stats["name"] = name
        stats["size_human"] = paths.format_size(stats["size_bytes"])
        overview.append(stats)
    return overview


def system_status(db: Session) -> dict[str, object]:
    db_status = database_status(db)
    config_stats = paths.directory_stats(paths.CONFIG_DIR)
    logs_stats = paths.directory_stats(paths.LOGS_DIR)
    return {
        "version": APP_VERSION,
        "database": db_status,
        "counts": {
            "users": _count(db, models.User),
            "active_users": active_user_count(db),
            "vacations": _count(db, models.VacationRequest),
            "orders": _count(db, models.Company),
            "time_entries": _count(db, models.TimeEntry),
        },
        "storage": {
            "database_bytes": db_status["size_bytes"],
            "database_human": db_status["size_human"],
            "config_bytes": config_stats["size_bytes"],
            "config_human": paths.format_size(config_stats["size_bytes"]),
            "logs_bytes": logs_stats["size_bytes"],
            "logs_human": paths.format_size(logs_stats["size_bytes"]),
            "free_bytes": paths.free_space_bytes(),
            "free_human": paths.format_size(paths.free_space_bytes()),
        },
        "sync": sync_status(),
        "sync_diagnostics": sync_diagnostics(db),
        "pwa": pwa_status(),
        "volumes": volume_overview(),
    }


def health_report(db: Session) -> dict[str, object]:
    """Detailed health information for the /health endpoint."""

    checks: dict[str, object] = {}
    db_reachable = True
    try:
        from sqlalchemy import text

        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover
        db_reachable = False
    checks["database"] = db_reachable

    try:
        from . import app_config

        app_config.load_logging_config()
        checks["configuration"] = True
    except Exception:  # pragma: no cover
        checks["configuration"] = False

    volumes_ok = True
    writable_ok = True
    for path in paths.all_directories().values():
        if not path.exists():
            volumes_ok = False
        elif not paths.directory_stats(path)["writable"]:
            writable_ok = False
    checks["volumes"] = volumes_ok
    checks["writable"] = writable_ok

    healthy = all(bool(value) for value in checks.values())
    return {
        "status": "ok" if healthy else "degraded",
        "version": APP_VERSION,
        "checks": checks,
    }


# -- Backups (delegated to app.backup_manager) ----------------------------

def list_backups() -> list[dict[str, object]]:
    from . import backup_manager

    return backup_manager.list_backups()


def backup_summary() -> dict[str, object]:
    from . import backup_manager

    return backup_manager.backup_summary()


def create_backup(config=None) -> dict[str, object]:
    from . import backup_manager

    return backup_manager.create_backup(config)
