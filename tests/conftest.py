"""Gemeinsame Testinfrastruktur.

Jeder Test lädt die Anwendung frisch (die Module unter ``app`` werden aus
``sys.modules`` entfernt und neu importiert) und legt dabei eine eigene
SQLAlchemy-Engine mit eigenem Verbindungspool an. Die alte Engine wird dabei
nur noch dereferenziert – ihre offenen SQLite-Verbindungen bleiben bestehen,
bis der Garbage Collector sie einsammelt.

Für einzelne Testdateien fällt das nicht auf. Über die gesamte Suite hinweg
summiert es sich: Der Prozess läuft in das Limit für offene Dateien und bricht
mit ``OSError: [Errno 24] Too many open files`` ab – und zwar erst beim
Aufräumen am Ende, sodass pytest gar keine Zusammenfassung mehr schreibt. Ein
grüner Lauf ist dann nicht mehr von einem roten zu unterscheiden.

Deshalb wird nach jedem Test aufgeräumt. Das ist reine Testhygiene und ändert
nichts am Verhalten der Anwendung.
"""

from __future__ import annotations

import gc
import os
import sys

import pytest

#: Ab so vielen offenen Dateideskriptoren wird zusätzlich der Heap nach
#: verwaisten Engines durchsucht. Das Limit des Containers liegt bei 4096;
#: der Schwellwert lässt genug Luft und hält die teure Suche selten.
_FD_SWEEP_THRESHOLD = 1500


def _open_fd_count() -> int:
    """Offene Dateideskriptoren des Prozesses – oder 0, wenn nicht ermittelbar."""
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:  # pragma: no cover - andere Plattformen
        return 0


def _dispose(engine: object) -> None:
    try:
        engine.dispose()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - Aufräumen darf keinen Test kippen
        pass


def _sweep_orphaned_engines() -> None:
    """Verwaiste Engines auf dem Heap schließen.

    Nicht jede Engine hängt an ``app.database``: Der datenbankübergreifende
    Restore baut eigene Engines für Quelle und Ziel, und ein Modulneuladen
    lässt die vorherige Engine unerreichbar, aber mit offenem Pool zurück.
    Diese Suche ist teuer, deshalb läuft sie erst, wenn wirklich viele
    Deskriptoren offen sind.
    """
    try:
        from sqlalchemy.engine import Engine
    except Exception:  # pragma: no cover
        return
    gc.collect()
    for obj in gc.get_objects():
        try:
            if isinstance(obj, Engine):
                _dispose(obj)
        except ReferenceError:  # pragma: no cover - Objekt verschwand beim Iterieren
            continue


@pytest.fixture(autouse=True)
def _dispose_database_engine():
    """Verbindungspools nach jedem Test schließen."""
    yield
    database = sys.modules.get("app.database")
    engine = getattr(database, "engine", None) if database is not None else None
    if engine is not None:
        _dispose(engine)
    if _open_fd_count() > _FD_SWEEP_THRESHOLD:
        _sweep_orphaned_engines()
