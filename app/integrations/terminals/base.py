"""Driver interface shared by every terminal type (§0.9.8)."""

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
    # Incremental cursor written back to the terminal record (driver specific).
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
    """Base class every concrete terminal driver inherits from.

    Drivers are stateless: all configuration lives on the ``Terminal`` model row
    that is passed into every method. This keeps the driver layer free of any
    global state and makes new terminal types trivial to add.
    """

    #: Stable identifier persisted in ``Terminal.type`` and used in the registry.
    key: str = ""
    #: Human readable label shown in the UI dropdown.
    label: str = ""

    def test_connection(self, terminal) -> TerminalTestResult:  # pragma: no cover - interface
        raise NotImplementedError

    def synchronize(
        self, db: Session, terminal, *, full_sync: bool = False
    ) -> TerminalSyncOutcome:  # pragma: no cover - interface
        raise NotImplementedError
