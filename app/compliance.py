"""Regelprüfung nach ArbZG und ArbSchG – kennzeichnen statt verhindern.

Der Leitgedanke dieses Moduls steht in einem Satz:

    **Die tatsächlich geleistete Arbeitszeit wird immer gespeichert.**

Eine Überschreitung der Höchstarbeitszeit, eine zu kurze Ruhezeit oder eine
fehlende Pause sind Tatsachen. Sie zu verschweigen oder die Buchung abzulehnen
würde den Nachweis verfälschen – und genau den verlangen §16 Abs. 2 ArbZG,
§17 MiLoG und die Rechtsprechung zur Arbeitszeiterfassung. Deshalb wird hier
nichts blockiert, sondern gekennzeichnet, damit es auffällt und bearbeitet
werden kann.

Geprüft wird:

* **§3 ArbZG** – mehr als 8 Stunden werktäglich (zulässig bei Ausgleich, daher
  Hinweis) und mehr als 10 Stunden (absolute Grenze, daher kritisch).
* **§4 ArbZG** – fehlende Ruhepause. Grenzen und Mindestabschnitt stehen in
  :mod:`app.models`.
* **§5 ArbZG** – weniger als 11 Stunden Ruhezeit zwischen zwei Arbeitstagen.
* **§9 ArbZG** – Arbeit an Sonn- und Feiertagen.

Keine dieser Kennzeichnungen ist eine rechtliche Bewertung des Einzelfalls:
Ausnahmen (Tarifverträge, §7 ArbZG, §10 ArbZG, Bereitschaft) kann eine Software
nicht kennen. Sie zeigt, was auffällt; entscheiden müssen Menschen.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from . import models

LOGGER = logging.getLogger("erfassung.application")

#: Schweregrade – steuern ausschließlich die Darstellung.
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

LABELS: dict[str, str] = {
    models.ComplianceCode.OVER_8H: "Mehr als 8 Stunden",
    models.ComplianceCode.OVER_10H: "Mehr als 10 Stunden",
    models.ComplianceCode.REST_UNDER_11H: "Ruhezeit unter 11 Stunden",
    models.ComplianceCode.BREAK_MISSING: "Ruhepause fehlt",
    models.ComplianceCode.SUNDAY_WORK: "Sonntagsarbeit",
    models.ComplianceCode.HOLIDAY_WORK: "Feiertagsarbeit",
}

REFERENCES: dict[str, str] = {
    models.ComplianceCode.OVER_8H: "§3 ArbZG",
    models.ComplianceCode.OVER_10H: "§3 ArbZG",
    models.ComplianceCode.REST_UNDER_11H: "§5 ArbZG",
    models.ComplianceCode.BREAK_MISSING: "§4 ArbZG",
    models.ComplianceCode.SUNDAY_WORK: "§9 ArbZG",
    models.ComplianceCode.HOLIDAY_WORK: "§9 ArbZG",
}


def _format_minutes(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d} Std"


def _entry_bounds(entry: models.TimeEntry) -> tuple[datetime, datetime]:
    """Beginn und Ende als Zeitpunkte – Ende ggf. am Folgetag.

    Die UTC-Stempel haben Vorrang, wenn sie gepflegt sind; sonst wird aus
    ``work_date`` und den Ortszeiten zusammengesetzt. So funktioniert die
    Prüfung für Bestandsbuchungen genauso wie für neue.
    """
    start = datetime.combine(entry.work_date, entry.start_time or time(0, 0))
    if entry.is_open or entry.end_time is None:
        now = datetime.now()
        end = datetime.combine(now.date(), now.time())
    else:
        end = datetime.combine(entry.work_date, entry.end_time)
    if end < start:
        end += timedelta(days=1)
    return start, end


def _countable(entries: Iterable[models.TimeEntry]) -> list[models.TimeEntry]:
    """Buchungen, die für die Bewertung zählen.

    Stornierte bleiben außen vor: Sie sind rückgängig gemacht und würden sonst
    einen Verstoß vortäuschen, den es nicht gab.
    """
    return [
        entry for entry in entries
        if entry.status != models.TimeEntryStatus.CANCELLED
    ]


def evaluate_day(
    db: Session,
    user_id: int,
    work_date: date,
    *,
    holiday_dates: Optional[set[date]] = None,
) -> list[dict[str, object]]:
    """Alle Kennzeichnungen eines Arbeitstags ermitteln.

    Gibt einfache Wörterbücher zurück statt Datenbankobjekte – so lässt sich
    die Bewertung ohne Schreibzugriff prüfen und testen.
    """
    entries = _countable(
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.work_date == work_date)
        .order_by(models.TimeEntry.start_time)
        .all()
    )
    if not entries:
        return []

    findings: list[dict[str, object]] = []
    total = sum(entry.worked_minutes for entry in entries)

    if total > models.ABSOLUTE_MAX_DAILY_MINUTES:
        findings.append({
            "code": models.ComplianceCode.OVER_10H,
            "severity": SEVERITY_CRITICAL,
            "entry_id": entries[-1].id,
            "detail": (
                f"{_format_minutes(total)} gearbeitet – über der Höchstgrenze von "
                f"{_format_minutes(models.ABSOLUTE_MAX_DAILY_MINUTES)}."
            ),
        })
    elif total > models.MAX_DAILY_MINUTES:
        findings.append({
            "code": models.ComplianceCode.OVER_8H,
            "severity": SEVERITY_WARNING,
            "entry_id": entries[-1].id,
            "detail": (
                f"{_format_minutes(total)} gearbeitet. Über 8 Stunden ist nur zulässig, "
                "wenn innerhalb von 6 Monaten auf 8 Stunden ausgeglichen wird."
            ),
        })

    # Pausen werden je Buchung bewertet: Zwei getrennte Buchungen sind zwei
    # Arbeitsabschnitte, und der Fehlbetrag der längeren geht sonst unter.
    for entry in entries:
        shortfall = entry.break_shortfall_minutes
        if shortfall > 0:
            findings.append({
                "code": models.ComplianceCode.BREAK_MISSING,
                "severity": SEVERITY_WARNING,
                "entry_id": entry.id,
                "detail": (
                    f"{shortfall} Minuten Ruhepause fehlen "
                    f"({_format_minutes(entry.gross_minutes)} Anwesenheit, "
                    f"{entry.countable_break_minutes} Minuten anrechenbare Pause)."
                ),
            })

    if work_date.weekday() == 6:
        findings.append({
            "code": models.ComplianceCode.SUNDAY_WORK,
            "severity": SEVERITY_INFO,
            "entry_id": entries[0].id,
            "detail": f"{_format_minutes(total)} an einem Sonntag.",
        })
    if holiday_dates is None:
        holiday_dates = _holiday_dates(db, work_date.year)
    if work_date in holiday_dates:
        findings.append({
            "code": models.ComplianceCode.HOLIDAY_WORK,
            "severity": SEVERITY_INFO,
            "entry_id": entries[0].id,
            "detail": f"{_format_minutes(total)} an einem Feiertag.",
        })

    rest = _rest_finding(db, user_id, work_date, entries)
    if rest:
        findings.append(rest)
    return findings


def _rest_finding(
    db: Session,
    user_id: int,
    work_date: date,
    entries: list[models.TimeEntry],
) -> Optional[dict[str, object]]:
    """Ruhezeit zum vorherigen Arbeitstag prüfen (§5 ArbZG).

    Verglichen wird das späteste Ende der Vortage mit dem frühesten Beginn
    dieses Tages. Zwei Tage zurück, damit eine Nachtschicht, die erst am
    Folgetag endet, nicht übersehen wird.
    """
    starts = [_entry_bounds(entry)[0] for entry in entries]
    if not starts:
        return None
    first_start = min(starts)

    previous = _countable(
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.work_date < work_date)
        .filter(models.TimeEntry.work_date >= work_date - timedelta(days=2))
        .all()
    )
    ends = [_entry_bounds(entry)[1] for entry in previous]
    ends = [end for end in ends if end <= first_start]
    if not ends:
        return None
    last_end = max(ends)
    rest_minutes = int((first_start - last_end).total_seconds() // 60)
    if rest_minutes >= models.MIN_REST_MINUTES:
        return None
    return {
        "code": models.ComplianceCode.REST_UNDER_11H,
        "severity": SEVERITY_CRITICAL,
        "entry_id": entries[0].id,
        "detail": (
            f"Nur {_format_minutes(max(rest_minutes, 0))} Ruhezeit seit "
            f"{last_end.strftime('%d.%m.%Y %H:%M')} – vorgeschrieben sind 11 Stunden."
        ),
    }


def _holiday_dates(db: Session, year: int) -> set[date]:
    from . import crud

    try:
        region = crud.get_default_holiday_region(db)
        return {holiday.date for holiday in crud.get_holidays_for_year(db, year, region)}
    except Exception:  # pragma: no cover - die Prüfung darf nie eine Buchung kippen
        return set()


def refresh_day(db: Session, user_id: int, work_date: date) -> list[models.ComplianceFlag]:
    """Kennzeichnungen eines Tages neu berechnen und speichern.

    Offene (unbestätigte) Kennzeichnungen werden ersetzt, bestätigte bleiben
    stehen: Wer einen Verstoß eingeordnet hat, soll das nicht bei jeder
    Nachbuchung erneut tun müssen.

    Fehler werden protokolliert und geschluckt – eine Stempelung darf nie an
    der Regelprüfung scheitern.
    """
    try:
        findings = evaluate_day(db, user_id, work_date)
        existing = (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.user_id == user_id)
            .filter(models.ComplianceFlag.work_date == work_date)
            .all()
        )
        acknowledged = {flag.code for flag in existing if flag.acknowledged_at is not None}
        for flag in existing:
            if flag.acknowledged_at is None:
                db.delete(flag)
        db.flush()

        created: list[models.ComplianceFlag] = []
        for finding in findings:
            if finding["code"] in acknowledged:
                continue
            flag = models.ComplianceFlag(
                user_id=user_id,
                entry_id=finding.get("entry_id"),
                work_date=work_date,
                code=str(finding["code"]),
                severity=str(finding["severity"]),
                detail=str(finding["detail"])[:500],
            )
            db.add(flag)
            created.append(flag)
        db.commit()
        return created
    except Exception as exc:  # pragma: no cover - defensiv
        db.rollback()
        LOGGER.warning("Regelprüfung für %s am %s fehlgeschlagen: %s", user_id, work_date, exc)
        return []


def refresh_for_entry(db: Session, entry: models.TimeEntry) -> None:
    """Nach jeder Änderung an einer Buchung deren Tag neu bewerten.

    Zusätzlich der Folgetag: Eine Buchung verändert die Ruhezeit *davor* – die
    steht aber am nächsten Arbeitstag.
    """
    if entry is None or entry.user_id is None or entry.work_date is None:
        return
    refresh_day(db, entry.user_id, entry.work_date)
    for offset in (1, 2):
        following = entry.work_date + timedelta(days=offset)
        has_entries = (
            db.query(models.TimeEntry.id)
            .filter(models.TimeEntry.user_id == entry.user_id)
            .filter(models.TimeEntry.work_date == following)
            .first()
        )
        if has_entries:
            refresh_day(db, entry.user_id, following)


def open_flags(
    db: Session,
    *,
    user_ids: Optional[Iterable[int]] = None,
    since: Optional[date] = None,
    limit: int = 200,
) -> list[models.ComplianceFlag]:
    """Offene Kennzeichnungen – für die Eskalation in der Administration."""
    query = db.query(models.ComplianceFlag).filter(
        models.ComplianceFlag.acknowledged_at.is_(None)
    )
    if user_ids is not None:
        ids = list(user_ids)
        if not ids:
            return []
        query = query.filter(models.ComplianceFlag.user_id.in_(ids))
    if since is not None:
        query = query.filter(models.ComplianceFlag.work_date >= since)
    return (
        query.order_by(
            models.ComplianceFlag.work_date.desc(), models.ComplianceFlag.id.desc()
        )
        .limit(limit)
        .all()
    )


def acknowledge(
    db: Session, flag_id: int, *, user: models.User, note: str
) -> Optional[models.ComplianceFlag]:
    """Eine Kennzeichnung einordnen. Die Begründung ist Pflicht.

    Bestätigen heißt nicht „erledigt", sondern „gesehen und bewertet" – der
    Verstoß selbst bleibt für die Prüfung erhalten.
    """
    flag = db.query(models.ComplianceFlag).filter(models.ComplianceFlag.id == flag_id).first()
    if flag is None:
        return None
    cleaned = (note or "").strip()
    if not cleaned:
        raise ValueError("REASON_REQUIRED")
    flag.acknowledged_at = datetime.utcnow()
    flag.acknowledged_by_id = user.id if user else None
    flag.acknowledgement = cleaned[:500]
    db.commit()
    db.refresh(flag)
    return flag


def label(code: str) -> str:
    return LABELS.get(code, code)


def reference(code: str) -> str:
    return REFERENCES.get(code, "")


__all__ = [
    "LABELS",
    "REFERENCES",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "acknowledge",
    "evaluate_day",
    "label",
    "open_flags",
    "reference",
    "refresh_day",
    "refresh_for_entry",
]
