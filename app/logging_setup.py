"""Professional, file based logging system for Erfassung.

Six dedicated, rotating log files live in :data:`app.paths.LOGS_DIR`:

==================  =========================================================
``application.log``  general application events
``api.log``          API calls
``sync.log``         offline / TimeMoto synchronisation
``security.log``     logins, logouts, permission related events
``error.log``        errors and exceptions (aggregated from all channels)
``audit.log``        administrative actions
==================  =========================================================

Every record is structured (timestamp, level, channel, optional user, message)
and rotated by size.  Behaviour is driven by :class:`app.app_config.LoggingConfig`
which is persisted in the ``config`` volume, so changes survive restarts.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from . import paths
from .app_config import LoggingConfig

# Channel name -> file name
CHANNELS: dict[str, str] = {
    "application": "application.log",
    "api": "api.log",
    "sync": "sync.log",
    "security": "security.log",
    "error": "error.log",
    "audit": "audit.log",
    "backup": "backup.log",
    "database": "database.log",
}

LOG_FILES = tuple(CHANNELS.values())

_LOGGER_PREFIX = "erfassung"

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(channel)-11s | user=%(user)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Track handlers we created so reconfiguration can replace them cleanly.
_MANAGED_HANDLERS: list[logging.Handler] = []
_ERROR_HANDLER: Optional[logging.Handler] = None
_CONFIGURED = False


class _ContextFilter(logging.Filter):
    """Ensure ``channel`` and ``user`` fields are always present."""

    def __init__(self, channel: str) -> None:
        super().__init__()
        self.channel = channel

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "channel"):
            record.channel = self.channel
        if not hasattr(record, "user"):
            record.user = "-"
        return True


def _channel_logger_name(channel: str) -> str:
    return f"{_LOGGER_PREFIX}.{channel}"


def channel_path(channel: str) -> Path:
    return paths.LOGS_DIR / CHANNELS[channel]


def _build_handler(path: Path, config: LoggingConfig, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=config.rotation_max_bytes,
        backupCount=config.rotation_backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    handler.setLevel(level)
    return handler


def _clear_managed_handlers() -> None:
    global _ERROR_HANDLER
    for handler in _MANAGED_HANDLERS:
        for logger in (logging.getLogger(), *(
            logging.getLogger(_channel_logger_name(name)) for name in CHANNELS
        )):
            if handler in logger.handlers:
                logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # pragma: no cover - defensive
            pass
    _MANAGED_HANDLERS.clear()
    _ERROR_HANDLER = None


def configure_logging(config: LoggingConfig | None = None) -> LoggingConfig:
    """(Re)configure all logging handlers from ``config``.

    Idempotent: existing managed handlers are removed before new ones are
    attached, so this can be called again whenever settings change.
    """

    global _CONFIGURED, _ERROR_HANDLER

    if config is None:
        from .app_config import load_logging_config

        config = load_logging_config()

    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, config.level, logging.INFO)

    _clear_managed_handlers()

    # error.log aggregates ERROR+ records from every channel via the root logger.
    error_handler = _build_handler(channel_path("error"), config, logging.ERROR)
    error_handler.addFilter(_ContextFilter("application"))
    _ERROR_HANDLER = error_handler

    root = logging.getLogger()
    root.setLevel(min(level, logging.ERROR))
    root.addHandler(error_handler)
    _MANAGED_HANDLERS.append(error_handler)

    # Per-channel toggles. Disabled channels still get a logger, but no file
    # handler, so their output is suppressed.
    channel_enabled = {
        "application": True,
        "api": config.api_logging,
        "sync": config.sync_logging,
        "security": config.security_logging,
        "audit": config.audit_logging,
        "backup": getattr(config, "backup_logging", True) or getattr(config, "restore_logging", True),
        "database": getattr(config, "database_logging", True),
    }

    for channel, enabled in channel_enabled.items():
        logger = logging.getLogger(_channel_logger_name(channel))
        logger.setLevel(level)
        logger.propagate = True  # let ERROR records bubble up to error.log
        if not enabled:
            continue
        handler = _build_handler(channel_path(channel), config, level)
        handler.addFilter(_ContextFilter(channel))
        logger.addHandler(handler)
        _MANAGED_HANDLERS.append(handler)

    _CONFIGURED = True
    return config


def is_configured() -> bool:
    return _CONFIGURED


def _log(channel: str, level: int, message: str, *, user: object = None, **kwargs) -> None:
    logger = logging.getLogger(_channel_logger_name(channel))
    extra = {"channel": channel, "user": _format_user(user)}
    logger.log(level, message, extra=extra, **kwargs)


def _format_user(user: object) -> str:
    if user is None:
        return "-"
    if isinstance(user, str):
        return user or "-"
    username = getattr(user, "username", None)
    if username:
        return str(username)
    user_id = getattr(user, "id", None)
    if user_id is not None:
        return f"id={user_id}"
    return str(user)


# -- Public helpers ---------------------------------------------------------

def log_application(message: str, *, level: int = logging.INFO, user: object = None) -> None:
    _log("application", level, message, user=user)


def log_api(message: str, *, level: int = logging.INFO, user: object = None) -> None:
    _log("api", level, message, user=user)


def log_sync(message: str, *, level: int = logging.INFO, user: object = None) -> None:
    _log("sync", level, message, user=user)


def log_security(message: str, *, level: int = logging.INFO, user: object = None) -> None:
    _log("security", level, message, user=user)


def log_audit(action: str, *, user: object = None, detail: str = "") -> None:
    message = f"{action}" + (f" – {detail}" if detail else "")
    _log("audit", logging.INFO, message, user=user)


def log_error(message: str, *, user: object = None, exc_info: bool = True) -> None:
    _log("error", logging.ERROR, message, user=user, exc_info=exc_info)


def log_backup(message: str, *, level: int = logging.INFO, user: object = None) -> None:
    """Backup/restore audit trail in the dedicated backup.log channel (§11)."""
    _log("backup", level, message, user=user)


def log_database(message: str, *, level: int = logging.INFO, user: object = None) -> None:
    """Database management / migration audit trail (database.log, §0.9.7)."""
    _log("database", level, message, user=user)


__all__ = [
    "CHANNELS",
    "LOG_FILES",
    "configure_logging",
    "is_configured",
    "channel_path",
    "log_application",
    "log_api",
    "log_sync",
    "log_security",
    "log_audit",
    "log_error",
    "log_backup",
    "log_database",
]
