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

Deshalb wird nach jedem Test die gerade geladene Engine geschlossen. Das ist
reine Testhygiene und ändert nichts am Verhalten der Anwendung.
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _dispose_database_engine():
    """Verbindungspool der zuletzt geladenen Engine nach jedem Test schließen."""
    yield
    database = sys.modules.get("app.database")
    engine = getattr(database, "engine", None) if database is not None else None
    if engine is None:
        return
    try:
        engine.dispose()
    except Exception:  # pragma: no cover - Aufräumen darf keinen Test kippen
        pass
