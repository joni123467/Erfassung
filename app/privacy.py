"""Datenschutz: Aufbewahrungsfristen und Auskunftsexport.

**Aufbewahrung.** Zeiterfassungsdaten unterliegen mehreren Fristen, die sich
widersprechen können: §16 Abs. 2 ArbZG verlangt mindestens zwei Jahre,
§17 Abs. 2 MiLoG ebenfalls zwei Jahre, steuer- und handelsrechtliche
Aufbewahrung reicht weiter, und Art. 5 Abs. 1 lit. e DSGVO verlangt Löschung,
sobald der Zweck entfällt. Die Anwendung legt deshalb keine Frist fest, sondern
macht sie **einstellbar und sichtbar** – mit Vorgabewerten, die sich an den
Mindestfristen orientieren.

Gelöscht wird nichts automatisch. Eine Zeiterfassung, die von sich aus Daten
entfernt, kann einen Nachweis vernichten, den jemand noch braucht. Statt dessen
zeigt :func:`retention_report`, was die Fristen überschritten hat, und die
Löschung bleibt eine bewusste Entscheidung.

**Auskunft.** Art. 15 DSGVO gibt jeder Person das Recht auf Kopie ihrer Daten.
:func:`subject_export` stellt sie vollständig zusammen: Stammdaten, Buchungen,
Pausen, Änderungshistorie, Kennzeichnungen, Urlaub und die protokollierten
Zugriffe auf ihre Daten.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from . import models, paths

_CONFIG_PATH = paths.CONFIG_DIR / "retention.json"

#: Vorgaben in Monaten. Bewusst an den gesetzlichen **Mindest**fristen
#: orientiert; wer länger aufbewahren muss, stellt sie hoch.
DEFAULT_TIME_ENTRY_MONTHS = 24
DEFAULT_ACCESS_LOG_MONTHS = 12
DEFAULT_REVISION_MONTHS = 24


@dataclass
class RetentionPolicy:
    """Aufbewahrungsfristen in Monaten. ``0`` heißt „unbegrenzt aufbewahren"."""

    time_entries_months: int = DEFAULT_TIME_ENTRY_MONTHS
    revisions_months: int = DEFAULT_REVISION_MONTHS
    access_log_months: int = DEFAULT_ACCESS_LOG_MONTHS
    #: Freitext für die Verfahrensdokumentation.
    note: str = field(
        default=(
            "Mindestens zwei Jahre nach §16 Abs. 2 ArbZG und §17 Abs. 2 MiLoG. "
            "Längere handels- oder steuerrechtliche Fristen können vorgehen."
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_policy() -> RetentionPolicy:
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return RetentionPolicy()
    if not isinstance(raw, dict):
        return RetentionPolicy()
    policy = RetentionPolicy()
    for key in ("time_entries_months", "revisions_months", "access_log_months"):
        value = raw.get(key)
        if isinstance(value, int) and value >= 0:
            setattr(policy, key, value)
    if isinstance(raw.get("note"), str):
        policy.note = raw["note"][:1000]
    return policy


def save_policy(policy: RetentionPolicy) -> RetentionPolicy:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(policy.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return policy


def _cutoff(months: int, today: Optional[date] = None) -> Optional[date]:
    if months <= 0:
        return None
    today = today or date.today()
    year = today.year - (months // 12)
    month = today.month - (months % 12)
    if month <= 0:
        month += 12
        year -= 1
    day = min(today.day, 28)
    return date(year, month, day)


def retention_report(db: Session, policy: Optional[RetentionPolicy] = None) -> dict[str, Any]:
    """Was hat seine Frist überschritten? Zählt nur – löscht nichts."""
    policy = policy or load_policy()
    entry_cutoff = _cutoff(policy.time_entries_months)
    access_cutoff = _cutoff(policy.access_log_months)
    revision_cutoff = _cutoff(policy.revisions_months)

    result: dict[str, Any] = {"policy": policy.to_dict()}
    result["time_entries"] = {
        "cutoff": entry_cutoff.isoformat() if entry_cutoff else None,
        "count": (
            db.query(models.TimeEntry)
            .filter(models.TimeEntry.work_date < entry_cutoff)
            .count()
            if entry_cutoff else 0
        ),
    }
    result["access_log"] = {
        "cutoff": access_cutoff.isoformat() if access_cutoff else None,
        "count": (
            db.query(models.DataAccessLog)
            .filter(
                models.DataAccessLog.accessed_at
                < datetime.combine(access_cutoff, datetime.min.time())
            )
            .count()
            if access_cutoff else 0
        ),
    }
    result["revisions"] = {
        "cutoff": revision_cutoff.isoformat() if revision_cutoff else None,
        "count": (
            db.query(models.TimeEntryRevision)
            .filter(
                models.TimeEntryRevision.changed_at_utc
                < datetime.combine(revision_cutoff, datetime.min.time())
            )
            .count()
            if revision_cutoff else 0
        ),
    }
    return result


def purge_access_log(db: Session, policy: Optional[RetentionPolicy] = None) -> int:
    """Abgelaufene Zugriffsprotokolle entfernen.

    Nur dieses eine Protokoll wird auf Wunsch bereinigt: Es ist reines
    Kontrollmaterial ohne Nachweisfunktion für Arbeitszeit. Buchungen und
    Revisionen werden **nie** automatisch gelöscht.
    """
    policy = policy or load_policy()
    cutoff = _cutoff(policy.access_log_months)
    if cutoff is None:
        return 0
    limit = datetime.combine(cutoff, datetime.min.time())
    removed = (
        db.query(models.DataAccessLog)
        .filter(models.DataAccessLog.accessed_at < limit)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(removed or 0)


def _stamp(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def subject_export(db: Session, user: models.User) -> dict[str, Any]:
    """Vollständige Auskunft über eine Person (Art. 15 DSGVO).

    Enthält bewusst auch die **Zugriffe auf** ihre Daten: Wer wissen will, was
    über ihn gespeichert ist, will in aller Regel auch wissen, wer es gesehen
    hat.
    """
    entries = (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user.id)
        .order_by(models.TimeEntry.work_date, models.TimeEntry.start_time)
        .all()
    )
    entry_ids = [entry.id for entry in entries]

    revisions = (
        db.query(models.TimeEntryRevision)
        .filter(models.TimeEntryRevision.entry_id.in_(entry_ids or [0]))
        .order_by(models.TimeEntryRevision.changed_at_utc)
        .all()
    )
    flags = (
        db.query(models.ComplianceFlag)
        .filter(models.ComplianceFlag.user_id == user.id)
        .order_by(models.ComplianceFlag.work_date)
        .all()
    )
    # Die Historie hängt an den Feststellungen dieser Person – aufsteigend,
    # damit die Auskunft den Verlauf in der Reihenfolge zeigt, in der er
    # entstanden ist.
    compliance_logs = (
        db.query(models.ComplianceLog)
        .filter(models.ComplianceLog.flag_id.in_([flag.id for flag in flags] or [0]))
        .order_by(models.ComplianceLog.id)
        .all()
    )
    accesses = (
        db.query(models.DataAccessLog)
        .filter(models.DataAccessLog.subject_user_id == user.id)
        .order_by(models.DataAccessLog.accessed_at)
        .all()
    )
    vacations = (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.user_id == user.id)
        .order_by(models.VacationRequest.start_date)
        .all()
    )

    return {
        "erstellt_am": datetime.utcnow().isoformat(),
        "hinweis": (
            "Auskunft nach Art. 15 DSGVO. Enthält alle zu dieser Person "
            "gespeicherten Zeiterfassungsdaten samt Änderungshistorie, der "
            "arbeitsrechtlichen Bewertung mit ihrem Verlauf und den "
            "protokollierten Zugriffen auf diese Daten."
        ),
        "person": {
            "id": user.id,
            "benutzername": user.username,
            "name": user.full_name,
            "email": user.email,
            "gruppen": [group.name for group in user.groups],
            "rollen": [role.name for role in user.roles],
            "wochenarbeitszeit_stunden": user.standard_weekly_hours,
            "jahresurlaub_tage": user.annual_vacation_days,
        },
        "buchungen": [
            {
                "id": entry.id,
                "datum": _stamp(entry.work_date),
                "beginn": _stamp(entry.start_time),
                "ende": _stamp(entry.end_time),
                "beginn_utc": _stamp(entry.started_at_utc),
                "ende_utc": _stamp(entry.ended_at_utc),
                "zeitzone": entry.tz_name,
                "pause_minuten": entry.total_break_minutes,
                "pausen": [
                    {
                        "beginn_utc": _stamp(interval.started_at_utc),
                        "ende_utc": _stamp(interval.ended_at_utc),
                        "minuten": interval.minutes,
                    }
                    for interval in entry.breaks
                ],
                "gearbeitet_minuten": entry.worked_minutes,
                "status": entry.status,
                "firma": entry.company_display_name,
                "einsatzort": entry.location_label,
                "kommentar": entry.notes,
                "quelle": entry.source,
                "storniert_am": _stamp(entry.cancelled_at),
                "stornogrund": entry.cancel_reason,
                "ersetzt_durch": entry.replaced_by_id,
                "ersetzt": entry.replaces_id,
            }
            for entry in entries
        ],
        "aenderungshistorie": [
            {
                "buchung": revision.entry_id,
                "nr": revision.revision_no,
                "vorgang": revision.action,
                "zeitpunkt_utc": _stamp(revision.changed_at_utc),
                "bearbeiter": revision.actor_label,
                "begruendung": revision.reason,
                "vorher": json.loads(revision.before_json) if revision.before_json else None,
                "nachher": json.loads(revision.after_json) if revision.after_json else None,
            }
            for revision in revisions
        ],
        "kennzeichnungen": [
            {
                "datum": _stamp(flag.work_date),
                "code": flag.code,
                "schwere": flag.severity,
                "beschreibung": flag.detail,
                "eingeordnet_am": _stamp(flag.acknowledged_at),
                "einordnung": flag.acknowledgement,
                # Ab 0.17.0 auch die arbeitsrechtliche Bewertung selbst: Wer
                # eine Sonntagsarbeit als zulässig eingestuft hat und worauf er
                # sich dabei berief, gehört zu den Daten über diese Person.
                "ausnahmegrund": flag.exception_reason,
                "rechtsgrundlage": flag.legal_basis,
                "ersatzruhetag": _stamp(flag.replacement_rest_date),
                "bearbeitungsstand": flag.handling_state,
            }
            for flag in flags
        ],
        "compliance_historie": [
            {
                "kennzeichnung": log.flag_id,
                "vorgang": log.action,
                "zeitpunkt_utc": _stamp(log.changed_at_utc),
                "bearbeiter": log.actor_label,
                "begruendung": log.reason,
                "quelle": log.source,
                "vorher": json.loads(log.before_json) if log.before_json else None,
                "nachher": json.loads(log.after_json) if log.after_json else None,
            }
            for log in compliance_logs
        ],
        "urlaub": [
            {
                "von": _stamp(vacation.start_date),
                "bis": _stamp(vacation.end_date),
                "status": vacation.status,
                "abwesenheitsart": vacation.absence_type_key,
                "kommentar": vacation.comment,
            }
            for vacation in vacations
        ],
        "arbeitszeitplaene": [
            {
                "name": plan.name, "gueltig_ab": _stamp(plan.valid_from),
                "gueltig_bis": _stamp(plan.valid_until),
                "sollminuten": {
                    "montag": plan.monday_minutes, "dienstag": plan.tuesday_minutes,
                    "mittwoch": plan.wednesday_minutes, "donnerstag": plan.thursday_minutes,
                    "freitag": plan.friday_minutes, "samstag": plan.saturday_minutes,
                    "sonntag": plan.sunday_minutes,
                },
            }
            for plan in user.work_schedules
        ],
        "urlaubsanspruch_buchungen": [
            {
                "jahr": item.year, "tage": item.days, "art": item.kind,
                "begruendung": item.reason, "verfaellt_am": _stamp(item.expires_on),
                "angelegt_am": _stamp(item.created_at),
            }
            for item in user.vacation_entitlement_entries
        ],
        "kalenderfeeds": [
            {
                "id": feed.id, "umfang": feed.scope, "aktiv": feed.active,
                "angelegt_am": _stamp(feed.created_at), "widerrufen_am": _stamp(feed.revoked_at),
            }
            for feed in db.query(models.CalendarFeed).filter(models.CalendarFeed.user_id == user.id).all()
        ],
        "zugriffe_auf_diese_daten": [
            {
                "zeitpunkt": _stamp(access.accessed_at),
                "durch": access.actor_label,
                "bereich": access.scope,
                "detail": access.detail,
            }
            for access in accesses
        ],
    }


__all__ = [
    "DEFAULT_ACCESS_LOG_MONTHS",
    "DEFAULT_REVISION_MONTHS",
    "DEFAULT_TIME_ENTRY_MONTHS",
    "RetentionPolicy",
    "load_policy",
    "purge_access_log",
    "retention_report",
    "save_policy",
    "subject_export",
]
