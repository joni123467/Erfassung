"""Job-based backup engine (§0.9.2).

Each :class:`app.models.BackupJob` defines what to back up (database / config /
logs), where to store it (local / FTP / SMB) and how long to keep it. Runs are
recorded as :class:`app.models.BackupRun` history rows.

Design goals:
* consistent database snapshots (SQLite online-backup API; mysqldump for MySQL)
* integrity check after every run (file present, plausible size, readable ZIP)
* per-job retention (count and/or age), best-effort on remote targets
* credentials are persisted in the DB but never written to any log
"""

from __future__ import annotations

import logging
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from . import __version__ as APP_VERSION
from . import crud, database, db_schema, logging_setup, paths

LOGGER = logging.getLogger("erfassung.application")

BACKUP_DIR = paths.DATA_DIR / "backups"
UPLOAD_DIR = paths.DATA_DIR / "uploads"
META_NAME = "backup_meta.json"


def log_backup(message, *, level=logging.INFO, user=None):
    """Backup/restore events go to the dedicated backup.log (§11-§18)."""
    try:
        logging_setup.log_backup(message, level=level, user=user)
    except Exception:  # pragma: no cover - logging must never break a backup
        LOGGER.info(message)


# -- database snapshot helpers --------------------------------------------

def _sqlite_path() -> Optional[Path]:
    url = database.SQLALCHEMY_DATABASE_URL
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        db_path = Path(raw)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        return db_path
    return None


def _dump_database(staging: Path) -> tuple[Optional[Path], Optional[str]]:
    """Return (snapshot_path, warning). Snapshot is consistent for SQLite."""
    if database.IS_SQLITE:
        src = _sqlite_path()
        if not src or not src.exists():
            return None, "SQLite-Datei nicht gefunden"
        snapshot = staging / "erfassung.db"
        # Online backup API -> consistent snapshot even during writes.
        with sqlite3.connect(src) as source, sqlite3.connect(snapshot) as dest:
            source.backup(dest)
        return snapshot, None

    # MySQL/MariaDB: use mysqldump when available.
    if shutil.which("mysqldump") is None:
        return None, "mysqldump nicht verfügbar – Datenbank wurde nicht gesichert"
    url = make_url(database.SQLALCHEMY_DATABASE_URL)
    snapshot = staging / "erfassung.sql"
    cmd = ["mysqldump", "--single-transaction", "--routines", "--triggers"]
    if url.host:
        cmd += ["-h", url.host]
    if url.port:
        cmd += ["-P", str(url.port)]
    if url.username:
        cmd += ["-u", url.username]
    env = dict(os.environ)
    if url.password:
        env["MYSQL_PWD"] = url.password  # avoids password on the command line
    cmd.append(url.database or "")
    try:
        with snapshot.open("wb") as handle:
            subprocess.run(cmd, check=True, stdout=handle, stderr=subprocess.PIPE, env=env)
    except (subprocess.CalledProcessError, OSError) as exc:
        return None, f"mysqldump fehlgeschlagen: {type(exc).__name__}"
    return snapshot, None


# -- metadata --------------------------------------------------------------

def _build_metadata(contents: list[str], backup_type: str) -> dict:
    """Metadata embedded in every archive for compatibility checks (§10)."""
    schema_version = None
    try:
        schema_version = db_schema.latest_applied_version(database.engine)
    except Exception:  # pragma: no cover
        schema_version = None
    return {
        "app_version": APP_VERSION,
        "database_type": database.DB_BACKEND,
        "schema_version": schema_version,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "backup_type": backup_type,
        "contents": contents,
    }


