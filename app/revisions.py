"""Revisionssichere Historie der Zeitbuchungen.

Vorgabe: **Originaldaten werden niemals überschrieben oder physisch gelöscht.**
Das lässt sich mit einer veränderlichen Tabelle allein nicht einlösen, deshalb
liegt neben jeder Buchung eine fortlaufende Historie:

* Jede Anlage, Änderung, Freigabe, Ablehnung und Stornierung erzeugt einen
  Eintrag mit **Vorher- und Nachher-Stand**, Zeitpunkt, Bearbeiter und Quelle.
* Bei Änderung, Ablehnung und Storno ist eine **Begründung Pflicht** – ohne
  sie wird der Vorgang abgelehnt, nicht etwa leer protokolliert.
* Eine Korrektur läuft über **Storno plus Ersatzbuchung**: Die alte Buchung
  bleibt vollständig sichtbar und trägt einen Verweis auf ihren Ersatz.

Was diese Umsetzung leistet und was nicht: Sie macht jede Änderung
nachvollziehbar und macht stilles Verschwinden von Daten in der Anwendung
unmöglich. Sie kann nicht verhindern, dass jemand mit direktem Datenbank- oder
Dateizugriff Einträge manipuliert – dafür braucht es Rechte-, Backup- und
Betriebsmaßnahmen außerhalb der Anwendung. Eine Zertifizierung oder rechtliche
Garantie ist damit ausdrücklich nicht verbunden.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from . import models

LOGGER = logging.getLogger("erfassung.application")

#: Felder, die den fachlichen Inhalt einer Buchung ausmachen. Technische
#: Spalten (``updated_at``) bleiben außen vor – sie würden jede Historie mit
#: Rauschen füllen.
TRACKED_FIELDS = (
    "user_id",
    "company_id",
    "location_id",
    "work_date",
    "start_time",
    "end_time",
    "break_minutes",
    "break_started_at",
    "is_open",
    "notes",
    "status",
    "is_manual",
    "is_remote",
    "source",
    "external_id",
    "started_at_utc",
    "ended_at_utc",
    "tz_name",
    "break_rule",
    "cancelled_at",
    "cancel_reason",
    "replaced_by_id",
    "replaces_id",
)


class ReasonRequired(ValueError):
    """Der Vorgang braucht eine Begründung, es kam aber keine."""


def snapshot(entry: models.TimeEntry) -> dict[str, Any]:
    """Fachlicher Stand einer Buchung als einfache Werte."""
    data: dict[str, Any] = {}
    for field in TRACKED_FIELDS:
        value = getattr(entry, field, None)
        if isinstance(value, (datetime,)):
            data[field] = value.isoformat()
        elif hasattr(value, "isoformat"):
            data[field] = value.isoformat()
        else:
            data[field] = value
    breaks = [
        {
            "started_at_utc": interval.started_at_utc.isoformat()
            if interval.started_at_utc else None,
            "ended_at_utc": interval.ended_at_utc.isoformat()
            if interval.ended_at_utc else None,
            "minutes": interval.minutes,
        }
        for interval in (entry.breaks or [])
    ]
    if breaks:
        data["breaks"] = breaks
    return data


def diff(before: Optional[dict[str, Any]], after: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Nur die geänderten Felder – für die Anzeige in der Historie."""
    before = before or {}
    after = after or {}
    changed: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            changed[key] = {"vorher": old, "nachher": new}
    return changed


def _actor_label(actor: object) -> str:
    if actor is None:
        return "System"
    name = getattr(actor, "full_name", None) or getattr(actor, "username", None)
    return str(name) if name else "System"


