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


def restore_from_archive(db: Session, archive_path: Path, *, user=None) -> dict:
    """Restore the given archive. Returns a result dict and records history."""
    archive_path = Path(archive_path)
    started = datetime.now()
    username = getattr(user, "username", None) or "-"
    meta = backup_manager.read_metadata(archive_path) or {}
    backup_version = meta.get("app_version") or "unbekannt"
    backup_db_type = meta.get("database_type") or "unbekannt"
    schema_version = meta.get("schema_version")

    log_backup(
        f"Restore gestartet: Datei {archive_path.name}, Backup-Version {backup_version}, "
        f"DB {backup_db_type}",
        user=user,
    )

    status = "error"
    message = ""
    safety_path: Optional[Path] = None
    migrations_applied: list[int] = []

    try:
        analysis = backup_manager.verify(archive_path, user=user)
        if analysis["level"] == "red" or not analysis["has_database"]:
            raise RuntimeError("Backup nicht wiederherstellbar: " + "; ".join(analysis["messages"]))
        if backup_db_type not in ("unbekannt", database.DB_BACKEND):
            raise RuntimeError(
                f"Datenbanktyp {backup_db_type} passt nicht zum System {database.DB_BACKEND}"
            )

        # §6: automatic safety backup for rollback.
        safety_path = backup_manager.create_safety_backup()
        log_backup(f"Sicherheitsbackup erstellt: {safety_path.name}", user=user)

        if database.IS_SQLITE:
            _restore_sqlite(archive_path)
        else:
            _restore_mysql(archive_path)

        config_files = _restore_config(archive_path)

        # Snapshot the *restored* schema state, then bring it up to date (§7/§8):
        # create any tables the (older) backup lacked, then run all outstanding
        # migrations. The diff reports what the restore had to upgrade.
        before = db_schema.applied_versions(database.engine)
        from . import db_migrations, models

        models.Base.metadata.create_all(bind=database.engine)
        db_migrations.run()
        after = db_schema.applied_versions(database.engine)
        migrations_applied = sorted(after - before)
        if migrations_applied:
            log_backup(
                f"Migrationen nach Restore ausgeführt: {migrations_applied}", user=user
            )

        status = "warning" if analysis["level"] == "yellow" else "success"
        message = (
            f"Restore erfolgreich (Version {backup_version}, {config_files} Konfig-Dateien, "
            f"Migrationen {migrations_applied or 'keine'})"
        )
        log_backup(f"Restore erfolgreich: {archive_path.name} – {message}", user=user)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        log_backup(f"Restore fehlgeschlagen: {archive_path.name} – {message}",
                   level=logging.ERROR, user=user)

    finished = datetime.now()
    crud.add_restore_run(
        db,
        started_at=started,
        finished_at=finished,
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
    return {
        "status": status,
        "message": message,
        "safety_backup": safety_path.name if safety_path else None,
        "migrations_applied": migrations_applied,
    }
