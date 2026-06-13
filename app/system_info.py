"""System status, backup and health information for the administration area."""

from __future__ import annotations

import sqlite3
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from . import __version__ as APP_VERSION
from . import database, log_tools, models, paths
from .integrations import timemoto

BACKUP_DIR = paths.DATA_DIR / "backups"


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
    url = database.SQLALCHEMY_DATABASE_URL
    db_type = url.split(":", 1)[0] if ":" in url else "unbekannt"
    reachable = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - depends on backend
        reachable = False
    db_path = _database_path()
    size = db_path.stat().st_size if db_path and db_path.exists() else 0
    user_version = None
    if db_path and db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("PRAGMA user_version").fetchone()
                user_version = int(row[0]) if row else None
        except sqlite3.Error:  # pragma: no cover
            user_version = None
    return {
        "type": db_type,
        "reachable": reachable,
        "size_bytes": size,
        "size_human": paths.format_size(size),
        "schema_version": user_version,
        "path": str(db_path) if db_path else url,
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


def pending_sync_count(db: Session) -> int:
    try:
        return int(db.query(func.count(models.MobileSyncAction.id)).scalar() or 0)
    except Exception:  # pragma: no cover
        return 0


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
        "pending_sync": pending_sync_count(db),
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


# -- Backups ---------------------------------------------------------------

def list_backups() -> list[dict[str, object]]:
    backups: list[dict[str, object]] = []
    if BACKUP_DIR.exists():
        for path in sorted(BACKUP_DIR.glob("*.zip"), reverse=True):
            try:
                stat = path.stat()
            except OSError:  # pragma: no cover
                continue
            backups.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "size_human": paths.format_size(stat.st_size),
                    "created": datetime.fromtimestamp(stat.st_mtime),
                }
            )
    return backups


def backup_summary() -> dict[str, object]:
    backups = list_backups()
    latest = backups[0] if backups else None
    return {
        "count": len(backups),
        "location": str(BACKUP_DIR),
        "latest": latest,
        "backups": backups,
    }


def create_backup() -> dict[str, object]:
    """Create a ZIP backup of the database and the configuration volume."""

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = BACKUP_DIR / f"backup_{timestamp}.zip"
    db_path = _database_path()
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if db_path and db_path.exists():
            archive.write(db_path, arcname=f"data/{db_path.name}")
        if paths.CONFIG_DIR.exists():
            for entry in paths.CONFIG_DIR.rglob("*"):
                if entry.is_file():
                    archive.write(entry, arcname=f"config/{entry.relative_to(paths.CONFIG_DIR)}")
    stat = archive_path.stat()
    return {
        "name": archive_path.name,
        "path": str(archive_path),
        "size_bytes": stat.st_size,
        "size_human": paths.format_size(stat.st_size),
        "created": datetime.fromtimestamp(stat.st_mtime),
    }
