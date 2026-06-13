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

from . import crud, database, paths

LOGGER = logging.getLogger("erfassung.application")

BACKUP_DIR = paths.DATA_DIR / "backups"


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


# -- archive ---------------------------------------------------------------

def _build_archive(job, staging: Path) -> tuple[Path, list[str]]:
    """Build the ZIP for ``job`` in ``staging``. Returns (path, warnings)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archive_path = BACKUP_DIR / f"backup_job{job.id}_{timestamp}.zip"
    contents = job.content_list
    warnings: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
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
    for archive in remove:
        try:
            archive.unlink()
            removed += 1
        except OSError:  # pragma: no cover
            continue
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

def run_job(db: Session, job, *, triggered_by: str = "manual") -> "object":
    """Execute ``job``: build, verify, transfer, prune, record history."""
    started = datetime.now()
    status = "error"
    message = ""
    size = 0
    local_file: Optional[str] = None
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


def test_connection(job) -> tuple[bool, str]:
    """Verify the job's target is reachable without creating a backup."""
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