def read_metadata(archive_path: Path) -> Optional[dict]:
    """Read the embedded backup metadata, or None if absent/unreadable."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if META_NAME not in archive.namelist():
                return None
            return json.loads(archive.read(META_NAME).decode("utf-8"))
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError, ValueError):
        return None


# -- archive ---------------------------------------------------------------

def _build_archive(job, staging: Path, *, backup_type: str = "job") -> tuple[Path, list[str]]:
    """Build the ZIP for ``job`` in ``staging``. Returns (path, warnings)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archive_path = BACKUP_DIR / f"backup_job{job.id}_{timestamp}.zip"
    contents = job.content_list
    warnings: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(META_NAME, json.dumps(_build_metadata(contents, backup_type), indent=2))
            if "database" in contents:
                snapshot, warning = _dump_database(tmp_dir)
                if snapshot:
                    archive.write(snapshot, arcname=f"data/{snapshot.name}")
                if warning:
                    warnings.append(warning)
            if "config" in contents and paths.CONFIG_DIR.exists():
                for entry in paths.CONFIG_DIR.rglob("*"):
                    if entry.is_file():
                        archive.write(entry, arcname=f"config/{entry.relative_to(paths.CONFIG_DIR)}")
            if "logs" in contents and paths.LOGS_DIR.exists():
                for entry in paths.LOGS_DIR.rglob("*"):
                    if entry.is_file():
                        archive.write(entry, arcname=f"logs/{entry.relative_to(paths.LOGS_DIR)}")
    return archive_path, warnings


