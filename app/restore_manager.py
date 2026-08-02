"""Rücksicherung eines Sicherungsarchivs in das laufende System.

Ablauf:

1. Archiv prüfen – es muss einen brauchbaren Datenbankstand enthalten,
2. selbsttätig eine Sicherheitskopie anlegen (Rückfallpunkt),
3. Datenbank (SQLite-Dateitausch bzw. logischer Import) und Konfiguration
   ersetzen,
4. alle offenen Migrationen ausführen – ältere Sicherungen ziehen dadurch
   automatisch auf den aktuellen Stand nach,
5. den Vorgang in ``restore_runs`` und ``backup.log`` festhalten.

Gegen Pfadtraversierung und manipulierte Archive wird durchgehend geprüft.
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

from . import backup_manager, crud, data_transfer, database, db_schema, logging_setup, paths
from .backup_manager import log_backup


def log_db(message: str, *, level: int = logging.INFO, user=None) -> None:
    """Cross-database / migration restore events also go to database.log (§17)."""
    try:
        logging_setup.log_database(message, level=level, user=user)
    except Exception:  # pragma: no cover - logging must never break a restore
        pass


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
    _harden_restored_secrets()
    return restored


def _harden_restored_secrets() -> None:
    """Dateirechte der Lizenzdatei nach dem Auspacken wieder verengen.

    ``license.json`` enthält den Aktivierungsschlüssel und wird von
    :func:`app.licensing.save_config` mit 0600 geschrieben. Beim Auspacken
    eines Archivs gehen diese Rechte verloren (ab 0.11.0).
    """
    from . import licensing

    licensing.harden_config_permissions()


def validate_restore(archive_path: Path) -> tuple[bool, str, dict]:
    """Vorabprüfung auf Unversehrtheit und Verträglichkeit.

    Läuft noch in der Anfrage, bevor der Auftrag eingestellt wird. Ein
    unbrauchbares Archiv wird dadurch sofort und mit klarer Begründung
    abgewiesen – nicht mit einem Serverfehler.
    """
    archive_path = Path(archive_path)
    meta = backup_manager.read_metadata(archive_path) or {}
    analysis = backup_manager.verify(archive_path)
    if not analysis["integrity"]:
        return False, "Backup-Archiv ist beschädigt oder unlesbar.", meta
    if analysis["level"] == "red" or not analysis["has_database"]:
        return False, "Backup enthält keine wiederherstellbare Datenbank.", meta
    # Logische Sicherungen sind datenbankunabhängig und lassen sich in **jede**
    # laufende Datenbank einspielen. Nur alte Sicherungen mit rohem Dateiabzug
    # verlangen denselben Datenbanktyp.
    if backup_manager.has_logical_data(archive_path):
        return True, "Backup ist wiederherstellbar (datenbankunabhängig).", meta
    backup_db_type = meta.get("database_type") or "unbekannt"
    if backup_db_type not in ("unbekannt", database.DB_BACKEND):
        return (
            False,
            f"Älteres Datei-Backup vom Typ {backup_db_type} kann nicht in "
            f"{database.DB_BACKEND} wiederhergestellt werden (kein logisches Backup).",
            meta,
        )
    return True, "Backup ist wiederherstellbar.", meta


def restore_preview(archive_path: Path) -> dict:
    """Backup + current-system summary shown before a restore (§11)."""
    archive_path = Path(archive_path)
    meta = backup_manager.read_metadata(archive_path) or {}
    counts = meta.get("counts") or {}
    # Bei Archiven aus der Zeit vor den Metadaten notfalls im logischen Export zählen.
    if not counts:
        logical = backup_manager.read_logical_data(archive_path)
        if logical:
            all_counts = data_transfer.table_counts_from_export(logical)
            counts = {
                name: all_counts.get(name, 0)
                for name in ("users", "time_entries", "vacation_requests", "holidays", "terminals")
            }
    from . import db_migrator

    return {
        "backup": {
            "file": archive_path.name,
            "app_version": meta.get("app_version") or "unbekannt",
            "created_at": meta.get("created_at"),
            "backup_format_version": meta.get("backup_format_version"),
            "database_type": meta.get("database_type") or "unbekannt",
            "schema_version": meta.get("schema_version"),
            "logical": backup_manager.has_logical_data(archive_path),
            "counts": counts,
        },
        "current": {
            "app_version": backup_manager.APP_VERSION,
            "database_type": database.DB_BACKEND,
            "database_version": db_migrator._server_version(database.engine),
        },
        "note": (
            "Die Daten werden in die aktuell konfigurierte Datenbank importiert. "
            "Die Datenbankkonfiguration bleibt unverändert."
        ),
    }


def _restore_logical(
    archive_path: Path, payload: dict, *, username: str, token: str
) -> tuple[dict, list[int]]:
    """Datenbankunabhängige Rücksicherung in die **laufende** Datenbank.

    Weder die aktive Datenbank noch ihre Konfiguration noch der Datenbanktyp
    werden dabei verändert – eingespielt werden ausschließlich Daten.

    Der Import läuft über :func:`data_transfer.import_database` in **einer**
    Transaktion; ein Fehler hinterlässt deshalb keinen halben Stand.
    """
    from . import db_migrations, models

    source_type = (backup_manager.read_metadata(archive_path) or {}).get("database_type") or "unbekannt"
    log_db(f"Quell-Datenbank erkannt: {source_type} (Job {token})", user=username)
    log_db(f"Ziel-Datenbank erkannt: {database.DB_BACKEND} (Job {token})", user=username)
    log_db(f"Cross-Database Restore gestartet: {source_type} → {database.DB_BACKEND} (Job {token})",
           user=username)

    # Das Schema **vor** dem Import auf den aktuellen Stand bringen, damit jede
    # Spalte vorhanden ist, die die Sicherung erwartet. Ältere Sicherungen
    # lassen neuere Spalten schlicht weg.
    models.Base.metadata.create_all(bind=database.engine)
    db_migrations.run()

    imported = data_transfer.import_database(database.engine, payload)
    total = sum(imported.values())
    log_db(
        f"Cross-Database Restore erfolgreich: {total} Datensätze importiert (Job {token})",
        user=username,
    )

    # Migration nach Restore (idempotent – die Live-DB ist bereits aktuell).
    before = db_schema.applied_versions(database.engine)
    db_migrations.run()
    after = db_schema.applied_versions(database.engine)
    migrations_applied = sorted(after - before)
    log_db(f"Migration nach Restore erfolgreich (Job {token})", user=username)
    return imported, migrations_applied


def _verify_logical_restore(imported: dict) -> tuple[bool, str]:
    """Prüfung: Die Zeilenzahlen in der Datenbank müssen den importierten entsprechen."""
    current = data_transfer.current_row_counts(database.engine)
    mismatches = [
        f"{table} (importiert {count} / aktiv {current.get(table, 0)})"
        for table, count in imported.items()
        if current.get(table, -1) != count
    ]
    if mismatches:
        return False, "Integritätsprüfung fehlgeschlagen: " + ", ".join(mismatches)
    return True, "Integritätsprüfung erfolgreich"


def perform_restore(
    archive_path: Path,
    *,
    username: str = "-",
    token: str = "",
    progress=None,
) -> dict:
    """Rücksicherung im Hintergrund ausführen – **nicht** in der Anfrage.

    Arbeitet mit eigenen Datenbanksitzungen, tauscht die Datenbank, führt die
    Migrationen aus und schreibt die Historie. Bei jedem Schritt wird
    ``progress(state, percent, message)`` aufgerufen, damit die Statusabfrage
    den Fortschritt zeigen kann.
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
    log_backup(f"Backup analysiert: {archive_path.name}", user=username)
    log_backup(f"Backup-Metadaten gelesen (Format {meta.get('backup_format_version', '-')})", user=username)

    status = "error"
    message = ""
    safety_path: Optional[Path] = None
    migrations_applied: list[int] = []

    try:
        ok, reason, _meta = validate_restore(archive_path)
        if not ok:
            raise RuntimeError(reason)
        analysis = backup_manager.verify(archive_path)
        logical = backup_manager.read_logical_data(archive_path)

        # §6/§12: mandatory pre-restore safety backup for rollback.
        emit("creating_backup", 15, "Sicherheitsbackup wird erstellt")
        safety_path = backup_manager.create_safety_backup()
        log_backup(f"Sicherheitsbackup erstellt: {safety_path.name} (Job {token})", user=username)

        if logical is not None:
            # Datenbankunabhängige Rücksicherung: Die laufende Datenbank, ihre
            # Konfiguration und der Datenbanktyp bleiben unverändert –
            # eingespielt werden ausschließlich Daten.
            emit("restoring", 45, "Daten werden importiert (datenbankunabhängig)")
            imported, migrations_applied = _restore_logical(
                archive_path, logical, username=username, token=token
            )
            config_files = _restore_config(archive_path)
            log_backup(
                f"Daten importiert: {sum(imported.values())} Datensätze, "
                f"{config_files} Konfig-Dateien (Job {token})",
                user=username,
            )
            log_backup("Migration gestartet", user=username)
            log_backup(
                f"Migration erfolgreich: {migrations_applied or 'keine ausstehend'}", user=username
            )

            emit("running_migrations", 80, "Integrität wird geprüft")
            integrity_ok, integrity_msg = _verify_logical_restore(imported)
            if not integrity_ok:
                raise RuntimeError(integrity_msg)
            log_backup(integrity_msg, user=username)
            log_backup("Anwendung wieder verfügbar", user=username)
            status = "success"
            message = (
                f"Cross-Database Restore erfolgreich (Version {backup_version} "
                f"[{backup_db_type}] → {database.DB_BACKEND}, {sum(imported.values())} Datensätze, "
                f"Migrationen {migrations_applied or 'keine'})"
            )
        else:
            # Legacy raw-snapshot backup (pre-0.9.9): same-type file restore.
            emit("restoring", 45, "Backup wird wiederhergestellt")
            if database.IS_SQLITE:
                _restore_sqlite(archive_path)
            else:
                _restore_mysql(archive_path)
            config_files = _restore_config(archive_path)
            log_backup(f"Datenbank und Konfiguration wiederhergestellt (Job {token})", user=username)

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
        log_db(
            f"Cross-Database Restore fehlgeschlagen: {message} (Job {token})",
            level=logging.ERROR, user=username,
        )
        emit("failed", 100, message)

    finished = datetime.now()
    duration = (finished - started).total_seconds()
    # Historie in einer frischen Sitzung schreiben, die an der
    # zurückgesicherten Datenbank hängt.
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
    """Rücksicherung im selben Thread – für Tests und die Kommandozeile.

    Die Oberfläche benutzt stattdessen den Hintergrundlauf
    :mod:`app.restore_jobs`.
    """
    resolved_user = username or getattr(user, "username", None) or "-"
    return perform_restore(archive_path, username=resolved_user, token=token, progress=progress)
