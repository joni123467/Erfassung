"""Austauschbare Treiber für Zeiterfassungsterminals.

Die allgemeine Terminalverwaltung enthält **keine** Logik für einen bestimmten
Terminaltyp. Jeder unterstützte Typ steckt in einem eigenen Treiber, der
:class:`app.integrations.terminals.base.TerminalDriver` erfüllt und sich in
:data:`REGISTRY` einträgt.

Oberfläche und Wegewahl sprechen ausschließlich mit der Treiberschnittstelle.
Ein neuer Terminaltyp (ZKTeco, Suprema, allgemeines REST/CSV, …) ist deshalb
eine neue Treiberdatei und ein Eintrag hier – sonst nichts.
"""

from __future__ import annotations

from .base import (
    TerminalDriver,
    TerminalSyncOutcome,
    TerminalTestResult,
)
from .timemoto_driver import TimeMotoDriver

# Driver key -> driver instance.
REGISTRY: dict[str, TerminalDriver] = {}


def register(driver: TerminalDriver) -> None:
    REGISTRY[driver.key] = driver


def get_driver(key: str) -> TerminalDriver | None:
    return REGISTRY.get(key)


def available_types() -> list[dict[str, str]]:
    """Terminaltypen für die Oberfläche: Treiberkennung und lesbare Bezeichnung."""

    return [
        {"key": driver.key, "label": driver.label}
        for driver in sorted(REGISTRY.values(), key=lambda d: d.label.lower())
    ]


def is_known_type(key: str) -> bool:
    return key in REGISTRY


# -- Mitgelieferte Treiber --------------------------------------------------
# Weitere Terminaltypen werden genauso eingetragen, etwa:
#   register(ZKTecoDriver())
#   register(SupremaDriver())
register(TimeMotoDriver())


__all__ = [
    "TerminalDriver",
    "TerminalSyncOutcome",
    "TerminalTestResult",
    "REGISTRY",
    "register",
    "get_driver",
    "available_types",
    "is_known_type",
]
