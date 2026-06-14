"""Asynchronous restore worker + status tracking (§0.9.5).

A restore must never run inside the HTTP request: it swaps the database file and
disposes the engine, which would tear down the very connection the request is
using (the cause of the previous "Internal Server Error"). Instead the request
only validates and *queues* a job; a background daemon thread performs the
restore and reports progress through a JSON status file.

The status file lives in the ``data`` volume but is *not* part of the database,
so it survives the DB swap and even a full application/container restart – the
frontend can therefore always read the final result, reconnect after a restart
and redirect the user.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import database, paths, restore_manager

STATUS_FILE = paths.DATA_DIR / "restore_status.json"

# States surfaced via /api/restore/status
ACTIVE_STATES = {"queued", "running", "creating_backup", "restoring", "restarting", "running_migrations"}
TERMINAL_STATES = {"completed", "failed"}

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def _write(payload: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(STATUS_FILE)


def read_status() -> dict:
    if not STATUS_FILE.exists():
        return {"state": "idle"}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "idle"}


def is_active() -> bool:
    return read_status().get("state") in ACTIVE_STATES


def active_job() -> Optional[dict]:
    status = read_status()
    return status if status.get("state") in ACTIVE_STATES else None


def _update(token: str, base: dict, state: str, percent: int, message: str, **extra) -> None:
    payload = dict(base)
    payload.update(
        {
            "token": token,
            "state": state,
            "percent": percent,
            "message": message,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    payload.update(extra)
    _write(payload)


def _worker(archive_path: Path, username: str, token: str, base: dict) -> None:
    def progress(state: str, percent: int, message: str) -> None:
        _update(token, base, state, percent, message)

    result = restore_manager.perform_restore(
        archive_path, username=username, token=token, progress=progress
    )
    final_state = "completed" if result["status"] in {"success", "warning"} else "failed"
    redirect = "/login"  # DB (and sessions) replaced -> user must re-authenticate
    _update(
        token,
        base,
        final_state,
        100,
        result["message"],
        finished_at=datetime.now().isoformat(timespec="seconds"),
        result_status=result["status"],
        safety_backup=result.get("safety_backup"),
        migrations_applied=result.get("migrations_applied"),
        log_token=token,
        redirect=redirect,
    )


def start_restore(archive_path: Path, *, username: str) -> str:
    """Queue a restore job and start the background worker. Returns the token."""
    global _thread
    with _lock:
        if is_active():
            raise RuntimeError("Es läuft bereits eine Wiederherstellung.")
        token = datetime.now().strftime("%Y%m%d%H%M%S")
        from . import backup_manager

        meta = backup_manager.read_metadata(Path(archive_path)) or {}
        base = {
            "file": Path(archive_path).name,
            "username": username,
            "backup_version": meta.get("app_version") or "unbekannt",
            "database_type": meta.get("database_type") or database.DB_BACKEND,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "redirect": None,
            "result_status": None,
        }
        _update(token, base, "queued", 5, "Wiederherstellung wurde gestartet")
        _thread = threading.Thread(
            target=_worker,
            args=(Path(archive_path), username, token, base),
            name="restore-worker",
            daemon=True,
        )
        _thread.start()
        return token


def clear_status() -> None:
    try:
        STATUS_FILE.unlink(missing_ok=True)
    except OSError:  # pragma: no cover
        pass
