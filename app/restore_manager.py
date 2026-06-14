"""Backup restore engine (§1, §5-§8).

Restores a backup archive into the live system:
1. verify the archive (must contain a usable database snapshot),
2. create an automatic pre-restore safety backup (rollback),
3. replace the database (SQLite file swap / MySQL import) and configuration,
4. run all outstanding migrations automatically (older backups are upgraded),
5. record the operation in ``restore_runs`` and ``backup.log``.

Path traversal and archive manipulation are guarded throughout (§24).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from . import backup_manager, crud, database, db_schema, paths
from .backup_manager import log_backup


def _safe_extract_member(archive: zipfile.ZipFile, member: str, dest_root: Path) -> Optional[Path]:
    """Extract ``member`` under ``dest_root`` guarding against path traversal."""
    rel = member.split("/", 1)[1] if "/" in member else member
    if not rel or rel.endswith("/"):
        return None
    target = (dest_root / rel).resolve()
    try:
        target.relative_to(dest_root.resolve())
    except ValueError:
        return None  # path traversal attempt -> skip
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member) as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    return target


def _restore_sqlite(archive_path: Path) -> None:
    target = backup_manager._sqlite_path()
    if not target:
        raise RuntimeError("SQLite-Zielpfad nicht ermittelbar")
    with zipfile.ZipFile(archive_path) as archive:
        members = [n for n in archive.namelist() if n.startswith("data/") and n.endswith(".db")]
        if not members:
            raise RuntimeError("Kein SQLite-Snapshot (data/*.db) im Backup enthalten")
        data = archive.read(members[0])
    # Release pooled connections before swapping the file.
    database.engine.dispose()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".restore-tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    database.engine.dispose()


def _restore_mysql(archive_path: Path) -> None:
    if shutil.which("mysql") is None:
        raise RuntimeError("mysql-Client nicht verfügbar – MySQL-Restore nicht möglich")
    with zipfile.ZipFile(archive_path) as archive:
        members = [n for n in archive.namelist() if n.startswith("data/") and n.endswith(".sql")]
        if not members:
            raise RuntimeError("Kein MySQL-Dump (data/*.sql) im Backup enthalten")
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "restore.sql"
            dump.write_bytes(archive.read(members[0]))
            url = make_url(database.SQLALCHEMY_DATABASE_URL)
            cmd = ["mysql"]
            if url.host:
                cmd += ["-h", url.host]
            if url.port:
                cmd += ["-P", str(url.port)]
            if url.username:
                cmd += ["-u", url.username]
            import os

            env = dict(os.environ)
            if url.password:
                env["MYSQL_PWD"] = url.password
            cmd.append(url.database or "")
            with dump.open("rb") as handle:
                subprocess.run(cmd, check=True, stdin=handle, stderr=subprocess.PIPE, env=env)
    database.engine.dispose()


def _restore_config(archive_path: Path) -> int:
    restored = 0
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.namelist():
            if member.startswith("config/") and not member.endswith("/"):
                if _safe_extract_member(archive, member, paths.CONFIG_DIR):
                    restored += 1
    return restored


def validate_restore(archive_path: Path) -> tuple[bool, str, dict]:
    """Synchronous pre-flight checks (§ Schritt 2): integrity + compatibility.

    Runs in the request thread before a restore job is queued, so invalid
    backups are rejected immediately with a clear message (never a 500).
    """
    archive_path = Path(archive_path)
    meta = backup_manager.read_metadata(archive_path) or {}
    analysis = backup_manager.verify(archive_path)
    if not analysis["integrity"]:
        return False, "Backup-Archiv ist beschädigt oder unlesbar.", meta
    if analysis["level"] == "red" or not analysis["has_database"]:
        return False, "Backup enthält keine wiederherstellbare Datenbank.", meta
    backup_db_type = meta.get("database_type") or "unbekannt"
    if backup_db_type not in ("unbekannt", database.DB_BACKEND):
        return (
            False,
            f"Datenbanktyp {backup_db_type} passt nicht zum System ({database.DB_BACKEND}).",
            meta,
        )
    return True, "Backup ist wiederherstellbar.", meta


def perform_restore(
    archive_path: Path,
    *,
    username: str = "-",
    token: str = "",
    progress=None,
) -> dict:
    """Execute a restore in a background worker (NOT in the request thread).

    Uses its own DB sessions, swaps the database, runs migrations and records
    history. ``progress(state, percent, message)`` is invoked at each step so the
    status API can report live progress.
    """
    archive_path = Path(archive_path)
    started = datetime.now()
    meta = backup_manager.read_metadata(archive_path) or {}
    backup_version = meta.get("app_version") or "unbekannt"
    backup_db_type = meta.get("database_type") or "unbekannt"
    schema_version = meta.get("schema_version")

    def emit(state: str, percent: int, message: str) -> None:
        if progress:
            progress(state, percent, message)

    log_backup(
        f"Restore gestartet: Datei {archive_path.name}, Backup-Version {backup_version}, "
        f"DB {backup_db_type} (Job {token})",
        user=username,
    )

    status = "error"
    message = ""
    safety_path: Optional[Path] = None
    migrations_applied: list[int] = []

    try:
        ok, reason, _meta = validate_restore(archive_path)
        if not ok:
            raise RuntimeError(reason)
        analysis = backup_manager.verify(archive_path)

        # §6: mandatory pre-restore safety backup for rollback.
        emit("creating_backup", 15, "Sicherheitsbackup wird erstellt")
        safety_path = backup_manager.create_safety_backup()
        log_backup(f"Sicherheitsbackup erstellt: {safety_path.name} (Job {token})", user=username)

        emit("restoring", 45, "Backup wird wiederhergestellt")
        if database.IS_SQLITE:
            _restore_sqlite(archive_path)
        else:
            _restore_mysql(archive_path)
        config_files = _restore_config(archive_path)
        log_backup(f"Datenbank und Konfiguration wiederhergestellt (Job {token})", user=username)

        # Reinitialise database connections cleanly after the swap.
        emit("restarting", 60, "Datenbankverbindung wird neu initialisiert")
        log_backup("Anwendung wird neu gestartet (Datenbankverbindung)", user=username)
        database.engine.dispose()

        emit("running_migrations", 75, "Migrationen werden ausgeführt")
        before = db_schema.applied_versions(database.engine)
        from . import db_migrations, models

        models.Base.metadata.create_all(bind=database.engine)
        log_backup("Migration gestartet", user=username)
        db_migrations.run()
        after = db_schema.applied_versions(database.engine)
        migrations_applied = sorted(after - before)
        log_backup(
            f"Migration erfolgreich: {migrations_applied or 'keine ausstehend'}", user=username
        )
        log_backup("Anwendung wieder verfügbar", user=username)

        status = "warning" if analysis["level"] == "yellow" else "success"
        message = (
            f"Restore erfolgreich (Version {backup_version}, {config_files} Konfig-Dateien, "
            f"Migrationen {migrations_applied or 'keine'})"
        )
        log_backup(f"Restore erfolgreich: {archive_path.name} – {message} (Job {token})", user=username)
        emit("completed", 100, "Wiederherstellung erfolgreich abgeschlossen")
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        log_backup(
            f"Restore fehlgeschlagen: {archive_path.name} – {message} (Job {token})",
            level=logging.ERROR, user=username,
        )
        log_backup("Migration fehlgeschlagen oder übersprungen", level=logging.WARNING, user=username)
        emit("failed", 100, message)

    finished = datetime.now()
    duration = (finished - started).total_seconds()
    # Record history in a fresh session bound to the (restored) database.
    try:
        history_db = database.SessionLocal()
        try:
            crud.add_restore_run(
                history_db,
                started_at=started,
                finished_at=finished,
                duration_seconds=duration,
                log_token=token,
                username=username,
                backup_file=archive_path.name,
                backup_version=str(backup_version),
                database_type=str(backup_db_type),
                schema_version=schema_version,
                safety_backup=safety_path.name if safety_path else None,
                migrations_applied=",".join(str(v) for v in migrations_applied),
                status=status,
                message=message,
            )
        finally:
            history_db.close()
    except Exception:  # pragma: no cover - history must never mask the result
        log_backup("Restore-Historie konnte nicht geschrieben werden", level=logging.ERROR, user=username)

    return {
        "status": status,
        "message": message,
        "safety_backup": safety_path.name if safety_path else None,
        "migrations_applied": migrations_applied,
        "duration_seconds": duration,
    }


def restore_from_archive(archive_path: Path, *, user=None, username: str = "", progress=None, token: str = "") -> dict:
    """Backwards-compatible synchronous restore (used by tests/CLI).

    The web UI uses the asynchronous :mod:`app.restore_jobs` worker instead.
    """
    resolved_user = username or getattr(user, "username", None) or "-"
    return perform_restore(archive_path, username=resolved_user, token=token, progress=progress)
