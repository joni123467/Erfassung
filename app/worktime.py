"""Zentrale Dauerberechnung für Zeitbuchungen (ab 0.16.0).

Bis 0.15.0 gab es die Rechnung zweimal: ``compliance._entry_bounds()`` rechnete
in UTC, ``TimeEntry.gross_minutes`` dagegen mit naiven Ortszeiten. Zwei Wege für
dieselbe Frage – und über eine Zeitumstellung hinweg zwei verschiedene
Antworten. Die Regelprüfung sah eine Stunde mehr oder weniger als Auswertung,
Zeitkonto und Export.

Dieses Modul ist ab jetzt die **einzige** Quelle. Es kennt zwei Fälle:

* **Neue Buchungen** tragen ``started_at_utc`` und ``ended_at_utc``. Diese
  Werte sind eindeutig und haben Vorrang – über eine Zeitumstellung hinweg ist
  nur so eine korrekte Dauer zu bekommen.
* **Bestandsbuchungen** (vor 0.14.0) haben nur ``work_date`` und lokale
  Uhrzeiten. Dann wird über die Zeitzone der Buchung (``tz_name``, sonst die
  Betriebszeitzone) umgerechnet. Das ist eine Annäherung, wenn die Zeitzone der
  Installation seit der Erfassung geändert wurde – geraten wird nichts, und
  nachträglich umgeschrieben wird auch nichts.

Bewusst ohne Import von :mod:`app.models`: Die Funktionen arbeiten über
Attribute (Duck-Typing). Sonst entstünde ein Importzyklus, denn ``models``
benutzt dieses Modul selbst.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

#: Zeitzone des Betriebs. Sie gilt für alle Beschäftigten – Kundenstandorte
#: ändern daran nichts (siehe ``app/compliance.py``).
TIMEZONE_ENV = "ERFASSUNG_TIMEZONE"
DEFAULT_TIMEZONE = "Europe/Berlin"

_UTC = timezone.utc


def timezone_name() -> str:
    """Konfigurierte Betriebszeitzone (ab 0.17.0 persistent).

    Reihenfolge: gespeicherte Systemkonfiguration → ``ERFASSUNG_TIMEZONE`` →
    Vorgabe. Die Umgebungsvariable dient damit nur noch als Vorbelegung bei der
    **Erstinstallation**; eine bereits gespeicherte Konfiguration überschreibt
    sie nie. Das entspricht der Regel, die für die Datenbankkonfiguration
    schon gilt.

    Eine Änderung wirkt ausschließlich auf **neue** Buchungen: Bestehende
    tragen ihr ``tz_name`` mit sich, und das wird nicht nachträglich
    umgeschrieben – sonst verschöben sich vergangene Zeiten.
    """
    try:
        from . import app_config

        stored = (app_config.load_system_settings().timezone or "").strip()
        if stored:
            return stored
    except Exception:  # pragma: no cover - Konfigurationsfehler darf nichts kippen
        pass
    return (os.environ.get(TIMEZONE_ENV) or "").strip() or DEFAULT_TIMEZONE


def zone(name: Optional[str] = None) -> ZoneInfo:
    """Zeitzone nach Name – mit der Betriebszeitzone als Rückfallebene."""
    for candidate in (name, timezone_name()):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except Exception:  # pragma: no cover - unbekannte Zone in Altdaten
            continue
    return ZoneInfo("UTC")


def from_local(moment: Optional[datetime], tz: ZoneInfo) -> Optional[datetime]:
    """Ortszeit nach UTC. Für ``work_date`` + ``start_time``/``end_time``."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=tz).astimezone(_UTC)
    return moment.astimezone(_UTC)


def from_utc_column(moment: Optional[datetime]) -> Optional[datetime]:
    """Wert aus einer ``*_at_utc``-Spalte zonenbehaftet machen.

    Die Spalte heißt nicht umsonst so: Ihr Inhalt **ist** UTC. Ein naiver Wert
    darf hier nicht als Ortszeit gelesen werden – das verschöbe jede Auswertung
    um den Zonenversatz.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=_UTC)
    return moment.astimezone(_UTC)


def entry_bounds(entry: Any) -> tuple[datetime, datetime]:
    """Beginn und Ende einer Buchung als **UTC-Zeitpunkte**.

    Eine laufende Buchung endet „jetzt". Endet eine Bestandsbuchung vor ihrem
    Beginn, liegt das Ende am Folgetag – so wird Nachtarbeit über Mitternacht
    richtig gerechnet.
    """
    tz = zone(getattr(entry, "tz_name", None))

    start = from_utc_column(getattr(entry, "started_at_utc", None))
    if start is None:
        start = from_local(
            datetime.combine(
                entry.work_date, getattr(entry, "start_time", None) or time(0, 0)
            ),
            tz,
        )

    if getattr(entry, "is_open", False) or getattr(entry, "end_time", None) is None:
        end = datetime.now(_UTC)
    else:
        end = from_utc_column(getattr(entry, "ended_at_utc", None))
        if end is None:
            end = from_local(datetime.combine(entry.work_date, entry.end_time), tz)
            if end is not None and end < start:
                end += timedelta(days=1)
    if end < start:
        end = start
    return start, end


def gross_minutes(entry: Any) -> int:
    """Anwesenheit von Beginn bis Ende in Minuten – ohne Pausenabzug."""
    start, end = entry_bounds(entry)
    return max(int((end - start).total_seconds() // 60), 0)


def local_date(moment: datetime, tz_name: Optional[str] = None) -> date:
    """Kalendertag eines UTC-Zeitpunkts in Ortszeit."""
    return moment.astimezone(zone(tz_name)).date()


def to_utc_naive(moment: Optional[datetime], tz_name: Optional[str] = None):
    """Ortszeit als naiven UTC-Wert – so, wie ihn die Spalten speichern."""
    if moment is None:
        return None
    converted = from_local(moment, zone(tz_name))
    return converted.replace(tzinfo=None) if converted else None


__all__ = [
    "DEFAULT_TIMEZONE",
    "TIMEZONE_ENV",
    "entry_bounds",
    "from_local",
    "from_utc_column",
    "gross_minutes",
    "local_date",
    "timezone_name",
    "to_utc_naive",
    "zone",
]
