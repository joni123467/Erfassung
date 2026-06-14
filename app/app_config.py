"""Persistent application configuration stored in the ``config`` volume.

All configuration that must survive container restarts lives here as JSON
files inside :data:`app.paths.CONFIG_DIR`:

* ``logging.json`` – log level, rotation and per-channel logging toggles
* ``system.json``  – global system / synchronisation settings

The stores are intentionally dependency free (plain dataclasses + JSON) so
they can be imported very early during application start-up, before logging
is configured.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import database, paths

LOGGER = logging.getLogger(__name__)

VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_LOGGING_PATH = paths.CONFIG_DIR / "logging.json"
_SYSTEM_PATH = paths.CONFIG_DIR / "system.json"
_BACKUP_PATH = paths.CONFIG_DIR / "backup.json"
_DATABASE_PATH = paths.CONFIG_DIR / "database.json"


def _ensure_config_dir() -> None:
    try:
        paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - depends on environment
        LOGGER.warning("Konfigurationsordner konnte nicht erstellt werden: %s", exc)


def _coerce_level(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.upper() in VALID_LEVELS:
        return value.upper()
    return fallback


def _coerce_int(value: Any, fallback: int, minimum: int = 0) -> int:
    try:
        return max(int(value), minimum)
    except (TypeError, ValueError):
        return fallback


def _coerce_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return fallback
    return bool(value)


@dataclass
class LoggingConfig:
    """Logging behaviour persisted across restarts."""

    level: str = "INFO"
    api_logging: bool = True
    security_logging: bool = True
    audit_logging: bool = True
    sync_logging: bool = True
    backup_logging: bool = True
    restore_logging: bool = True
    database_logging: bool = True
    terminal_logging: bool = True
    rotation_max_bytes: int = 5 * 1024 * 1024
    rotation_backup_count: int = 5
    auto_cleanup_enabled: bool = False
    auto_cleanup_days: int = 90

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LoggingConfig":
        config = cls()
        if not isinstance(payload, dict):
            return config
        config.level = _coerce_level(payload.get("level"), config.level)
        config.api_logging = _coerce_bool(payload.get("api_logging"), config.api_logging)
        config.security_logging = _coerce_bool(
            payload.get("security_logging"), config.security_logging
        )
        config.audit_logging = _coerce_bool(payload.get("audit_logging"), config.audit_logging)
        config.sync_logging = _coerce_bool(payload.get("sync_logging"), config.sync_logging)
        config.backup_logging = _coerce_bool(payload.get("backup_logging"), config.backup_logging)
        config.restore_logging = _coerce_bool(payload.get("restore_logging"), config.restore_logging)
        config.database_logging = _coerce_bool(
            payload.get("database_logging"), config.database_logging
        )
        config.terminal_logging = _coerce_bool(
            payload.get("terminal_logging"), config.terminal_logging
        )
        config.rotation_max_bytes = _coerce_int(
            payload.get("rotation_max_bytes"), config.rotation_max_bytes, minimum=1024
        )
        config.rotation_backup_count = _coerce_int(
            payload.get("rotation_backup_count"), config.rotation_backup_count, minimum=0
        )
        config.auto_cleanup_enabled = _coerce_bool(
            payload.get("auto_cleanup_enabled"), config.auto_cleanup_enabled
        )
        config.auto_cleanup_days = _coerce_int(
            payload.get("auto_cleanup_days"), config.auto_cleanup_days, minimum=1
        )
        return config


@dataclass
class SystemSettings:
    """Global system / synchronisation settings."""

    sync_enabled: bool = True
    sync_interval_minutes: int = 60
    sync_full_on_start: bool = False
    auto_holiday_management: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SystemSettings":
        config = cls()
        if not isinstance(payload, dict):
            return config
        config.sync_enabled = _coerce_bool(payload.get("sync_enabled"), config.sync_enabled)
        config.sync_interval_minutes = _coerce_int(
            payload.get("sync_interval_minutes"), config.sync_interval_minutes, minimum=1
        )
        config.sync_full_on_start = _coerce_bool(
            payload.get("sync_full_on_start"), config.sync_full_on_start
        )
        config.auto_holiday_management = _coerce_bool(
            payload.get("auto_holiday_management"), config.auto_holiday_management
        )
        return config


BACKUP_TARGETS = ("local", "ftp", "smb")


@dataclass
class BackupConfig:
    """Backup destinations and retention. Stored in the config volume.

    Passwords are persisted (so unattended backups work) but must never be
    written to any log file.
    """

    target: str = "local"
    include_logs: bool = False
    retention_count: int = 10
    retention_days: int = 30

    # FTP
    ftp_host: str = ""
    ftp_port: int = 21
    ftp_username: str = ""
    ftp_password: str = ""
    ftp_remote_dir: str = "/"
    ftp_use_tls: bool = True

    # SMB (SMB3)
    smb_server: str = ""
    smb_share: str = ""
    smb_path: str = ""
    smb_username: str = ""
    smb_password: str = ""
    smb_domain: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def safe_dict(self) -> dict[str, Any]:
        """Like :meth:`to_dict` but with passwords masked (for logging/UI echo)."""
        data = self.to_dict()
        for key in ("ftp_password", "smb_password"):
            if data.get(key):
                data[key] = "***"
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BackupConfig":
        config = cls()
        if not isinstance(payload, dict):
            return config
        target = payload.get("target")
        if isinstance(target, str) and target in BACKUP_TARGETS:
            config.target = target
        config.include_logs = _coerce_bool(payload.get("include_logs"), config.include_logs)
        config.retention_count = _coerce_int(
            payload.get("retention_count"), config.retention_count, minimum=0
        )
        config.retention_days = _coerce_int(
            payload.get("retention_days"), config.retention_days, minimum=0
        )
        config.ftp_host = str(payload.get("ftp_host") or "").strip()
        config.ftp_port = _coerce_int(payload.get("ftp_port"), config.ftp_port, minimum=1)
        config.ftp_username = str(payload.get("ftp_username") or "").strip()
        # Keep the stored password when the form submits an empty/masked value.
        ftp_pw = payload.get("ftp_password")
        if ftp_pw not in (None, "", "***"):
            config.ftp_password = str(ftp_pw)
        config.ftp_remote_dir = str(payload.get("ftp_remote_dir") or "/").strip() or "/"
        config.ftp_use_tls = _coerce_bool(payload.get("ftp_use_tls"), config.ftp_use_tls)
        config.smb_server = str(payload.get("smb_server") or "").strip()
        config.smb_share = str(payload.get("smb_share") or "").strip()
        config.smb_path = str(payload.get("smb_path") or "").strip()
        config.smb_username = str(payload.get("smb_username") or "").strip()
        smb_pw = payload.get("smb_password")
        if smb_pw not in (None, "", "***"):
            config.smb_password = str(smb_pw)
        config.smb_domain = str(payload.get("smb_domain") or "").strip()
        return config


DATABASE_TYPES = ("sqlite", "mysql", "mariadb", "postgresql")

# Backends recommended for productive multi-user deployments (§0.9.7).
RECOMMENDED_DATABASE_TYPES = ("mariadb", "postgresql")

# Default port per logical database type.
DATABASE_DEFAULT_PORTS = {"mysql": 3306, "mariadb": 3306, "postgresql": 5432}


@dataclass
class DatabaseConfig:
    """Active database backend configuration (persisted in the config volume).

    The same dataclass describes SQLite (only ``sqlite_path`` is relevant) and
    the server backends MySQL/MariaDB/PostgreSQL (host/port/name/user/password
    + optional SSL and connection timeout). The password is stored so the
    connection can be re-established unattended, but is never written to a log.
    """

    type: str = "sqlite"
    sqlite_path: str = "./erfassung.db"
    host: str = ""
    port: int = 0
    name: str = ""
    user: str = ""
    password: str = ""
    ssl: bool = False
    timeout: int = 30

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def safe_dict(self) -> dict[str, Any]:
        """Like :meth:`to_dict` but with the password masked (UI/logging)."""
        data = self.to_dict()
        if data.get("password"):
            data["password"] = "***"
        data["has_password"] = bool(self.password)
        return data

    def connection_config(self) -> dict[str, Any]:
        """Mapping consumed by :func:`app.database.build_url` / ``reconfigure``."""
        return {
            "type": self.type,
            "sqlite_path": self.sqlite_path,
            "host": self.host,
            "port": self.port,
            "name": self.name,
            "user": self.user,
            "password": self.password,
            "ssl": self.ssl,
            "timeout": self.timeout,
        }

    def to_url(self) -> str:
        return database.build_url(self.connection_config())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DatabaseConfig":
        config = cls()
        if not isinstance(payload, dict):
            return config
        db_type = str(payload.get("type") or "").strip().lower()
        if db_type in DATABASE_TYPES:
            config.type = db_type
        config.sqlite_path = str(payload.get("sqlite_path") or config.sqlite_path).strip() or config.sqlite_path
        config.host = str(payload.get("host") or "").strip()
        default_port = DATABASE_DEFAULT_PORTS.get(config.type, 0)
        config.port = _coerce_int(payload.get("port"), default_port, minimum=0)
        config.name = str(payload.get("name") or "").strip()
        config.user = str(payload.get("user") or "").strip()
        pw = payload.get("password")
        # Keep the stored password when the form submits an empty/masked value.
        if pw not in (None, "", "***"):
            config.password = str(pw)
        config.ssl = _coerce_bool(payload.get("ssl"), config.ssl)
        config.timeout = _coerce_int(payload.get("timeout"), config.timeout, minimum=1)
        return config

    def describe(self) -> str:
        """Short human-readable description (no credentials)."""
        if self.type == "sqlite":
            return f"SQLite ({self.sqlite_path})"
        label = {"mysql": "MySQL", "mariadb": "MariaDB", "postgresql": "PostgreSQL"}.get(
            self.type, self.type
        )
        return f"{label} {self.host}:{self.port or DATABASE_DEFAULT_PORTS.get(self.type, '')}/{self.name}"


def load_database_config() -> "DatabaseConfig":
    stored = _read_json(_DATABASE_PATH)
    config = DatabaseConfig.from_dict(stored)
    if isinstance(stored, dict) and stored.get("password"):
        config.password = str(stored["password"])
    if not stored:
        # No persisted selection yet: mirror the live backend so the UI shows
        # the database the process actually started with (env/SQLite default).
        backend = database.DB_TYPE
        config.type = backend if backend in DATABASE_TYPES else "sqlite"
        if config.type == "sqlite":
            raw = database.SQLALCHEMY_DATABASE_URL
            if raw.startswith("sqlite:///"):
                config.sqlite_path = raw.replace("sqlite:///", "", 1)
    return config


def save_database_config(config: "DatabaseConfig") -> None:
    _write_json(_DATABASE_PATH, config.to_dict())


def validate_database_config(config: "DatabaseConfig") -> tuple[bool, str]:
    """Validate a database configuration before testing/migrating."""
    if config.type not in DATABASE_TYPES:
        return False, f"Unbekannter Datenbanktyp: {config.type!r}."
    if config.type == "sqlite":
        if not config.sqlite_path.strip():
            return False, "Datenbankpfad darf nicht leer sein."
        return True, "Konfiguration gültig."
    if not config.host:
        return False, "Host darf nicht leer sein."
    if not config.name:
        return False, "Datenbankname darf nicht leer sein."
    if not config.user:
        return False, "Benutzer darf nicht leer sein."
    return True, "Konfiguration gültig."


def load_backup_config() -> "BackupConfig":
    stored = _read_json(_BACKUP_PATH)
    config = BackupConfig.from_dict(stored)
    # from_dict skips empty passwords (to support masked form re-submits); when
    # loading from disk we must keep the real stored passwords verbatim.
    if isinstance(stored, dict):
        if stored.get("ftp_password"):
            config.ftp_password = str(stored["ftp_password"])
        if stored.get("smb_password"):
            config.smb_password = str(stored["smb_password"])
    return config


def save_backup_config(config: "BackupConfig") -> None:
    _write_json(_BACKUP_PATH, config.to_dict())


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Konfigurationsdatei %s ist ungültig: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_config_dir()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_logging_config() -> LoggingConfig:
    return LoggingConfig.from_dict(_read_json(_LOGGING_PATH))


def save_logging_config(config: LoggingConfig) -> None:
    _write_json(_LOGGING_PATH, config.to_dict())


def load_system_settings() -> SystemSettings:
    return SystemSettings.from_dict(_read_json(_SYSTEM_PATH))


def save_system_settings(settings: SystemSettings) -> None:
    _write_json(_SYSTEM_PATH, settings.to_dict())


def export_all() -> dict[str, Any]:
    """Return a JSON-serialisable snapshot of all persisted settings."""

    return {
        "version": 1,
        "logging": load_logging_config().to_dict(),
        "system": load_system_settings().to_dict(),
    }


def validate_import(payload: Any) -> tuple[bool, str]:
    """Validate an import payload before applying it."""

    if not isinstance(payload, dict):
        return False, "Ungültiges Format: Objekt erwartet."
    logging_section = payload.get("logging")
    system_section = payload.get("system")
    if logging_section is None and system_section is None:
        return False, "Keine bekannten Einstellungen (logging/system) enthalten."
    if logging_section is not None and not isinstance(logging_section, dict):
        return False, "Abschnitt 'logging' muss ein Objekt sein."
    if system_section is not None and not isinstance(system_section, dict):
        return False, "Abschnitt 'system' muss ein Objekt sein."
    level = (logging_section or {}).get("level")
    if level is not None and (not isinstance(level, str) or level.upper() not in VALID_LEVELS):
        return False, f"Ungültiges Log-Level: {level!r}."
    return True, "Einstellungen sind gültig."


def import_all(payload: dict[str, Any]) -> None:
    """Persist a previously validated settings payload."""

    if "logging" in payload and isinstance(payload["logging"], dict):
        save_logging_config(LoggingConfig.from_dict(payload["logging"]))
    if "system" in payload and isinstance(payload["system"], dict):
        save_system_settings(SystemSettings.from_dict(payload["system"]))


__all__ = [
    "LoggingConfig",
    "SystemSettings",
    "BackupConfig",
    "DatabaseConfig",
    "BACKUP_TARGETS",
    "DATABASE_TYPES",
    "RECOMMENDED_DATABASE_TYPES",
    "DATABASE_DEFAULT_PORTS",
    "VALID_LEVELS",
    "load_logging_config",
    "save_logging_config",
    "load_system_settings",
    "save_system_settings",
    "load_backup_config",
    "save_backup_config",
    "load_database_config",
    "save_database_config",
    "validate_database_config",
    "export_all",
    "import_all",
    "validate_import",
]


# Silence "imported but unused" for dataclass helpers kept for completeness.
_ = (field, fields)
