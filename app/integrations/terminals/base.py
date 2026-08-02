"""Gemeinsame Treiberschnittstelle aller Terminaltypen."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass
class TerminalTestResult:
    """Outcome of a connection test."""

    ok: bool
    message: str
    version: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "message": self.message, "version": self.version}


@dataclass
class TerminalSyncOutcome:
    """Outcome of a synchronisation run."""

    status: str  # success / warning / error
    imported: int = 0
    errors: int = 0
    message: str = ""
    # Fortschrittsmarke, die in die Terminalzeile zurückgeschrieben wird –
    # ihre Bedeutung legt der jeweilige Treiber fest.
    last_event_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "imported": self.imported,
            "errors": self.errors,
            "message": self.message,
            "last_event_id": self.last_event_id,
        }


class TerminalDriver:
    """Basisklasse jedes konkreten Terminaltreibers.

    Treiber halten keinen eigenen Zustand: Die gesamte Konfiguration steht in
    der ``Terminal``-Zeile, die jeder Methode übergeben wird. Dadurch bleibt die
    Treiberschicht frei von globalem Zustand, und ein neuer Terminaltyp ist mit
    wenig Aufwand ergänzt.
    """

    #: Feste Kennung; steht in ``Terminal.type`` und dient als Registerschlüssel.
    key: str = ""
    #: Lesbare Bezeichnung für die Auswahlliste in der Oberfläche.
    label: str = ""

    def test_connection(self, terminal) -> TerminalTestResult:  # pragma: no cover - interface
        raise NotImplementedError

    def synchronize(
        self, db: Session, terminal, *, full_sync: bool = False
    ) -> TerminalSyncOutcome:  # pragma: no cover - interface
        raise NotImplementedError
