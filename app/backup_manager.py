"""Backup creation, integrity checks, retention, history and remote targets.

Targets (§25):
* local – store the archive in the data volume (``data/backups``)
* ftp   – upload via FTP/FTPS (stdlib ``ftplib``)
* smb   – upload via SMB3 (``smbprotocol``)

Backup configuration (incl. credentials) is persisted in the config volume via
:class:`app.app_config.BackupConfig`. Passwords are never written to any log.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from . import app_config, database, paths

LOGGER = logging.getLogger("erfassung.application")

BACKUP_DIR = paths.DATA_DIR / "backups"
_HISTORY_PATH = BACKUP_DIR / "history.json"
_MAX_HISTORY = 200


# -- helpers ---------------------------------------------------------------

def _database_path() -> Optional[Path]:
    url = database.SQLALCHEMY_DATABASE_URL
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        db_path = Path(raw)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        return db_path
    return None


def _read_history() -> list[dict]:
    if not _HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _append_history(entry: dict) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    history = _read_history()
    history.insert(0, entry)
    history = history[:_MAX_HISTORY]
    try:
        _HISTORY_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except OSError as exc:  # pragma: no cover
        LOGGER.warning("Backup-Historie konnte nicht geschrieben werden: %s", exc)


def history() -> list[dict]:
    return _read_history()


# -- archive creation ------------------------------------------------------

def _build_archive(include_logs: bool) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    # Microseconds keep the filename unique even for rapid successive backups.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archive_path = BACKUP_DIR / f"backup_{timestamp}.zip"
    db_path = _database_path()
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if db_path and db_path.exists():
            archive.write(db_path, arcname=f"data/{db_path.name}")
        if paths.CONFIG_DIR.exists():
            for entry in paths.CONFIG_DIR.rglob("*"):
                if entry.is_file():
                    archive.write(entry, arcname=f"config/{entry.relative_to(paths.CONFIG_DIR)}")
        if include_logs and paths.LOGS_DIR.exists():
            for entry in paths.LOGS_DIR.rglob("*"):
                if entry.is_file():
                    archive.write(entry, arcname=f"logs/{entry.relative_to(paths.LOGS_DIR)}")
    return archive_path


def verify_integrity(archive_path: Path) -> tuple[bool, str]:
    """§26: ensure the file exists, has a plausible size and is a readable ZIP."""
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


# -- retention -------------------------------------------------------------

def apply_retention(config: app_config.BackupConfig) -> int:
    """Remove local archives exceeding the configured count/age. Returns removed."""
    archives = sorted(BACKUP_DIR.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    to_remove: set[Path] = set()
    if config.retention_count > 0 and len(archives) > config.retention_count:
        to_remove.update(archives[config.retention_count:])
    if config.retention_days > 0:
        cutoff = datetime.now().timestamp() - config.retention_days * 24 * 3600
        for archive in archives:
            if archive.stat().st_mtime < cutoff:
                to_remove.add(archive)
    removed = 0
    for archive in to_remove:
        try:
            archive.unlink()
            removed += 1
        except OSError:  # pragma: no cover
            continue
    return removed


# -- remote transfer -------------------------------------------------------

def _upload_ftp(config: app_config.BackupConfig, archive_path: Path) -> None:
    import ftplib

    cls = ftplib.FTP_TLS if config.ftp_use_tls else ftplib.FTP
    ftp = cls()
    ftp.connect(config.ftp_host, config.ftp_port, timeout=30)
    ftp.login(config.ftp_username, config.ftp_password)
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    try:
        if config.ftp_remote_dir and config.ftp_remote_dir != "/":
            try:
                ftp.cwd(config.ftp_remote_dir)
            except ftplib.error_perm:
                ftp.mkd(config.ftp_remote_dir)
                ftp.cwd(config.ftp_remote_dir)
        with archive_path.open("rb") as handle:
            ftp.storbinary(f"STOR {archive_path.name}", handle)
    finally:
        ftp.quit()


def _smb_url_parts(config: app_config.BackupConfig) -> tuple[str, str]:
    """Return (server, share) handling Windows-style ``\\\\server\\share`` paths."""
    server = config.smb_server.strip().lstrip("\\/").replace("\\", "/")
    share = config.smb_share.strip().strip("\\/").replace("\\", "/")
    if not share and "/" in server:
        server, _, share = server.partition("/")
    return server, share


def _upload_smb(config: app_config.BackupConfig, archive_path: Path) -> None:
    import smbclient

    server, share = _smb_url_parts(config)
    username = config.smb_username
    if config.smb_domain and "\\" not in username and "@" not in username:
        username = f"{config.smb_domain}\\{username}"
    smbclient.register_session(
        server, username=username, password=config.smb_password
    )
    try:
        sub_path = config.smb_path.strip("\\/").replace("\\", "/")
        remote_dir = f"\\\\{server}\\{share}"
        if sub_path:
            remote_dir = remote_dir + "\\" + sub_path.replace("/", "\\")
        remote_file = f"{remote_dir}\\{archive_path.name}"
        try:
            smbclient.makedirs(remote_dir, exist_ok=True)
        except Exception:  # pragma: no cover - dir may already exist
            pass
        with archive_path.open("rb") as src, smbclient.open_file(remote_file, mode="wb") as dst:
            dst.write(src.read())
    finally:
        try:
            smbclient.delete_session(server)
        except Exception:  # pragma: no cover
            pass


def _transfer(config: app_config.BackupConfig, archive_path: Path) -> str:
    if config.target == "ftp":
        _upload_ftp(config, archive_path)
        return f"ftp://{config.ftp_host}{config.ftp_remote_dir}"
    if config.target == "smb":
        _upload_smb(config, archive_path)
        return f"\\\\{config.smb_server}\\{config.smb_share}"
    return str(archive_path)


# -- public API ------------------------------------------------------------

def create_backup(config: Optional[app_config.BackupConfig] = None) -> dict:
    """Create a backup, verify it, transfer it and record the history entry."""
    if config is None:
        config = app_config.load_backup_config()

    entry: dict = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "target": config.target,
        "result": "error",
        "message": "",
        "size_bytes": 0,
    }
    try:
        archive_path = _build_archive(config.include_logs)
        ok, message = verify_integrity(archive_path)
        size = archive_path.stat().st_size if archive_path.exists() else 0
        entry["name"] = archive_path.name
        entry["size_bytes"] = size
        entry["size_human"] = paths.format_size(size)
        if not ok:
            entry["message"] = f"Integritätsprüfung fehlgeschlagen: {message}"
            LOGGER.error("Backup-Integritätsprüfung fehlgeschlagen: %s", message)
            _append_history(entry)
            return entry
        location = _transfer(config, archive_path)
        entry["location"] = location
        entry["result"] = "success"
        entry["message"] = message
        removed = apply_retention(config)
        if removed:
            entry["message"] += f" · {removed} alte Sicherung(en) entfernt"
        LOGGER.info("Backup erstellt (%s) -> %s", config.target, location)
    except Exception as exc:  # pragma: no cover - depends on remote target
        # Never log credentials – only the exception text.
        entry["message"] = f"{type(exc).__name__}: {exc}"
        LOGGER.error("Backup fehlgeschlagen (%s): %s", config.target, exc)
    _append_history(entry)
    return entry


def test_connection(config: app_config.BackupConfig) -> tuple[bool, str]:
    """Verify connectivity to the configured remote target without uploading."""
    try:
        if config.target == "ftp":
            import ftplib

            cls = ftplib.FTP_TLS if config.ftp_use_tls else ftplib.FTP
            ftp = cls()
            ftp.connect(config.ftp_host, config.ftp_port, timeout=15)
            ftp.login(config.ftp_username, config.ftp_password)
            if isinstance(ftp, ftplib.FTP_TLS):
                ftp.prot_p()
            ftp.voidcmd("NOOP")
            ftp.quit()
            return True, "FTP-Verbindung erfolgreich"
        if config.target == "smb":
            import smbclient

            server, share = _smb_url_parts(config)
            username = config.smb_username
            if config.smb_domain and "\\" not in username and "@" not in username:
                username = f"{config.smb_domain}\\{username}"
            smbclient.register_session(server, username=username, password=config.smb_password)
            smbclient.listdir(f"\\\\{server}\\{share}")
            smbclient.delete_session(server)
            return True, "SMB3-Verbindung erfolgreich"
        return True, "Lokales Ziel ist immer verfügbar"
    except ModuleNotFoundError as exc:
        return False, f"Erforderliche Bibliothek fehlt: {exc.name}"
    except Exception as exc:  # pragma: no cover - depends on remote target
        return False, f"Verbindung fehlgeschlagen: {type(exc).__name__}: {exc}"


def list_backups() -> list[dict]:
    backups: list[dict] = []
    if BACKUP_DIR.exists():
        for path in sorted(BACKUP_DIR.glob("backup_*.zip"), reverse=True):
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


def backup_summary() -> dict:
    backups = list_backups()
    latest = backups[0] if backups else None
    return {
        "count": len(backups),
        "location": str(BACKUP_DIR),
        "latest": latest,
        "backups": backups,
        "history": history(),
    }
