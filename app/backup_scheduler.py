"""Schlanke Ablaufsteuerung für Sicherungsaufträge im eigenen Prozess.

Ein Hintergrund-Thread wacht regelmäßig auf und startet jeden aktiven Auftrag,
dessen Zeitplan fällig ist (täglich, wöchentlich, monatlich). Bewusst einfach
gehalten, ohne zusätzliche Abhängigkeit, und für einen Einzelprozessbetrieb
unbedenklich. Die eigentliche Fälligkeitsprüfung (:func:`run_due_jobs`) ist
nebenwirkungsfrei und damit einzeln testbar.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from . import backup_manager, crud, database

LOGGER = logging.getLogger("erfassung.application")

_INTERVALS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}

_stop = threading.Event()
_thread: threading.Thread | None = None


def job_due(job, now: datetime) -> bool:
    if not job.active or job.schedule not in _INTERVALS:
        return False
    if job.last_run_at is None:
        return True
    return (now - job.last_run_at) >= _INTERVALS[job.schedule]


def run_due_jobs(db, now: datetime | None = None) -> list:
    """Alle fälligen Aufträge ausführen; Rückgabe sind die tatsächlich gelaufenen."""
    now = now or datetime.now()
    executed = []
    for job in crud.get_active_backup_jobs(db):
        if job_due(job, now):
            LOGGER.info("Geplanter Backup-Job '%s' wird ausgeführt", job.name)
            backup_manager.run_job(db, job, triggered_by="zeitplan")
            executed.append(job)
    return executed


def _loop(interval: int) -> None:
    # Anlaufverzögerung: Nach einem Neustart sollen nicht sofort alle
    # nachzuholenden Aufträge gleichzeitig losrennen.
    if _stop.wait(interval):
        return
    while not _stop.is_set():
        db = database.SessionLocal()
        try:
            run_due_jobs(db)
        except Exception:  # pragma: no cover - scheduler must never crash
            LOGGER.exception("Backup-Scheduler-Durchlauf fehlgeschlagen")
        finally:
            db.close()
        _stop.wait(interval)


def start(interval: int = 60) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval,), name="backup-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
