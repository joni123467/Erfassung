"""Regelmäßige Nachfrage beim Lizenzserver (ab 0.12.0).

Ein Hintergrundthread fragt einmal täglich nach, ob die Lizenz noch gilt, und
holt dabei ein frisch signiertes Dokument. Damit wirken Änderungen an
Benutzerzahl, Laufzeit und Funktionsbausteinen ohne Zutun des Kunden.

Der wichtigste Grundsatz steht in :func:`app.licensing.refresh_from_server`:
**Ein unerreichbarer Lizenzserver sperrt nie.** Der Thread protokolliert die
Störung und lässt die gespeicherte Lizenz unverändert weiterlaufen. Nur eine
ausdrückliche Sperrmeldung des Servers startet die Übergangsfrist.

Bewusst ohne externe Abhängigkeit und ohne eigene Zustandsdatei – der
Zeitpunkt der letzten Nachfrage steht in ``config/license.json``.
"""

from __future__ import annotations

import logging
import threading

from . import licensing

LOGGER = logging.getLogger("erfassung.application")

#: Wie oft der Thread aufwacht. Ob wirklich nachgefragt wird, entscheidet
#: :func:`app.licensing.due_for_check` anhand des letzten Kontakts.
WAKE_INTERVAL_SECONDS = 3600

#: Kurze Wartezeit nach dem Start, damit die Anwendung erst hochkommt.
INITIAL_DELAY_SECONDS = 60

_stop = threading.Event()
_thread: threading.Thread | None = None


def check_now(force: bool = False) -> tuple[bool, str]:
    """Einmal nachfragen, sofern fällig. Gibt ``(erreicht, Meldung)``.

    Rein und einzeln aufrufbar – so lässt sich der Ablauf ohne Thread testen.
    """
    try:
        if not force and not licensing.due_for_check():
            return False, "Noch nicht fällig."
        return licensing.refresh_from_server()
    except Exception as exc:  # pragma: no cover - darf den Thread nie beenden
        LOGGER.warning("Lizenzprüfung fehlgeschlagen: %s", exc)
        return False, str(exc)


def _loop() -> None:
    # Erst einmal Luft holen: Beim Start ist die Anwendung mit Migrationen und
    # Seeding beschäftigt, und der Lizenzserver läuft vielleicht noch gar nicht.
    if _stop.wait(INITIAL_DELAY_SECONDS):
        return
    while not _stop.is_set():
        check_now()
        if _stop.wait(WAKE_INTERVAL_SECONDS):
            return


def start() -> None:
    """Hintergrundprüfung starten. Mehrfaches Aufrufen ist unschädlich."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="license-check", daemon=True)
    _thread.start()
    LOGGER.info(
        "Lizenzprüfung gestartet (alle %s Stunden).", licensing.CHECK_INTERVAL_HOURS
    )


def stop() -> None:
    global _thread
    _stop.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)
    _thread = None


def is_running() -> bool:
    return bool(_thread and _thread.is_alive())


__all__ = ["check_now", "is_running", "start", "stop"]
