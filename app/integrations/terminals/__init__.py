"""Pluggable time-recording terminal drivers (§0.9.8).

The generic terminal management does not contain any terminal-specific logic.
Each supported terminal type is implemented as a *driver* that conforms to
:class:`app.integrations.terminals.base.TerminalDriver` and registers itself in
the :data:`REGISTRY`. The UI and the routing layer only ever talk to the driver
interface, so adding a new terminal type (ZKTeco, Suprema, generic REST/CSV, …)
is a matter of dropping in a new driver module and registering it here.
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
    """Terminal types offered in the UI (driver key + human label)."""

    return [
        {"key": driver.key, "label": driver.label}
        for driver in sorted(REGISTRY.values(), key=lambda d: d.label.lower())
    ]


def is_known_type(key: str) -> bool:
    return key in REGISTRY


# -- Built-in drivers -------------------------------------------------------
# Further terminal types are registered the same way, e.g.:
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