def record(
    db: Session,
    entry: models.TimeEntry,
    action: str,
    *,
    actor: object = None,
    reason: str = "",
    before: Optional[dict[str, Any]] = None,
    after: Optional[dict[str, Any]] = None,
    source: Optional[str] = None,
    tz_name: Optional[str] = None,
    commit: bool = False,
) -> models.TimeEntryRevision:
    """Einen Vorgang historisieren.

    Löst :class:`ReasonRequired` aus, wenn eine Pflichtbegründung fehlt. Das
    ist Absicht: Lieber ein abgelehnter Vorgang als eine Historie, die „wurde
    geändert" sagt und sonst nichts.
    """
    cleaned = (reason or "").strip()
    if action in models.REVISION_REASON_REQUIRED and not cleaned:
        raise ReasonRequired(
            "Für diesen Vorgang ist eine Begründung erforderlich."
        )

    last = (
        db.query(models.TimeEntryRevision)
        .filter(models.TimeEntryRevision.entry_id == entry.id)
        .order_by(models.TimeEntryRevision.revision_no.desc())
        .first()
    )
    revision = models.TimeEntryRevision(
        entry_id=entry.id,
        revision_no=(last.revision_no + 1) if last else 1,
        action=action,
        changed_at_utc=datetime.utcnow(),
        tz_name=tz_name or getattr(entry, "tz_name", None),
        actor_id=getattr(actor, "id", None),
        actor_label=_actor_label(actor),
        reason=cleaned[:500] or None,
        source=source or entry.source or None,
        before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
        after_json=json.dumps(after, ensure_ascii=False) if after is not None else None,
    )
    db.add(revision)
    if commit:
        db.commit()
        db.refresh(revision)
    else:
        db.flush()
    return revision


def record_creation(
    db: Session,
    entry: models.TimeEntry,
    *,
    actor: object = None,
    source: Optional[str] = None,
    commit: bool = False,
) -> models.TimeEntryRevision:
    """Anlage einer Buchung – ohne Begründungspflicht."""
    return record(
        db,
        entry,
        models.RevisionAction.CREATED,
        actor=actor,
        after=snapshot(entry),
        source=source,
        commit=commit,
    )


def history(db: Session, entry_id: int) -> list[models.TimeEntryRevision]:
    return (
        db.query(models.TimeEntryRevision)
        .filter(models.TimeEntryRevision.entry_id == entry_id)
        .order_by(models.TimeEntryRevision.revision_no)
        .all()
    )


def history_for_user(
    db: Session, user_id: int, *, limit: int = 500
) -> list[models.TimeEntryRevision]:
    """Historie aller Buchungen einer Person – für den Auskunftsexport."""
    return (
        db.query(models.TimeEntryRevision)
        .join(models.TimeEntry, models.TimeEntry.id == models.TimeEntryRevision.entry_id)
        .filter(models.TimeEntry.user_id == user_id)
        .order_by(models.TimeEntryRevision.changed_at_utc.desc())
        .limit(limit)
        .all()
    )


def parse(payload: Optional[str]) -> Optional[dict[str, Any]]:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


ACTION_LABELS = {
    models.RevisionAction.CREATED: "Angelegt",
    models.RevisionAction.CLOSED: "Beendet",
    models.RevisionAction.UPDATED: "Geändert",
    models.RevisionAction.APPROVED: "Freigegeben",
    models.RevisionAction.REJECTED: "Abgelehnt",
    models.RevisionAction.CANCELLED: "Storniert",
    models.RevisionAction.REPLACED: "Ersetzt",
    models.RevisionAction.REOPENED: "Wieder geöffnet",
}

FIELD_LABELS = {
    "work_date": "Datum",
    "start_time": "Beginn",
    "end_time": "Ende",
    "break_minutes": "Pause (Min)",
    "break_started_at": "Pause seit",
    "is_open": "läuft",
    "notes": "Kommentar",
    "status": "Status",
    "company_id": "Firma",
    "location_id": "Einsatzort",
    "is_remote": "Remote",
    "is_manual": "Nachtrag",
    "user_id": "Benutzer",
    "cancelled_at": "Storniert am",
    "cancel_reason": "Stornogrund",
    "replaced_by_id": "Ersetzt durch",
    "replaces_id": "Ersetzt",
    "started_at_utc": "Beginn (UTC)",
    "ended_at_utc": "Ende (UTC)",
    "tz_name": "Zeitzone",
    "break_rule": "Pausenregel",
    "source": "Quelle",
    "external_id": "Fremdschlüssel",
    "breaks": "Pausen",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def field_label(field: str) -> str:
    return FIELD_LABELS.get(field, field)


__all__ = [
    "ReasonRequired",
    "TRACKED_FIELDS",
    "action_label",
    "diff",
    "field_label",
    "history",
    "history_for_user",
    "parse",
    "record",
    "record_creation",
    "snapshot",
]
