"""Abschluss- und Korrekturworkflow für Abrechnungsperioden.

Der Ablauf hat vier Zustände:

1. **offen** – normal gearbeitet, alles änderbar.
2. **Mitarbeiterprüfung** – die Zeiten stehen zur Durchsicht. Jede Person
   bestätigt oder widerspricht mit Begründung.
3. **freigegeben** – der Arbeitgeber hat geprüft. Änderungen sind weiterhin
   möglich, solange nicht gesperrt ist.
4. **gesperrt** – abgerechnet. Buchungen dieses Zeitraums lassen sich nicht
   mehr ändern (:func:`app.crud.ensure_period_open`).

Warum die Trennung zwischen *freigegeben* und *gesperrt*: Zwischen Freigabe und
Lohnlauf liegen erfahrungsgemäß Nachfragen. Wer sofort sperrt, macht jede
berechtigte Korrektur unmöglich; wer nie sperrt, hat keinen belastbaren
Abschluss. Beides gibt es hier nacheinander.

Ein Widerspruch sperrt nichts – er ist ein Vermerk, den der Arbeitgeber
beantworten muss. Das Ergebnis bleibt in der Historie.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from . import models

STATUS_LABELS = {
    models.PeriodStatus.OPEN: "offen",
    models.PeriodStatus.REVIEW: "Mitarbeiterprüfung",
    models.PeriodStatus.APPROVED: "freigegeben",
    models.PeriodStatus.LOCKED: "gesperrt",
}

CONFIRMATION_LABELS = {
    models.ConfirmationStatus.PENDING: "offen",
    models.ConfirmationStatus.CONFIRMED: "bestätigt",
    models.ConfirmationStatus.OBJECTED: "Widerspruch",
}


def month_bounds(year: int, month: int) -> tuple[date, date]:
    from calendar import monthrange

    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def get_period(db: Session, period_id: int) -> Optional[models.PayrollPeriod]:
    return (
        db.query(models.PayrollPeriod)
        .filter(models.PayrollPeriod.id == period_id)
        .first()
    )


def list_periods(db: Session, *, limit: int = 36) -> list[models.PayrollPeriod]:
    return (
        db.query(models.PayrollPeriod)
        .order_by(models.PayrollPeriod.period_start.desc())
        .limit(limit)
        .all()
    )


def period_for(db: Session, day: date) -> Optional[models.PayrollPeriod]:
    return (
        db.query(models.PayrollPeriod)
        .filter(models.PayrollPeriod.period_start <= day)
        .filter(models.PayrollPeriod.period_end >= day)
        .first()
    )


def create_period(
    db: Session, *, period_start: date, period_end: date, label: str = ""
) -> models.PayrollPeriod:
    if period_end < period_start:
        raise ValueError("PERIOD_RANGE")
    existing = (
        db.query(models.PayrollPeriod)
        .filter(models.PayrollPeriod.period_start == period_start)
        .filter(models.PayrollPeriod.period_end == period_end)
        .first()
    )
    if existing:
        return existing
    period = models.PayrollPeriod(
        period_start=period_start,
        period_end=period_end,
        label=(label or f"{period_start:%m/%Y}")[:64],
        status=models.PeriodStatus.OPEN,
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


def start_review(
    db: Session, period: models.PayrollPeriod, *, user_ids: Iterable[int]
) -> models.PayrollPeriod:
    """Zur Mitarbeiterprüfung stellen und für jede Person einen Eintrag anlegen."""
    period.status = models.PeriodStatus.REVIEW
    period.review_started_at = datetime.utcnow()
    known = {item.user_id for item in period.confirmations}
    for user_id in user_ids:
        if user_id in known:
            continue
        db.add(models.PeriodConfirmation(
            period_id=period.id,
            user_id=user_id,
            status=models.ConfirmationStatus.PENDING,
        ))
    db.commit()
    db.refresh(period)
    return period


def submit_confirmation(
    db: Session,
    period: models.PayrollPeriod,
    user: models.User,
    *,
    confirmed: bool,
    note: str = "",
) -> models.PeriodConfirmation:
    """Bestätigung oder Widerspruch einer Person.

    Ein Widerspruch **braucht** eine Begründung – ohne sie wüsste niemand, was
    zu prüfen ist.
    """
    cleaned = (note or "").strip()
    if not confirmed and not cleaned:
        raise ValueError("REASON_REQUIRED")
    record = (
        db.query(models.PeriodConfirmation)
        .filter(models.PeriodConfirmation.period_id == period.id)
        .filter(models.PeriodConfirmation.user_id == user.id)
        .first()
    )
    if record is None:
        record = models.PeriodConfirmation(period_id=period.id, user_id=user.id)
        db.add(record)
    record.status = (
        models.ConfirmationStatus.CONFIRMED if confirmed
        else models.ConfirmationStatus.OBJECTED
    )
    record.submitted_at = datetime.utcnow()
    record.note = cleaned[:500]
    db.commit()
    db.refresh(record)
    return record


def respond_to_objection(
    db: Session,
    confirmation: models.PeriodConfirmation,
    *,
    actor: models.User,
    response: str,
) -> models.PeriodConfirmation:
    cleaned = (response or "").strip()
    if not cleaned:
        raise ValueError("REASON_REQUIRED")
    confirmation.response = cleaned[:500]
    confirmation.responded_at = datetime.utcnow()
    confirmation.responded_by_id = actor.id if actor else None
    db.commit()
    db.refresh(confirmation)
    return confirmation


def approve(
    db: Session, period: models.PayrollPeriod, *, actor: models.User
) -> models.PayrollPeriod:
    period.status = models.PeriodStatus.APPROVED
    period.approved_at = datetime.utcnow()
    period.approved_by_id = actor.id if actor else None
    db.commit()
    db.refresh(period)
    return period


def lock(
    db: Session, period: models.PayrollPeriod, *, actor: models.User, note: str = ""
) -> models.PayrollPeriod:
    """Periode sperren. Danach sind Buchungen des Zeitraums unveränderlich."""
    period.status = models.PeriodStatus.LOCKED
    period.locked_at = datetime.utcnow()
    period.locked_by_id = actor.id if actor else None
    if note:
        period.note = note[:500]
    db.commit()
    db.refresh(period)
    return period


def reopen(
    db: Session, period: models.PayrollPeriod, *, actor: models.User, reason: str
) -> models.PayrollPeriod:
    """Sperre aufheben – nur mit Begründung, und der Vorgang bleibt vermerkt.

    Eine Sperre aufzuheben ist ein Eingriff in einen Abschluss. Wer das tut,
    muss sagen warum; der Vermerk bleibt an der Periode stehen.
    """
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ValueError("REASON_REQUIRED")
    stamp = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    who = getattr(actor, "full_name", None) or getattr(actor, "username", "?")
    addition = f"[{stamp}] Sperre aufgehoben von {who}: {cleaned}"
    period.note = (f"{period.note}\n{addition}" if period.note else addition)[:500]
    period.status = models.PeriodStatus.APPROVED
    period.locked_at = None
    period.locked_by_id = None
    db.commit()
    db.refresh(period)
    return period


def open_confirmations(db: Session, user_id: int) -> list[models.PeriodConfirmation]:
    """Perioden, die diese Person noch prüfen soll."""
    return (
        db.query(models.PeriodConfirmation)
        .join(models.PayrollPeriod)
        .filter(models.PeriodConfirmation.user_id == user_id)
        .filter(models.PeriodConfirmation.status == models.ConfirmationStatus.PENDING)
        .filter(models.PayrollPeriod.status == models.PeriodStatus.REVIEW)
        .order_by(models.PayrollPeriod.period_start.desc())
        .all()
    )


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def confirmation_label(status: str) -> str:
    return CONFIRMATION_LABELS.get(status, status)


__all__ = [
    "approve",
    "confirmation_label",
    "create_period",
    "get_period",
    "list_periods",
    "lock",
    "month_bounds",
    "open_confirmations",
    "period_for",
    "reopen",
    "respond_to_objection",
    "start_review",
    "status_label",
    "submit_confirmation",
]
