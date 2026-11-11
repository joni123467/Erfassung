"""Versioniertes Outbox-Protokoll. Empfang, Buchung und Bestätigung sind atomar.

Die vorhandene Fachlogik darf intern commit() aufrufen: eine äußere Transaktion
mit SAVEPOINT-Sitzung hält diese Änderungen bis zur Empfangsbestätigung zurück.
SQLite serialisiert vor dem ersten Lesen; andere Backends sperren den Benutzer.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, database, logging_setup, models, permission_service, worktime

router = APIRouter()
PROTOCOL = 1


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal[1]
    owner_id: int = Field(gt=0)
    client_action_id: str = Field(min_length=1, max_length=191, pattern=r"^[\w.-]+$")
    kind: Literal["punch", "vacation"]
    payload: dict[str, str] = Field(max_length=30)


def authenticated(request: Request, db: Session) -> models.User:
    from . import main
    user = main.get_logged_in_user(request, db)
    if not user or user.must_change_password:
        raise HTTPException(401, "Bitte erneut anmelden bzw. das Kennwort ändern. Buchungen bleiben erhalten.")
    return user


@contextmanager
def transaction(user_id: int):
    with database.engine.connect() as connection:
        if database.IS_SQLITE:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.begin()
        try:
            if not database.IS_SQLITE:
                connection.execute(select(models.User.id).where(models.User.id == user_id).with_for_update())
            with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as db:
                yield db, connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def result(row: models.MobileSyncReceipt, *, duplicate=False) -> dict:
    return {
        "protocol": PROTOCOL, "owner_id": row.user_id,
        "client_action_id": row.client_action_id, "received": True,
        "receipt_id": row.id, "status": row.status,
        "ok": row.status == "applied", "duplicate": duplicate,
        "message": row.message, "resolution_note": row.resolution_note or "",
    }


def _request_for(request: Request, user_id: int) -> Request:
    scope = dict(request.scope)
    scope["session"] = {**request.session, "user_id": user_id}
    scope["headers"] = [(key, value) for key, value in scope["headers"] if key.lower() != b"accept"]
    scope["headers"].append((b"accept", b"application/json"))
    return Request(scope)


def _event_time(payload: dict) -> datetime:
    try:
        value = datetime.fromisoformat(payload["event_time"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        raise ValueError("Der ursprüngliche Buchungszeitpunkt fehlt oder ist ungültig.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=worktime.zone())
    utc = value.astimezone(timezone.utc)
    if not datetime.now(timezone.utc) - timedelta(days=400) <= utc <= datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("Buchungszeitpunkt außerhalb des zulässigen Zeitfensters. Bitte prüfen.")
    return value.astimezone(worktime.zone())


def _apply(request: Request, action: Action, db: Session) -> dict:
    """Nur deklarierte Formularfelder übernehmen; keine Session/Benutzer aus Payload."""
    from . import main
    payload = dict(action.payload)
    payload["client_action_id"] = action.client_action_id
    if action.kind == "punch":
        moment = _event_time(payload)
        payload["event_time"] = moment.isoformat()
        current = crud.get_open_time_entry(db, action.owner_id)
        _check_expected_state(payload, current)
        if current:
            started, _ = worktime.entry_bounds(current)
            if moment.astimezone(timezone.utc) < started:
                raise ValueError("Offline-Buchung liegt vor der aktuell laufenden Buchung.")
            if payload.get("action") == "start_work":
                raise ValueError("Es läuft bereits eine andere Arbeitszeit. Bitte den Offline-Start prüfen.")
            if payload.get("action") == "start_company" and str(current.company_id) == payload.get("company_id"):
                raise ValueError("Dieser Auftrag läuft bereits. Bitte den Offline-Start prüfen.")
        if payload.get("action") == "correct_end_work":
            return _correct_end_work(action, current, moment, db)
        handler = main.punch_action
    else:
        if not main.has_license_feature("vacation"):
            raise ValueError("Urlaubsplanung ist nicht lizenziert. Antrag bleibt zur Prüfung erhalten.")
        handler = main.submit_vacation
        for key in ("start_date", "end_date"):
            try:
                payload[key] = date.fromisoformat(payload[key])
            except (KeyError, ValueError):
                raise ValueError("Ungültiger Zeitraum des Urlaubsantrags.")
    kwargs = {}
    for name, parameter in inspect.signature(handler).parameters.items():
        if name in ("request", "db"):
            continue
        if name in payload:
            kwargs[name] = payload[name]
        else:
            default = getattr(parameter.default, "default", None)
            kwargs[name] = default if default is not ... else None
    response = handler(request=_request_for(request, action.owner_id), db=db, **kwargs)
    if response.status_code != 200:
        raise ValueError("Buchung konnte nicht angewendet werden. Bitte Berechtigungen prüfen.")
    return json.loads(response.body)


def _check_expected_state(payload: dict, current: models.TimeEntry | None) -> None:
    """Geräte vergleichen ihren bekannten Zustand unter derselben Benutzersperre."""
    expected_state = payload.get("expected_state")
    if expected_state is None:
        return  # Bereits gespeicherte Ereignisse älterer Clients bleiben lesbar.
    if expected_state not in {"idle", "working", "break"}:
        raise ValueError("Ungültiger Buchungsstand. Bitte die Übersicht aktualisieren.")
    actual = "idle" if current is None else "break" if current.break_started_at else "working"
    changed = actual != expected_state
    if current is not None and not changed:
        try:
            expected = datetime.fromisoformat(payload["expected_started_at"].replace("Z", "+00:00"))
            if expected.tzinfo is None:
                raise ValueError
        except (KeyError, ValueError):
            raise ValueError("Der Bezug zur laufenden Buchung fehlt. Bitte die Übersicht aktualisieren.")
        started, _ = worktime.entry_bounds(current)
        changed = expected.astimezone(timezone.utc).replace(microsecond=0) != started.replace(microsecond=0)
        expected_id = payload.get("expected_entry_id")
        changed = changed or bool(expected_id and expected_id != str(current.id))
        if actual == "break" and current.running_break:
            try:
                expected_break = datetime.fromisoformat(payload["expected_break_started_at"].replace("Z", "+00:00"))
                if expected_break.tzinfo is None:
                    raise ValueError
            except (KeyError, ValueError):
                raise ValueError("Der Bezug zur laufenden Pause fehlt. Bitte die Übersicht aktualisieren.")
            break_start = worktime.from_utc_column(current.running_break.started_at_utc)
            changed = changed or expected_break.astimezone(timezone.utc).replace(microsecond=0) != break_start.replace(microsecond=0)
    if changed:
        raise ValueError("Der Buchungsstand wurde inzwischen geändert, möglicherweise auf einem anderen Gerät. Bitte vorhandene Buchungen prüfen; diese Aktion wurde nicht auf eine andere Buchung angewendet.")


def _correct_end_work(action: Action, current: models.TimeEntry | None, moment: datetime, db: Session) -> dict:
    """Ein vergessenes Ende nur an der ausdrücklich geprüften offenen Buchung ergänzen."""
    from . import compliance
    if current is None:
        raise ValueError("Die zu korrigierende Arbeitszeit läuft nicht mehr. Bitte vorhandene Buchungen prüfen.")
    reason = action.payload.get("correction_reason", "").strip()
    if not reason or len(reason) > 2000:
        raise ValueError("Bitte eine Begründung für das nachgetragene Arbeitsende angeben (maximal 2000 Zeichen).")
    try:
        expected = datetime.fromisoformat(action.payload["expected_started_at"].replace("Z", "+00:00"))
        if expected.tzinfo is None:
            raise ValueError
    except (KeyError, ValueError):
        raise ValueError("Der Beginn der zu korrigierenden Arbeitszeit fehlt. Bitte Buchung prüfen.")
    started, _ = worktime.entry_bounds(current)
    expected_id = action.payload.get("entry_id")
    if (expected_id and expected_id != str(current.id)) or expected.astimezone(timezone.utc).replace(microsecond=0) != started.replace(microsecond=0):
        raise ValueError("Inzwischen läuft eine andere Buchung. Das nachgetragene Ende wird nicht darauf angewendet.")
    ended = moment.astimezone(timezone.utc)
    if ended <= started or ended > datetime.now(timezone.utc):
        raise ValueError("Das tatsächliche Ende muss nach dem Beginn und darf nicht in der Zukunft liegen.")
    for interval in current.breaks:
        last = interval.ended_at_utc or interval.started_at_utc
        if last and worktime.from_utc_column(last) > ended:
            raise ValueError("Nach dem angegebenen Ende ist eine Pause erfasst. Bitte zuerst die Pausenzeiten prüfen.")
    if current.break_started_at and not current.running_break:
        # Altbestand ohne Pausenintervalle lässt sich hier nicht eindeutig kürzen.
        raise ValueError("Eine laufende Pause muss vor der Korrektur geprüft werden.")
    owner = db.get(models.User, action.owner_id)
    crud.finish_running_entry(db, current, moment, actor=owner, reason=reason)
    compliance.refresh_for_entry(db, current)
    crud.create_mobile_sync_action(db, user_id=action.owner_id,
                                  client_action_id=action.client_action_id, action="correct_end_work")
    return {"ok": True, "message": "Arbeitszeit mit dem angegebenen tatsächlichen Ende abgeschlossen."}


def _attempt(request: Request, action: Action, db: Session, connection) -> dict:
    # Alle Teilbuchungen (z.B. Auftrag beenden + nächsten starten) zurückrollen,
    # wenn irgendein Teil scheitert. Der Konflikt wird danach separat persistiert.
    db.info["mobile_atomic"] = True
    db.commit()
    savepoint = connection.begin_nested()
    try:
        response = _apply(request, action, db)
        db.commit()
    except (ValueError, crud.PeriodLocked) as exc:
        db.rollback()
        response = {"ok": False, "message": str(exc)}
    except BaseException:
        db.rollback()
        if savepoint.is_active:
            savepoint.rollback()
        raise
    if response.get("ok"):
        savepoint.commit()
    else:
        savepoint.rollback()
    db.expire_all()
    return response


def _digest(kind: str, payload: dict) -> str:
    # Empty/default form fields are equivalent across old HTML and protocol 1.
    values = {key: str(value) for key, value in payload.items()
              if value not in (None, "") and key not in {"csrf_token", "next_url", "client_action_id"}}
    if kind == "vacation":
        values.setdefault("absence_type_key", "vacation")
    return hashlib.sha256((kind + json.dumps(values, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def legacy_action(request: Request, previous_db: Session, handler, arguments: dict):
    """Alte Clients: auch abgewiesene Ereignisse vor ihrer fehlerhaften Löschung sichern."""
    from . import main
    from urllib.parse import parse_qs, urlsplit
    user = main.get_logged_in_user(request, previous_db)
    if not user:
        return main._auth_required_response(request)
    user_id = user.id
    previous_db.rollback()
    kind = "punch" if handler is main.punch_action else "vacation"
    payload = {key: value.isoformat() if isinstance(value, date) else value for key, value in arguments.items()
               if value is not None and key not in {"client_action_id", "next_url"}}
    digest = _digest(kind, payload)
    client_id = arguments["client_action_id"]
    if len(client_id) > 191:
        raise HTTPException(422, "Aktions-ID zu lang")
    target = main._sanitize_next(arguments.get("next_url", "/records/vacations"))
    with transaction(user_id) as (db, connection):
        db.info["mobile_atomic"] = True
        row = db.query(models.MobileSyncReceipt).filter_by(user_id=user_id, client_action_id=client_id).first()
        if row:
            if row.payload_hash != digest:
                raise HTTPException(409, "Aktions-ID gehört zu anderen Buchungsdaten")
            return main._sync_result(request, target=target,
                                     message=row.message if row.status != "conflict" else "",
                                     error=row.message if row.status == "conflict" else "",
                                     duplicate=row.status == "applied", retryable=row.status == "conflict")
        db.commit()
        savepoint = connection.begin_nested()
        response = handler(request=request, db=db, **arguments)
        db.commit()
        failed = response.status_code >= 400
        message = ""
        if isinstance(response, JSONResponse):
            body = json.loads(response.body)
            failed = failed or not body.get("ok")
            message = body.get("message", "")
        elif isinstance(response, RedirectResponse):
            params = parse_qs(urlsplit(response.headers["location"]).query)
            failed = failed or "error" in params
            message = (params.get("error") or params.get("msg") or [""])[0]
        if failed:
            savepoint.rollback()
        else:
            savepoint.commit()
        db.expire_all()
        db.add(models.MobileSyncReceipt(user_id=user_id, client_action_id=client_id, kind=kind,
               payload_json=json.dumps(payload, ensure_ascii=False), payload_hash=digest,
               status="conflict" if failed else "applied", message=message))
        db.commit()
    logging_setup.log_sync(f"Legacy-Offline-Ereignis {client_id}: {'conflict' if failed else 'applied'}", user=user_id)
    return response


def receive(request: Request, action: Action) -> dict:
    if any(len(value) > 8000 for value in action.payload.values()):
        raise HTTPException(422, "Buchungsdaten zu groß")
    # Transportfelder gehören nicht zum unveränderlichen Ereignis.
    payload = {key: value for key, value in action.payload.items() if key not in {"csrf_token", "next_url", "client_action_id"}}
    action = action.model_copy(update={"payload": payload})
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = _digest(action.kind, payload)
    with transaction(action.owner_id) as (db, connection):
        row = db.query(models.MobileSyncReceipt).filter_by(user_id=action.owner_id, client_action_id=action.client_action_id).first()
        if row:
            if row.payload_hash != digest:
                raise HTTPException(409, "Diese Aktions-ID gehört zu anderen Buchungsdaten. Original erhalten.")
            return result(row, duplicate=True)
        legacy = crud.get_mobile_sync_action(db, action.owner_id, action.client_action_id)
        response = {"ok": True, "message": "Bereits verbucht"} if legacy else _attempt(request, action, db, connection)
        row = models.MobileSyncReceipt(
            user_id=action.owner_id, client_action_id=action.client_action_id,
            kind=action.kind, payload_json=encoded, payload_hash=digest,
            status="applied" if response.get("ok") else "conflict",
            message=response.get("message", "Bitte prüfen"),
        )
        db.add(row)
        db.commit()
        answer = result(row)
    logging_setup.log_sync(f"Offline-Ereignis {action.client_action_id}: {answer['status']}", user=action.owner_id)
    return answer


@router.get("/api/mobile/session")
def session_info(request: Request, db: Session = Depends(database.get_db)):
    from . import main
    user = authenticated(request, db)
    return JSONResponse({"protocol": PROTOCOL, "user": {"id": user.id, "name": user.full_name,
                                                      "overview_preference": user.overview_preference},
                         "permissions": {"admin_access": main.has_admin_access(user), "account_access": True},
                         "csrf_token": main.get_csrf_token(request), "version": main.APP_VERSION},
                        headers={"Cache-Control": "no-store"})


@router.post("/api/mobile/actions")
def accept_action(request: Request, action: Action, db: Session = Depends(database.get_db)):
    user = authenticated(request, db)
    if action.owner_id != user.id:
        raise HTTPException(403, "Diese Buchungen gehören zu einem anderen Konto.")
    db.rollback()  # Lesetransaktion vor der Schreibsperre freigeben.
    return JSONResponse(receive(request, action), headers={"Cache-Control": "no-store"})


@router.get("/admin/sync-conflicts")
def conflicts(request: Request, db: Session = Depends(database.get_db)):
    from . import main
    user = authenticated(request, db)
    if not permission_service.has(user, "Time.Sync.Resolve"):
        raise HTTPException(403, "Recht zur Konfliktfreigabe fehlt")
    query = db.query(models.MobileSyncReceipt)
    allowed = permission_service.allowed_user_ids(db, user, "Time.Sync.Resolve")
    if allowed is not None:
        query = query.filter(models.MobileSyncReceipt.user_id.in_(allowed))
    rows = query.filter(models.MobileSyncReceipt.status == "conflict").order_by(models.MobileSyncReceipt.id).all()
    history = query.filter(models.MobileSyncReceipt.resolved_at.isnot(None)).order_by(models.MobileSyncReceipt.resolved_at.desc()).limit(50).all()
    return main._admin_template("admin/sync_conflicts.html", request, user, rows=rows, history=history,
                                payloads={row.id: json.loads(row.payload_json) for row in rows},
                                message=request.query_params.get("msg"), error=request.query_params.get("error"))


@router.post("/admin/sync-conflicts/{receipt_id}")
def resolve(request: Request, receipt_id: int, decision: str = Form(...), reason: str = Form(...),
            event_time: str = Form(""), db: Session = Depends(database.get_db)):
    from . import main
    reviewer = authenticated(request, db)
    row = db.get(models.MobileSyncReceipt, receipt_id)
    if not row:
        raise HTTPException(404, "Vorgang nicht gefunden")
    if not permission_service.can_access_user(db, reviewer, "Time.Sync.Resolve", row.user_id):
        raise HTTPException(403, "Recht zur Konfliktfreigabe für diesen Benutzer fehlt")
    if decision not in {"retry", "reject"} or not reason.strip() or len(reason) > 2000:
        raise HTTPException(422, "Entscheidung und Begründung erforderlich")
    owner_id, reviewer_id, reviewer_name = row.user_id, reviewer.id, reviewer.username
    db.rollback()
    with transaction(owner_id) as (tx, connection):
        row = tx.get(models.MobileSyncReceipt, receipt_id)
        if row.status != "conflict":
            return RedirectResponse("/admin/sync-conflicts?msg=Bereits+entschieden", status_code=303)
        payload = json.loads(row.payload_json)
        if event_time:
            payload["event_time"] = event_time
        action = Action(protocol=1, owner_id=owner_id, client_action_id=row.client_action_id, kind=row.kind, payload=payload)
        if decision == "retry":
            # Der alte Erfolgsmarker darf eine echte Prüfung nicht abkürzen.
            response = _attempt(request, action, tx, connection)
            row = tx.get(models.MobileSyncReceipt, receipt_id)
            if not response.get("ok"):
                row.message = response.get("message", "Konflikt besteht weiterhin")
                tx.commit()
                logging_setup.log_audit("Synchronisationskonflikt erneut geprüft", user=reviewer_name, detail=f"Vorgang {receipt_id}")
                return RedirectResponse(main._build_redirect("/admin/sync-conflicts", error=row.message), status_code=303)
            row.status = "applied"
            row.message = "Nach Prüfung verbucht"
        else:
            row.status = "rejected"
            row.message = "Nach Prüfung abgelehnt"
        row.resolution_note = reason.strip()
        row.resolution_json = json.dumps(payload, ensure_ascii=False)
        row.resolved_by_id = reviewer_id
        row.resolved_at = datetime.utcnow()
        tx.commit()
    logging_setup.log_audit("Synchronisationskonflikt entschieden", user=reviewer_name, detail=f"Vorgang {receipt_id}: {decision}")
    return RedirectResponse("/admin/sync-conflicts?msg=Entscheidung+gespeichert", status_code=303)
