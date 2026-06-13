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

from . import paths

LOGGER = logging.getLogger(__name__)

VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_LOGGING_PATH = paths.CONFIG_DIR / "logging.json"
_SYSTEM_PATH = paths.CONFIG_DIR / "system.json"


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
    "VALID_LEVELS",
    "load_logging_config",
    "save_logging_config",
    "load_system_settings",
    "save_system_settings",
    "export_all",
    "import_all",
    "validate_import",
]


# Silence "imported but unused" for dataclass helpers kept for completeness.
_ = (field, fields)