def create_safety_backup(*, prefix: str = "pre_restore", backup_type: str = "safety") -> Path:
    """Create a safety backup of DB + config (§6).

    ``prefix`` controls the file name so callers can distinguish pre-restore
    safety backups (``pre_restore_*``) from pre/post database-migration
    snapshots (``pre_db_migration_*`` / ``post_db_migration_*``, §0.9.7).
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = BACKUP_DIR / f"{prefix}_{timestamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                META_NAME, json.dumps(_build_metadata(["database", "config"], backup_type), indent=2)
            )
            snapshot, _warning = _dump_database(tmp_dir)
            if snapshot:
                archive.write(snapshot, arcname=f"data/{snapshot.name}")
            if paths.CONFIG_DIR.exists():
                for entry in paths.CONFIG_DIR.rglob("*"):
                    if entry.is_file():
                        archive.write(entry, arcname=f"config/{entry.relative_to(paths.CONFIG_DIR)}")
    return archive_path


def verify_integrity(archive_path: Path) -> tuple[bool, str]:
    if not archive_path.exists():
        return False, "Datei wurde nicht erstellt"
    size = archive_path.stat().st_size
    if size < 64:
        return False, f"Archivgröße unplausibel ({size} Bytes)"
    try:
        with zipfile.ZipFile(archive_path) as archive:
            bad = archive.testzip()
            if bad is not None:
                return False, f"Beschädigter Eintrag im Archiv: {bad}"
            if not archive.namelist():
                return False, "Archiv ist leer"
    except zipfile.BadZipFile:
        return False, "Archiv ist nicht lesbar (kein gültiges ZIP)"
    return True, "Archiv geprüft (lesbar, plausible Größe)"


def verify(archive_path: Path, *, user=None) -> dict:
    """Analyse an archive without restoring it (§4). Returns level/details.

    level: 'green' (verwendbar), 'yellow' (verwendbar mit Hinweisen),
    'red' (nicht verwendbar).
    """
    archive_path = Path(archive_path)
    result = {
        "level": "red",
        "readable": False,
        "integrity": False,
        "has_metadata": False,
        "has_database": False,
        "app_version": None,
        "database_type": None,
        "schema_version": None,
        "messages": [],
    }
    ok, integrity_msg = verify_integrity(archive_path)
    result["integrity"] = ok
    result["readable"] = ok
    if not ok:
        result["messages"].append(integrity_msg)
        log_backup(f"Integritätsprüfung fehlgeschlagen: {archive_path.name} – {integrity_msg}",
                   level=logging.WARNING, user=user)
        return result

    names = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:  # pragma: no cover - already checked
        result["messages"].append("Archiv nicht lesbar")
        return result

    result["has_database"] = any(n.startswith("data/") for n in names)
    meta = read_metadata(archive_path)
    if meta:
        result["has_metadata"] = True
        result["app_version"] = meta.get("app_version")
        result["database_type"] = meta.get("database_type")
        result["schema_version"] = meta.get("schema_version")

    messages = []
    if not result["has_metadata"]:
        messages.append("Keine Metadaten enthalten – Kompatibilität nicht prüfbar")
    if not result["has_database"]:
        messages.append("Kein Datenbank-Snapshot enthalten")
    if result["has_metadata"] and result["database_type"] and result["database_type"] != database.DB_BACKEND:
        messages.append(
            f"Datenbanktyp im Backup ({result['database_type']}) weicht vom aktuellen "
            f"System ({database.DB_BACKEND}) ab"
        )

    if not result["has_database"]:
        result["level"] = "red"
        messages.insert(0, "Backup nicht für Wiederherstellung der Datenbank verwendbar")
    elif messages:
        result["level"] = "yellow"
    else:
        result["level"] = "green"
        messages.append("Backup verwendbar")
    result["messages"] = messages
    log_backup(
        f"Backup-Prüfung {archive_path.name}: {result['level']} "
        f"(Version={result['app_version']}, DB={result['database_type']})",
        user=user,
    )
    return result


def backup_file_info(archive_path: Path) -> dict:
    """Metadata + filesystem info for one local archive (for listings)."""
    path = Path(archive_path)
    stat = path.stat()
    meta = read_metadata(path) or {}
    name = path.name
    if name.startswith(("pre_restore_", "pre_db_migration_", "post_db_migration_")):
        source = "safety"
    elif name.startswith("upload_"):
        source = "upload"
    else:
        source = "local"
    return {
        "name": name,
        "path": str(path),
        "size_bytes": stat.st_size,
        "size_human": paths.format_size(stat.st_size),
        "created": datetime.fromtimestamp(stat.st_mtime),
        "app_version": meta.get("app_version"),
        "database_type": meta.get("database_type"),
        "schema_version": meta.get("schema_version"),
        "backup_type": meta.get("backup_type"),
        "source": source,
    }


def list_local_backups() -> list[dict]:
    """All restorable archives in the local backup directory (incl. uploads)."""
    items: list[dict] = []
    for directory in (BACKUP_DIR,):
        if directory.exists():
            for path in directory.glob("*.zip"):
                try:
                    items.append(backup_file_info(path))
                except OSError:  # pragma: no cover
                    continue
    items.sort(key=lambda i: i["created"], reverse=True)
    return items


def resolve_backup_path(name: str) -> Optional[Path]:
    """Safely resolve a backup file name to a path inside BACKUP_DIR.

    Guards against path traversal (§24): only plain file names within the
    backup directory are accepted.
    """
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    candidate = (BACKUP_DIR / name).resolve()
    try:
        candidate.relative_to(BACKUP_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() else None


# -- SMB helpers -----------------------------------------------------------

def _parse_unc(unc: str) -> tuple[str, str, str]:
    """Split a Windows UNC path ``\\\\server\\share\\sub\\dir`` into parts.

    Returns (server, share, subpath). Accepts forward or back slashes.
    """
    cleaned = (unc or "").strip().replace("/", "\\").lstrip("\\")
    parts = [p for p in cleaned.split("\\") if p]
    server = parts[0] if parts else ""
    share = parts[1] if len(parts) > 1 else ""
    subpath = "\\".join(parts[2:]) if len(parts) > 2 else ""
    return server, share, subpath


def _smb_register(job):
    import smbclient

    server, _share, _sub = _parse_unc(job.smb_path)
    # smbprotocol accepts "DOMAIN\\user" and "user@domain" in ``username``.
    smbclient.register_session(server, username=job.smb_username, password=job.smb_password)
    return smbclient, server


# -- transfer --------------------------------------------------------------

def _transfer(job, archive_path: Path) -> tuple[str, Optional[str]]:
    """Move/upload the archive to the job target. Returns (location, local_file)."""
    if job.target_type == "local":
        dest_dir = Path(job.local_path) if job.local_path else BACKUP_DIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        final = dest_dir / archive_path.name
        if final != archive_path:
            shutil.move(str(archive_path), str(final))
        return str(final), str(final)

    if job.target_type == "ftp":
        import ftplib

        cls = ftplib.FTP_TLS if job.ftp_use_tls else ftplib.FTP
        ftp = cls()
        ftp.connect(job.ftp_host, job.ftp_port or 21, timeout=30)
        ftp.login(job.ftp_username, job.ftp_password)
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        try:
            target_dir = job.ftp_path or "/"
            if target_dir and target_dir != "/":
                try:
                    ftp.cwd(target_dir)
                except ftplib.error_perm:
                    ftp.mkd(target_dir)
                    ftp.cwd(target_dir)
            with archive_path.open("rb") as handle:
                ftp.storbinary(f"STOR {archive_path.name}", handle)
        finally:
            ftp.quit()
        archive_path.unlink(missing_ok=True)
        return f"ftp://{job.ftp_host}{job.ftp_path}", None

    if job.target_type == "smb":
        smbclient, server = _smb_register(job)
        try:
            _srv, share, sub = _parse_unc(job.smb_path)
            remote_dir = f"\\\\{server}\\{share}"
            if sub:
                remote_dir += "\\" + sub
            try:
                smbclient.makedirs(remote_dir, exist_ok=True)
            except Exception:  # pragma: no cover - already exists
                pass
            remote_file = f"{remote_dir}\\{archive_path.name}"
            with archive_path.open("rb") as src, smbclient.open_file(remote_file, mode="wb") as dst:
                dst.write(src.read())
        finally:
            try:
                smbclient.delete_session(server)
            except Exception:  # pragma: no cover
                pass
        archive_path.unlink(missing_ok=True)
        return job.smb_path, None

    return str(archive_path), str(archive_path)


# -- retention -------------------------------------------------------------

def _retention_cutoff(job) -> Optional[float]:
    if job.retention_days and job.retention_days > 0:
        return datetime.now().timestamp() - job.retention_days * 24 * 3600
    return None


def _apply_local_retention(job, directory: Path) -> int:
    archives = sorted(
        directory.glob(f"backup_job{job.id}_*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    remove: set[Path] = set()
    if job.retention_count and job.retention_count > 0 and len(archives) > job.retention_count:
        remove.update(archives[job.retention_count:])
    cutoff = _retention_cutoff(job)
    if cutoff is not None:
        remove.update(a for a in archives if a.stat().st_mtime < cutoff)
    removed = 0
    freed = 0
    for archive in remove:
        try:
            freed += archive.stat().st_size
            archive.unlink()
            removed += 1
        except OSError:  # pragma: no cover
            continue
    if removed:
        # §17: log retention cleanup (job, count, freed space).
        log_backup(
            f"Aufbewahrung '{job.name}': {removed} alte Sicherung(en) gelöscht, "
            f"{paths.format_size(freed)} freigegeben"
        )
    return removed


def apply_retention(job) -> int:
    """Prune old archives for ``job`` according to its retention rules."""
    try:
        if job.target_type == "local":
            directory = Path(job.local_path) if job.local_path else BACKUP_DIR
            return _apply_local_retention(job, directory)
        if job.target_type == "ftp":
            return _apply_ftp_retention(job)
        if job.target_type == "smb":
            return _apply_smb_retention(job)
    except Exception as exc:  # pragma: no cover - remote best effort
        LOGGER.warning("Backup-Retention (%s) fehlgeschlagen: %s", job.target_type, exc)
    return 0


def _select_for_removal(names_with_mtime: list[tuple[str, float]], job) -> list[str]:
    names_with_mtime.sort(key=lambda item: item[1], reverse=True)
    remove: list[str] = []
    if job.retention_count and job.retention_count > 0 and len(names_with_mtime) > job.retention_count:
        remove += [n for n, _ in names_with_mtime[job.retention_count:]]
    cutoff = _retention_cutoff(job)
    if cutoff is not None:
        remove += [n for n, m in names_with_mtime if m < cutoff and n not in remove]
    return remove


def _apply_ftp_retention(job) -> int:
    import ftplib

    cls = ftplib.FTP_TLS if job.ftp_use_tls else ftplib.FTP
    ftp = cls()
    ftp.connect(job.ftp_host, job.ftp_port or 21, timeout=30)
    ftp.login(job.ftp_username, job.ftp_password)
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    removed = 0
    try:
        if job.ftp_path and job.ftp_path != "/":
            ftp.cwd(job.ftp_path)
        # FTP lacks reliable mtimes via NLST; the timestamped filename sorts
        # chronologically, so lexical descending order keeps the newest.
        names = [
            name.rsplit("/", 1)[-1]
            for name in ftp.nlst()
            if name.rsplit("/", 1)[-1].startswith(f"backup_job{job.id}_")
        ]
        names.sort(reverse=True)
        keep = job.retention_count if job.retention_count and job.retention_count > 0 else len(names)
        for base in names[keep:]:
            try:
                ftp.delete(base)
                removed += 1
            except ftplib.error_perm:  # pragma: no cover
                continue
    finally:
        ftp.quit()
    return removed


def _apply_smb_retention(job) -> int:
    smbclient, server = _smb_register(job)
    removed = 0
    try:
        _srv, share, sub = _parse_unc(job.smb_path)
        remote_dir = f"\\\\{server}\\{share}"
        if sub:
            remote_dir += "\\" + sub
        entries: list[tuple[str, float]] = []
        for name in smbclient.listdir(remote_dir):
            if name.startswith(f"backup_job{job.id}_"):
                try:
                    info = smbclient.stat(f"{remote_dir}\\{name}")
                    entries.append((name, info.st_mtime))
                except Exception:  # pragma: no cover
                    entries.append((name, 0.0))
        for name in _select_for_removal(entries, job):
            try:
                smbclient.remove(f"{remote_dir}\\{name}")
                removed += 1
            except Exception:  # pragma: no cover
                continue
    finally:
        try:
            smbclient.delete_session(server)
        except Exception:  # pragma: no cover
            pass
    return removed


# -- run + test ------------------------------------------------------------

def run_job(db: Session, job, *, triggered_by: str = "manual", user=None) -> "object":
    """Execute ``job``: build, verify, transfer, prune, record history."""
    started = datetime.now()
    status = "error"
    message = ""
    size = 0
    location = "-"
    local_file: Optional[str] = None
    # §12: log start (never include credentials, only the target type/path).
    log_backup(f"Backup gestartet: Job '{job.name}' (Typ {job.target_type}, Auslöser {triggered_by})", user=user)
    try:
        archive_path, warnings = _build_archive(job, BACKUP_DIR)
        ok, integrity_msg = verify_integrity(archive_path)
        size = archive_path.stat().st_size if archive_path.exists() else 0
        if not ok:
            message = f"Integritätsprüfung fehlgeschlagen: {integrity_msg}"
            LOGGER.error("Backup-Job %s: %s", job.name, message)
            archive_path.unlink(missing_ok=True)
        else:
            location, local_file = _transfer(job, archive_path)
            removed = apply_retention(job)
            status = "warning" if warnings else "success"
            parts = [integrity_msg, f"Ziel: {location}"]
            if warnings:
                parts.append("Warnungen: " + "; ".join(warnings))
            if removed:
                parts.append(f"{removed} alte Sicherung(en) entfernt")
            message = " · ".join(parts)
            LOGGER.info("Backup-Job '%s' (%s) – %s", job.name, triggered_by, status)
    except Exception as exc:  # pragma: no cover - depends on target
        message = f"{type(exc).__name__}: {exc}"
        LOGGER.error("Backup-Job '%s' fehlgeschlagen: %s", job.name, exc)

    finished = datetime.now()
    duration = (finished - started).total_seconds()
    # §12/§13: log result (Jobname, Ziel, Dateiname, Größe, Dauer, Ergebnis).
    if status == "error":
        log_backup(
            f"Backup fehlgeschlagen: Job '{job.name}', Ziel {job.target_type}: {message}",
            level=logging.ERROR, user=user,
        )
    else:
        log_backup(
            f"Backup erfolgreich: Job '{job.name}', Ziel {location}, "
            f"Datei {Path(local_file).name if local_file else '-'}, "
            f"{paths.format_size(size)}, {duration:.1f}s, Status {status}",
            user=user,
        )
    run = crud.add_backup_run(
        db,
        job_id=job.id,
        job_name=job.name,
        target_type=job.target_type,
        started_at=started,
        finished_at=finished,
        duration_seconds=(finished - started).total_seconds(),
        size_bytes=size,
        status=status,
        message=message,
        filename=local_file,
    )
    crud.update_backup_job(db, job.id, last_run_at=finished, last_status=status)
    crud.prune_backup_runs(db, job.id)
    return run


def test_connection(job, *, user=None) -> tuple[bool, str]:
    """Verify the job's target is reachable without creating a backup."""
    ok, message = _test_connection(job)
    # §16: log connection tests (target type, result) – never credentials.
    target = job.target_type
    if target == "ftp":
        target = f"ftp://{job.ftp_host}"
    elif target == "smb":
        target = job.smb_path
    log_backup(
        f"Verbindungstest {job.target_type} ({target}): {'erfolgreich' if ok else 'fehlgeschlagen'}",
        level=logging.INFO if ok else logging.WARNING, user=user,
    )
    return ok, message


