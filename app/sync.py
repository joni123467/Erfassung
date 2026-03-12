from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import crud, models


@dataclass
class OperationResult:
    operation_id: str
    status: str
    message: str = ""
    server_entry_id: int | None = None


def _normalize_notes(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def apply_punch_operation(db: Session, user: models.User, operation: dict[str, Any]) -> OperationResult:
    operation_id = str(operation.get("operation_id") or "")
    payload = operation.get("payload") if isinstance(operation.get("payload"), dict) else {}
    action = str(payload.get("action") or "")
    company_id = payload.get("company_id")
    notes = _normalize_notes(payload.get("notes"))
    now = datetime.utcnow()

    active_entry = crud.get_open_time_entry(db, user.id)

    if action == "start_work":
        if active_entry:
            return OperationResult(operation_id, "conflict", "Arbeitszeit läuft bereits.")
        entry = crud.start_running_entry(db, user_id=user.id, started_at=now, notes=notes)
        return OperationResult(operation_id, "synced", server_entry_id=entry.id)

    if action == "end_work":
        if not active_entry:
            return OperationResult(operation_id, "conflict", "Keine laufende Arbeitszeit vorhanden.")
        crud.finish_running_entry(db, active_entry, now)
        return OperationResult(operation_id, "synced", server_entry_id=active_entry.id)

    if action == "start_break":
        if not active_entry:
            return OperationResult(operation_id, "conflict", "Keine laufende Arbeitszeit vorhanden.")
        if active_entry.break_started_at:
            return OperationResult(operation_id, "conflict", "Pause läuft bereits.")
        crud.start_break(db, active_entry, now)
        return OperationResult(operation_id, "synced", server_entry_id=active_entry.id)

    if action == "end_break":
        if not active_entry:
            return OperationResult(operation_id, "conflict", "Keine laufende Arbeitszeit vorhanden.")
        if not active_entry.break_started_at:
            return OperationResult(operation_id, "conflict", "Keine laufende Pause vorhanden.")
        crud.end_break(db, active_entry, now)
        return OperationResult(operation_id, "synced", server_entry_id=active_entry.id)

    if action == "start_company":
        target_company = None
        if company_id not in (None, "", "null"):
            try:
                target_company = crud.get_company(db, int(company_id))
            except (TypeError, ValueError):
                target_company = None
        if not target_company:
            return OperationResult(operation_id, "conflict", "Firma nicht gefunden.")
        if active_entry and active_entry.company_id == target_company.id:
            return OperationResult(operation_id, "conflict", "Auftrag läuft bereits.")
        if active_entry:
            crud.finish_running_entry(db, active_entry, now)
        entry = crud.start_running_entry(
            db,
            user_id=user.id,
            started_at=now,
            company_id=target_company.id,
            notes=notes,
        )
        return OperationResult(operation_id, "synced", server_entry_id=entry.id)

    if action == "end_company":
        if not active_entry or active_entry.company_id is None:
            return OperationResult(operation_id, "conflict", "Kein laufender Auftrag vorhanden.")
        crud.finish_running_entry(db, active_entry, now)
        entry = crud.start_running_entry(db, user_id=user.id, started_at=now, notes=notes)
        return OperationResult(operation_id, "synced", server_entry_id=entry.id)

    return OperationResult(operation_id, "failed", "Unbekannte Aktion.")
