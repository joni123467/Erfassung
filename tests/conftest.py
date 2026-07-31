"""Gemeinsame Testinfrastruktur.

Jeder Test lädt die Anwendung frisch: Die Module unter ``app`` werden aus
``sys.modules`` entfernt und neu importiert. Dabei bleiben zwei Sorten von
Ressourcen offen zurück, weil die Anwendung im Betrieb nie neu geladen wird
und daher auch nichts aufzuräumen hat:

1. **Der Verbindungspool der Datenbank.** Die vorherige ``app.database``-Engine
   wird nur dereferenziert; ihre SQLite-Verbindungen bleiben bis zur nächsten
   Garbage Collection offen.
2. **Die Logdateien.** ``logging_setup`` merkt sich seine Handler in einer
   modulweiten Liste und schließt sie beim Neukonfigurieren. Wird das *Modul*
   ersetzt, ist diese Liste leer – die Handler des alten Moduls hängen aber
   weiter an den ``erfassung.*``-Loggern, denn die leben in der globalen
   Logging-Registrierung und werden nicht mitgeladen. Pro Test bleiben so rund
   zehn offene Logdateien liegen.

Über die gesamte Suite summiert sich das bis an das Limit für offene Dateien
(``OSError: [Errno 24] Too many open files``). Das Tückische daran: Es trifft
irgendeinen späten Test oder erst das Aufräumen am Ende – ein grüner Lauf ist
dann nicht mehr von einem roten zu unterscheiden.

Deshalb wird nach jedem Test beides geschlossen. Reine Testhygiene; am
Verhalten der Anwendung ändert das nichts.
"""

from __future__ import annotations

import logging
import sys

import pytest

#: Wurzel der Kanal-Logger aus ``app.logging_setup``.
_LOGGER_PREFIX = "erfassung"


def _close(resource: object, method: str) -> None:
    try:
        getattr(resource, method)()
    except Exception:  # pragma: no cover - Aufräumen darf keinen Test kippen
        pass


def _dispose_engine() -> None:
    database = sys.modules.get("app.database")
    engine = getattr(database, "engine", None) if database is not None else None
    if engine is not None:
        _close(engine, "dispose")


def _close_log_handlers() -> None:
    """Dateihandler der ``erfassung.*``-Logger abhängen und schließen."""
    manager = logging.Logger.manager
    names = [
        name
        for name in list(manager.loggerDict)
        if name == _LOGGER_PREFIX or name.startswith(f"{_LOGGER_PREFIX}.")
    ]
    targets = [logging.getLogger(name) for name in names]
    targets.append(logging.getLogger())  # error.log hängt am Root-Logger
    for logger in targets:
        for handler in list(getattr(logger, "handlers", [])):
            # Nur Dateihandler: Die Konsolen- und Capture-Handler von pytest
            # bleiben unangetastet, sonst verlöre der Bericht seine Ausgabe.
            if isinstance(handler, logging.FileHandler):
                logger.removeHandler(handler)
                _close(handler, "close")


@pytest.fixture(autouse=True)
def _release_process_resources():
    """Datenbankpool und Logdateien nach jedem Test freigeben."""
    yield
    _dispose_engine()
    _close_log_handlers()