def _test_connection(job) -> tuple[bool, str]:
    try:
        if job.target_type == "local":
            directory = Path(job.local_path) if job.local_path else BACKUP_DIR
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True, f"Lokaler Pfad beschreibbar: {directory}"
        if job.target_type == "ftp":
            import ftplib

            cls = ftplib.FTP_TLS if job.ftp_use_tls else ftplib.FTP
            ftp = cls()
            ftp.connect(job.ftp_host, job.ftp_port or 21, timeout=15)
            ftp.login(job.ftp_username, job.ftp_password)
            if isinstance(ftp, ftplib.FTP_TLS):
                ftp.prot_p()
            ftp.voidcmd("NOOP")
            ftp.quit()
            return True, "FTP-Verbindung erfolgreich"
        if job.target_type == "smb":
            smbclient, server = _smb_register(job)
            try:
                _srv, share, sub = _parse_unc(job.smb_path)
                remote_dir = f"\\\\{server}\\{share}"
                if sub:
                    remote_dir += "\\" + sub
                smbclient.listdir(remote_dir)
            finally:
                try:
                    smbclient.delete_session(server)
                except Exception:  # pragma: no cover
                    pass
            return True, "SMB3-Verbindung erfolgreich"
        return False, "Unbekannter Backup-Typ"
    except ModuleNotFoundError as exc:
        return False, f"Erforderliche Bibliothek fehlt: {exc.name}"
    except Exception as exc:  # pragma: no cover - depends on target
        return False, f"Verbindung fehlgeschlagen: {type(exc).__name__}: {exc}"


