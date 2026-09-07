"""Business-neutral ingestion service for physical terminal events."""

from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import crud, logging_setup, models
from .integrations.terminals.zkteco_sc800 import AttendanceEvent


def fingerprint(terminal_id: int, event: AttendanceEvent) -> str:
    stable = "\x1f".join((str(terminal_id), event.external_event_id,
        event.user_identifier, event.timestamp.isoformat(), event.status,
        event.verify_mode, event.work_code))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _resolve_user(db: Session, terminal_id: int, event: AttendanceEvent):
    identity = (db.query(models.TerminalIdentity)
        .filter(models.TerminalIdentity.terminal_id == terminal_id)
        .filter(models.TerminalIdentity.external_user_id == event.user_identifier).first())
    if identity:
        return identity.user
    if event.card_identifier:
        card = (db.query(models.TerminalCard)
            .filter(models.TerminalCard.terminal_id == terminal_id)
            .filter(models.TerminalCard.card_identifier == event.card_identifier)
            .filter(models.TerminalCard.active.is_(True)).first())
        return card.identity.user if card else None
    return None


def ingest(db: Session, terminal: models.Terminal, event: AttendanceEvent) -> tuple[models.TerminalEvent, bool]:
    """Persist and process once, using the same running-entry primitives as `/punch`."""
    digest = fingerprint(terminal.id, event)
    existing = (db.query(models.TerminalEvent)
        .filter(models.TerminalEvent.terminal_id == terminal.id)
        .filter(models.TerminalEvent.fingerprint == digest).first())
    if existing:
        logging_setup.log_terminal(f"terminal.event.duplicate terminal_id={terminal.id}")
        return existing, True
    record = models.TerminalEvent(
        terminal_id=terminal.id, external_event_id=event.external_event_id or None,
        fingerprint=digest, user_identifier=event.user_identifier or None,
        card_identifier=event.card_identifier or None, event_timestamp=event.timestamp,
        event_type="toggle", verify_mode=event.verify_mode or None,
        work_code=event.work_code or None, raw_payload=event.raw_line[:2000],
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return (db.query(models.TerminalEvent)
            .filter(models.TerminalEvent.terminal_id == terminal.id,
                    models.TerminalEvent.fingerprint == digest).one()), True
    db.refresh(record)
    if not terminal.active or terminal.enrollment_status != "approved":
        record.processing_status = "terminal_disabled"
        record.error = "Terminal ist nicht freigegeben oder deaktiviert."
    else:
        user = _resolve_user(db, terminal.id, event)
        if user is None:
            record.processing_status = "unknown_user"
            record.error = "Keine Mitarbeiterzuordnung vorhanden."
        elif not user.is_active:
            record.processing_status = "inactive_user"
            record.error = "Mitarbeiter ist deaktiviert."
        else:
            try:
                ZoneInfo(terminal.timezone or "Europe/Berlin")
                active = crud.get_open_time_entry(db, user.id)
                if active:
                    record.time_entry_id = crud.finish_running_entry(db, active, event.timestamp).id
                else:
                    entry = crud.start_running_entry(db, user_id=user.id, started_at=event.timestamp)
                    entry.source = "terminal"
                    entry.external_id = f"{terminal.id}:{digest}"
                    db.commit()
                    record.time_entry_id = entry.id
                record.processing_status = "processed"
            except (ValueError, ZoneInfoNotFoundError) as exc:
                db.rollback()
                record = db.get(models.TerminalEvent, record.id)
                record.processing_status = "failed"
                record.error = str(exc)[:500]
    db.commit()
    db.refresh(record)
    logging_setup.log_terminal(
        f"terminal.event.{record.processing_status} terminal_id={terminal.id} event_id={record.id}"
    )
    return record, False
