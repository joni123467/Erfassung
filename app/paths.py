"""Central resolution of the persistent volume directories.

Erfassung uses three persistent volumes that map to dedicated purposes:

* ``config`` – only configuration (system settings, logging, UI, mail, sync, PWA)
* ``data``   – only business data (database, users, vacation, holidays, …)
* ``logs``   – only log files

Paths can be overridden via environment variables so that operators can mount
the volumes anywhere they like.  By default they live next to the application
package (``/app/config``, ``/app/data``, ``/app/logs`` inside the container).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from . import database


def _discover_project_root() -> Path:
    """Return the folder that contains the application package."""

    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "requirements.txt").exists():
            return candidate
    for candidate in current.parents:
        if (candidate / "app").is_dir():
            return candidate
    return current.parent.parent


PROJECT_ROOT = _discover_project_root()


def _data_dir_default() -> Path:
    """Derive the data directory from the configured SQLite database path."""

    url = database.SQLALCHEMY_DATABASE_URL
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        db_path = Path(raw)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        return db_path.parent
    return PROJECT_ROOT / "data"


def _resolve(env_var: str, default: Path) -> Path:
    value = os.environ.get(env_var)
    if value:
        return Path(value).expanduser()
    return default


CONFIG_DIR = _resolve("ERFASSUNG_CONFIG_DIR", PROJECT_ROOT / "config")
DATA_DIR = _resolve("ERFASSUNG_DATA_DIR", _data_dir_default())
LOGS_DIR = _resolve("ERFASSUNG_LOGS_DIR", PROJECT_ROOT / "logs")


def all_directories() -> dict[str, Path]:
    return {"config": CONFIG_DIR, "data": DATA_DIR, "logs": LOGS_DIR}


def ensure_directories() -> dict[str, dict[str, object]]:
    """Create the persistent directories if they are missing.

    Returns a status mapping describing, per volume, whether it already
    existed, whether it could be created and whether it is writable.
    """

    report: dict[str, dict[str, object]] = {}
    for name, path in all_directories().items():
        existed = path.exists()
        created = False
        error: str | None = None
        if not existed:
            try:
                path.mkdir(parents=True, exist_ok=True)
                created = True
            except OSError as exc:  # pragma: no cover - depends on environment
                error = str(exc)
        report[name] = {
            "path": str(path),
            "existed": existed,
            "created": created,
            "writable": _is_writable(path),
            "error": error,
        }
    return report


def _is_writable(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK)


def directory_stats(path: Path) -> dict[str, object]:
    """Return size, file count and last-modified timestamp for a directory."""

    total_size = 0
    file_count = 0
    last_modified: datetime | None = None
    if path.exists():
        for entry in path.rglob("*"):
            try:
                if entry.is_file():
                    stat = entry.stat()
                    total_size += stat.st_size
                    file_count += 1
                    modified = datetime.fromtimestamp(stat.st_mtime)
                    if last_modified is None or modified > last_modified:
                        last_modified = modified
            except OSError:  # pragma: no cover - races / permission issues
                continue
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": total_size,
        "file_count": file_count,
        "last_modified": last_modified,
        "writable": _is_writable(path),
    }


def free_space_bytes(path: Path | None = None) -> int:
    """Return the free space (in bytes) of the filesystem holding ``path``."""

    target = path or DATA_DIR
    probe = target if target.exists() else PROJECT_ROOT
    try:
        usage = os.statvfs(probe)
        return usage.f_bavail * usage.f_frsize
    except (OSError, AttributeError):  # pragma: no cover - non-POSIX fallback
        return 0


def format_size(num_bytes: float | int | None) -> str:
    """Human readable byte size."""

    if not num_bytes:
        return "0 B"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