# -- uploads & remote retrieval -------------------------------------------

def register_uploaded_file(temp_path: Path, original_name: str) -> Path:
    """Move a verified upload into the backup directory under a safe name (§3/§24)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_suffix = ".zip"
    final = BACKUP_DIR / f"upload_{timestamp}{safe_suffix}"
    shutil.move(str(temp_path), str(final))
    return final


def fetch_remote_to_temp(job, filename: str) -> Path:
    """Download a named backup file from a job's FTP/SMB target to a temp file."""
    fd, tmp_name = tempfile.mkstemp(prefix="fetch_", suffix=".zip", dir=str(BACKUP_DIR))
    os.close(fd)
    tmp_path = Path(tmp_name)
    if job.target_type == "ftp":
        import ftplib

        cls = ftplib.FTP_TLS if job.ftp_use_tls else ftplib.FTP
        ftp = cls()
        ftp.connect(job.ftp_host, job.ftp_port or 21, timeout=30)
        ftp.login(job.ftp_username, job.ftp_password)
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        try:
            if job.ftp_path and job.ftp_path != "/":
                ftp.cwd(job.ftp_path)
            with tmp_path.open("wb") as handle:
                ftp.retrbinary(f"RETR {filename}", handle.write)
        finally:
            ftp.quit()
    elif job.target_type == "smb":
        smbclient, server = _smb_register(job)
        try:
            _srv, share, sub = _parse_unc(job.smb_path)
            remote_dir = f"\\\\{server}\\{share}" + (("\\" + sub) if sub else "")
            with smbclient.open_file(f"{remote_dir}\\{filename}", mode="rb") as src, tmp_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        finally:
            try:
                smbclient.delete_session(server)
            except Exception:  # pragma: no cover
                pass
    else:
        tmp_path.unlink(missing_ok=True)
        raise ValueError("Remote-Abruf nur für FTP/SMB")
    return tmp_path
