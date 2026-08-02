"""Datenbankmigration im Hintergrund samt Fortschrittsanzeige.

Ein Datenbankwechsel kopiert jede Tabelle ins Ziel und hängt danach die
laufende Verbindung um. Liefe das in der HTTP-Anfrage, risse es genau die
Verbindung ab, über die diese Anfrage läuft. Deshalb – wie bei der
Rücksicherung (:mod:`app.restore_jobs`) – prüft die Anfrage nur und **stellt
den Auftrag ein**; ein Hintergrund-Thread führt die Migration aus und meldet
den Fortschritt über eine JSON-Statusdatei im data-Volume.

Die Statusdatei gehört nicht zur Datenbank und überlebt den Wechsel. Die
Fortschrittsseite kann das Ergebnis deshalb immer lesen und weiterleiten.
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
        # Die Daten sind auf dem neuen Backend dieselben und das Sitzungscookie
        # bleibt gültig – die Administration landet direkt wieder auf der
        # Datenbankseite.
        redirect="/admin/system/database",
    )


def start_migration(target_config: "app_config.DatabaseConfig", *, username: str) -> str:
    """Migrationsauftrag einstellen und den Hintergrundlauf starten.

    Rückgabe ist die Kennung, unter der sich der Fortschritt abfragen lässt.
    """
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

