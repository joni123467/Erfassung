"""Asynchronous database-migration worker + status tracking (§0.9.7).

A database switch copies every table into the target backend and then rebinds
the live engine. Running that inside the HTTP request would tear down the very
connection the request uses, so – exactly like the restore worker
(:mod:`app.restore_jobs`) – the request only validates and *queues* the job
while a background daemon thread performs the migration and reports progress via
a JSON status file in the *data* volume.

The status file survives the engine swap (it is not part of the database), so
the progress page can always read the final result and redirect the user.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import app_config, db_migrator, paths

STATUS_FILE = paths.DATA_DIR / "db_migration_status.json"

ACTIVE_STATES = {
    "queued",
    "testing",
    "creating_backup",
    "creating_schema",
    "copying",
    "verifying",
    "switching",
}
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


def _worker(target_config: "app_config.DatabaseConfig", username: str, token: str, base: dict) -> None:
    def progress(state: str, percent: int, message: str) -> None:
        _update(token, base, state, percent, message)

    result = db_migrator.migrate(
        target_config, username=username, token=token, progress=progress
    )
    final_state = "completed" if result["status"] == "success" else "failed"
    _update(
        token,
        base,
        final_state,
        100,
        result["message"],
        finished_at=datetime.now().isoformat(timespec="seconds"),
        result_status=result["status"],
        records=result.get("records"),
        safety_backup=result.get("safety_backup"),
        post_backup=result.get("post_backup"),
        log_token=token,
        # Data is identical on the new backend, the session cookie stays valid,
        # so the admin returns straight to the database page.
        redirect="/admin/system/database",
    )


def start_migration(target_config: "app_config.DatabaseConfig", *, username: str) -> str:
    """Queue a migration job and start the background worker. Returns the token."""
    global _thread
    with _lock:
        if is_active():
            raise RuntimeError("Es läuft bereits eine Datenbankmigration.")
        from . import database

        token = datetime.now().strftime("%Y%m%d%H%M%S")
        base = {
            "username": username,
            "source_type": database.DB_TYPE,
            "target_type": app_config.database.normalise_type(target_config.type),
            "target": target_config.describe(),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "redirect": None,
            "result_status": None,
        }
        _update(token, base, "queued", 5, "Datenbankmigration wurde gestartet")
        _thread = threading.Thread(
            target=_worker,
            args=(target_config, username, token, base),
            name="db-migration-worker",
            daemon=True,
        )
        _thread.start()
        return token


def clear_status() -> None:
    try:
        STATUS_FILE.unlink(missing_ok=True)
    except OSError:  # pragma: no cover
        pass
