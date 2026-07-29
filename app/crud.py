from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from . import models, schemas
from . import permissions as group_permissions
from . import security


def get_group(db: Session, group_id: int) -> Optional[models.Group]:
    return db.query(models.Group).filter(models.Group.id == group_id).first()


def get_groups(db: Session) -> List[models.Group]:
    return db.query(models.Group).order_by(models.Group.name).all()


def create_group(db: Session, group: schemas.GroupCreate) -> models.Group:
    db_group = models.Group(name=group.name, description=group.description or "")
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group


def get_group_by_name(db: Session, name: str) -> Optional[models.Group]:
    return db.query(models.Group).filter(models.Group.name == name).first()


def set_group_members(db: Session, group: models.Group, user_ids: Iterable[int]) -> models.Group:
    """Mitglieder einer Gruppe vollständig setzen."""
    wanted = {int(value) for value in user_ids}
    group.users = db.query(models.User).filter(models.User.id.in_(wanted)).all() if wanted else []
    db.commit()
    db.refresh(group)
    return group


# --- Rollen (RBAC) -------------------------------------------------------------

def get_role(db: Session, role_id: int) -> Optional[models.Role]:
    return db.query(models.Role).filter(models.Role.id == role_id).first()


def get_role_by_name(db: Session, name: str) -> Optional[models.Role]:
    return db.query(models.Role).filter(models.Role.name == name).first()


def get_roles(db: Session) -> List[models.Role]:
    return db.query(models.Role).order_by(models.Role.name).all()


def create_role(
    db: Session,
    *,
    name: str,
    description: str = "",
    is_system: bool = False,
    is_active: bool = True,
    permissions: Optional[dict[str, str]] = None,
) -> models.Role:
    role = models.Role(
        name=name, description=description or "", is_system=is_system, is_active=is_active
    )
    db.add(role)
    db.flush()
    _apply_role_permissions(db, role, permissions or {})
    db.commit()
    db.refresh(role)
    return role


def _apply_role_permissions(
    db: Session, role: models.Role, permissions: dict[str, str]
) -> None:
    """Berechtigungen einer Rolle vollständig ersetzen (nur bekannte Keys).

    Die Altbestände werden bewusst gelöscht **und geflusht**, bevor die neuen
    Zeilen entstehen – sonst kollidiert der Insert mit dem Unique-Index aus
    (Rolle, Recht).
    """
    for item in list(role.permissions):
        db.delete(item)
    db.flush()
    for key, scope in permissions.items():
        permission = group_permissions.PERMISSIONS_BY_KEY.get(key)
        if permission is None or scope == group_permissions.SCOPE_NONE:
            continue
        db.add(
            models.RolePermission(role_id=role.id, permission_key=key, scope=scope)
        )
    db.flush()


def update_role(
    db: Session,
    role_id: int,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    permissions: Optional[dict[str, str]] = None,
) -> Optional[models.Role]:
    """Rolle ändern. Systemrollen sind unveränderlich und werden abgelehnt."""
    role = get_role(db, role_id)
    if not role:
        return None
    if role.is_system:
        raise ValueError("SYSTEM_ROLE_IMMUTABLE")
    if name is not None:
        role.name = name
    if description is not None:
        role.description = description
    if is_active is not None:
        role.is_active = bool(is_active)
    if permissions is not None:
        _apply_role_permissions(db, role, permissions)
    db.commit()
    db.refresh(role)
    return role


def delete_role(db: Session, role_id: int) -> bool:
    role = get_role(db, role_id)
    if not role or role.is_system:
        return False
    db.delete(role)
    db.commit()
    return True


def set_user_groups(db: Session, user: models.User, group_ids: Iterable[int]) -> models.User:
    wanted = {int(value) for value in group_ids}
    user.groups = db.query(models.Group).filter(models.Group.id.in_(wanted)).all() if wanted else []
    db.commit()
    db.refresh(user)
    return user


def set_user_roles(db: Session, user: models.User, role_ids: Iterable[int]) -> models.User:
    wanted = {int(value) for value in role_ids}
    user.roles = db.query(models.Role).filter(models.Role.id.in_(wanted)).all() if wanted else []
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, user_id: int) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.username == username).first()


def get_users(db: Session) -> List[models.User]:
    return db.query(models.User).order_by(models.User.full_name).all()


def _allocate_internal_pin(db: Session) -> str:
    used = {row[0] for row in db.query(models.User.pin_code).all() if row[0]}
    for candidate in range(10000):
        pin = f"{candidate:04d}"
        if pin not in used:
            return pin
    raise ValueError("Keine interne PIN mehr verfügbar")


def _pop_membership(payload: dict) -> tuple[Optional[set[int]], Optional[set[int]]]:
    """Gruppen-/Rollenzuordnung aus dem Schema lösen.

    ``None`` bedeutet „nicht angegeben“ – die vorhandene Zuordnung bleibt dann
    unverändert. ``group_id`` bleibt aus Kompatibilität erhalten und zählt als
    einzelne Mitgliedschaft, wenn keine ``group_ids`` übergeben wurden.
    """
    raw_groups = payload.pop("group_ids", None)
    raw_roles = payload.pop("role_ids", None)
    group_ids = {int(value) for value in raw_groups} if raw_groups is not None else None
    role_ids = {int(value) for value in raw_roles} if raw_roles is not None else None
    legacy_group = payload.pop("group_id", None)
    if group_ids is None and legacy_group:
        group_ids = {int(legacy_group)}
    return group_ids, role_ids


def create_user(db: Session, user: schemas.UserCreate) -> models.User:
    payload = user.model_dump()
    group_ids, role_ids = _pop_membership(payload)
    raw_password = payload.pop("password")
    security.validate_password_strength(raw_password)
    weekly_hours = float(payload.get("standard_weekly_hours", 0) or 0)
    payload["standard_weekly_hours"] = weekly_hours
    payload["standard_daily_minutes"] = int(round(max(weekly_hours, 0) * 60 / 5)) if weekly_hours else 0
    limit_value = payload.get("monthly_overtime_limit_minutes", None)
    if limit_value is None:
        payload["monthly_overtime_limit_minutes"] = None
    else:
        limit_minutes = int(limit_value)
        payload["monthly_overtime_limit_minutes"] = max(limit_minutes, 0)
    if not payload.get("rfid_tag"):
        payload["rfid_tag"] = None
    payload["password_hash"] = security.hash_password(raw_password)
    payload["must_change_password"] = True
    payload["pin_code"] = _allocate_internal_pin(db)
    db_user = models.User(**payload)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    if group_ids is not None:
        set_user_groups(db, db_user, group_ids)
    if role_ids is not None:
        set_user_roles(db, db_user, role_ids)
    return db_user


def update_user(db: Session, user_id: int, user: schemas.UserUpdate) -> Optional[models.User]:
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    payload = user.model_dump()
    group_ids, role_ids = _pop_membership(payload)
    if "standard_weekly_hours" in payload:
        weekly_hours = float(payload["standard_weekly_hours"] or 0)
        db_user.standard_weekly_hours = weekly_hours
        db_user.standard_daily_minutes = int(round(max(weekly_hours, 0) * 60 / 5)) if weekly_hours else 0
        payload.pop("standard_weekly_hours", None)
    if "monthly_overtime_limit_minutes" in payload:
        limit_value = payload.pop("monthly_overtime_limit_minutes")
        if limit_value is None:
            db_user.monthly_overtime_limit_minutes = None
        else:
            limit_minutes = int(limit_value)
            db_user.monthly_overtime_limit_minutes = max(limit_minutes, 0)
    if "rfid_tag" in payload and not payload["rfid_tag"]:
        payload["rfid_tag"] = None
    if "password" in payload:
        raw_password = payload.pop("password")
        if raw_password:
            security.validate_password_strength(raw_password)
            db_user.password_hash = security.hash_password(raw_password)
            db_user.must_change_password = True
    for key, value in payload.items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    if group_ids is not None:
        set_user_groups(db, db_user, group_ids)
    if role_ids is not None:
        set_user_roles(db, db_user, role_ids)
    return db_user


def delete_user(db: Session, user_id: int) -> bool:
    db_user = get_user(db, user_id)
    if not db_user:
        return False
    db.delete(db_user)
    db.commit()
    return True


def update_group(db: Session, group_id: int, group: schemas.GroupCreate) -> Optional[models.Group]:
    db_group = get_group(db, group_id)
    if not db_group:
        return None
    db_group.name = group.name
    db_group.description = group.description or ""
    db.commit()
    db.refresh(db_group)
    return db_group


def delete_group(db: Session, group_id: int) -> bool:
    db_group = get_group(db, group_id)
    if not db_group:
        return False
    if db_group.users:
        return False
    db.delete(db_group)
    db.commit()
    return True


_PREVIOUS_STATUS_SENTINEL = object()


def get_time_entry_by_external_reference(
    db: Session, source: str, external_id: str
) -> Optional[models.TimeEntry]:
    if not source or not external_id:
        return None
    return (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.source == source)
        .filter(models.TimeEntry.external_id == external_id)
        .first()
    )


def _entry_bounds(work_date: date, start_time: time, end_time: time, is_open: bool) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(work_date, start_time)
    if is_open:
        current_end = max(datetime.now(), start_dt + timedelta(seconds=1))
        return start_dt, current_end
    end_dt = datetime.combine(work_date, end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _intervals_overlap(
    first_start: datetime, first_end: datetime, second_start: datetime, second_end: datetime
) -> bool:
    return first_start < second_end and second_start < first_end


def _floor_to_minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def _intervals_overlap_minute(
    first_start: datetime, first_end: datetime, second_start: datetime, second_end: datetime
) -> bool:
    """Überschneidung minutengenau prüfen.

    Die Oberfläche arbeitet mit Minuten (``HH:MM``), Terminal-Importe speichern
    jedoch Sekunden. Direkt aneinandergrenzende Buchungen teilen sich denselben
    Stempel-Zeitpunkt inkl. Sekunden (z. B. Ende 14:18:45 = Beginn 14:18:45).
    Wird eine solche Buchung im Formular gespeichert, rundet die Startzeit auf
    die Minute ab (14:18:00) und würde die Vorbuchung um <1 Minute „überlappen".
    Durch das Abrunden auf die Minute werden solche Sekunden-Grenzfälle korrekt
    als *nicht* überlappend behandelt; echte Überschneidungen (≥ 1 Minute)
    bleiben erkannt.
    """
    return _intervals_overlap(
        _floor_to_minute(first_start),
        _floor_to_minute(first_end),
        _floor_to_minute(second_start),
        _floor_to_minute(second_end),
    )


def _describe_entry(entry: models.TimeEntry) -> str:
    """Kurzbeschreibung einer Buchung für Fehlermeldungen (Diagnose)."""
    day = entry.work_date.strftime("%d.%m.%Y") if entry.work_date else "?"
    start = entry.start_time.strftime("%H:%M") if entry.start_time else "?"
    if entry.is_open:
        end = "läuft"
    else:
        end = entry.end_time.strftime("%H:%M") if entry.end_time else "?"
    return f"{day} {start}–{end}"


def _overlapping_entries(
    db: Session, payload: dict, *, exclude_id: Optional[int] = None
) -> list[models.TimeEntry]:
    """Alle (nicht abgelehnten) Buchungen desselben Benutzers, deren Zeitraum
    sich mit dem übergebenen überschneidet."""
    user_id = payload["user_id"]
    work_date = payload["work_date"]
    start_time = payload["start_time"]
    end_time = payload["end_time"]
    is_open = bool(payload.get("is_open"))
    new_start, new_end = _entry_bounds(work_date, start_time, end_time, is_open)
    window_start = (new_start - timedelta(days=1)).date()
    window_end = (new_end + timedelta(days=1)).date()
    query = (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.status != models.TimeEntryStatus.REJECTED)
        .filter(models.TimeEntry.work_date >= window_start)
        .filter(models.TimeEntry.work_date <= window_end)
    )
    if exclude_id is not None:
        query = query.filter(models.TimeEntry.id != exclude_id)
    conflicts: list[models.TimeEntry] = []
    for existing in query.all():
        existing_start, existing_end = _entry_bounds(
            existing.work_date, existing.start_time, existing.end_time, existing.is_open
        )
        if _intervals_overlap_minute(new_start, new_end, existing_start, existing_end):
            conflicts.append(existing)
    return conflicts


def _ensure_no_time_overlap(
    db: Session, payload: dict, *, exclude_id: Optional[int] = None
) -> None:
    if _overlapping_entries(db, payload, exclude_id=exclude_id):
        raise ValueError("OVERLAPPING_TIME_ENTRY")


def _ensure_no_vacation_overlap(db: Session, vacation: schemas.VacationRequestCreate) -> None:
    conflict = (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.user_id == vacation.user_id)
        .filter(
            models.VacationRequest.status.in_(
                [
                    models.VacationStatus.PENDING,
                    models.VacationStatus.APPROVED,
                    models.VacationStatus.WITHDRAW_REQUESTED,
                ]
            )
        )
        .filter(models.VacationRequest.end_date >= vacation.start_date)
        .filter(models.VacationRequest.start_date <= vacation.end_date)
        .first()
    )
    if conflict:
        raise ValueError("VACATION_OVERLAP")


def _find_containing_closed_entry(
    db: Session, user_id: int, new_start: datetime, new_end: datetime
) -> Optional[models.TimeEntry]:
    """Abgeschlossene (Eintages-)Buchung finden, die den Nachtrag vollständig
    umschließt. Mehrtägige/über Mitternacht laufende Bestandsbuchungen werden
    bewusst ausgeklammert (Teilen wäre mehrdeutig)."""
    work_date = new_start.date()
    if new_end.date() != work_date:
        return None
    candidates = (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.is_open.is_(False))
        .filter(models.TimeEntry.status != models.TimeEntryStatus.REJECTED)
        .filter(models.TimeEntry.work_date == work_date)
        .all()
    )
    for existing in candidates:
        if existing.end_time <= existing.start_time:
            continue  # über Mitternacht – nicht teilen
        if existing.start_time <= new_start.time() and new_end.time() <= existing.end_time:
            return existing
    return None


def _split_closed_entry(
    db: Session,
    existing: models.TimeEntry,
    payload: dict,
    new_start: datetime,
    new_end: datetime,
) -> models.TimeEntry:
    """Nachtrag in eine umschließende, abgeschlossene Buchung einfügen.

    Die Bestandsbuchung wird in bis zu zwei Abschnitte (davor/danach) zerlegt,
    die Attribute (Firma, Kommentar, Status, Quelle) bleiben erhalten. Die
    erfassten Pausenminuten bleiben beim ersten Abschnitt (oder – falls es
    keinen gibt – beim zweiten). So entstehen keine doppelt gezählten Zeiten.
    """
    _ensure_no_time_overlap(db, payload, exclude_id=existing.id)

    original_start = existing.start_time
    original_end = existing.end_time
    original_breaks = existing.break_minutes or 0
    new_start_time = new_start.time()
    new_end_time = new_end.time()

    has_first = new_start_time > original_start
    has_second = new_end_time < original_end

    def _clone_part(start_time: time, end_time: time, break_minutes: int) -> models.TimeEntry:
        return models.TimeEntry(
            user_id=existing.user_id,
            company_id=existing.company_id,
            work_date=existing.work_date,
            start_time=start_time,
            end_time=end_time,
            break_minutes=break_minutes,
            break_started_at=None,
            is_open=False,
            notes=existing.notes or "",
            status=existing.status,
            is_manual=existing.is_manual,
            is_remote=bool(existing.is_remote),
            source=existing.source,
            external_id=existing.external_id,
        )

    if has_first:
        # Bestandsbuchung wird zum ersten Abschnitt (behält Pausen/Referenzen).
        existing.end_time = new_start_time
        if has_second:
            db.add(_clone_part(new_end_time, original_end, 0))
    elif has_second:
        # Kein erster Abschnitt: Bestandsbuchung wird zum zweiten Abschnitt.
        existing.start_time = new_end_time
        existing.end_time = original_end
        existing.break_minutes = original_breaks
    else:
        # Nachtrag deckt die Bestandsbuchung exakt ab – sie wird ersetzt.
        db.delete(existing)

    manual_entry = models.TimeEntry(**payload)
    db.add(manual_entry)
    db.commit()
    db.refresh(manual_entry)
    return manual_entry


def create_manual_time_entry(db: Session, entry: schemas.TimeEntryCreate) -> tuple[models.TimeEntry, bool]:
    """Manuelle Buchung anlegen; liegt sie innerhalb einer bestehenden Buchung
    des Benutzers (laufend oder abgeschlossen), wird diese geteilt.

    Ergebnis entspricht dem Live-Stempeln: Der Zeitraum davor wird
    abgeschlossen (bisherige Pausenminuten bleiben dort), der Nachtrag
    eingefügt (typisch: PENDING) und der Zeitraum danach mit Firma/Kommentar
    unverändert fortgeführt (bei der laufenden Buchung: sie läuft weiter). So
    entstehen keine doppelt gezählten Zeiten.

    Rückgabe: (angelegter Eintrag, wurde_geteilt). Fehler:
    - ``BREAK_RUNNING``: laufende Pause muss zuerst beendet werden.
    - ``OVERLAPPING_TIME_ENTRY``: Überschneidung mit anderen Buchungen oder
      nur teilweise Überlappung (z. B. Ende in der Zukunft).
    """
    payload = entry.model_dump()
    new_start, new_end = _entry_bounds(
        payload["work_date"], payload["start_time"], payload["end_time"], False
    )
    new_start = _normalize_time(new_start)
    new_end = _normalize_time(new_end)

    # 1. Fällt der Nachtrag in die laufende Buchung? → laufende Buchung teilen.
    open_entry = get_open_time_entry(db, payload["user_id"])
    if open_entry:
        open_start, open_end = _entry_bounds(
            open_entry.work_date, open_entry.start_time, open_entry.end_time, True
        )
        if _intervals_overlap_minute(new_start, new_end, open_start, open_end):
            if open_entry.break_started_at:
                raise ValueError("BREAK_RUNNING")
            if new_start < open_start or new_end > open_end:
                # Nur teilweise Überlappung (beginnt vor der laufenden Buchung
                # oder endet in der Zukunft) lässt sich nicht sinnvoll teilen.
                raise ValueError("OVERLAPPING_TIME_ENTRY")

            _ensure_no_time_overlap(db, payload, exclude_id=open_entry.id)

            if new_start - open_start >= timedelta(minutes=1):
                first_part = models.TimeEntry(
                    user_id=open_entry.user_id,
                    company_id=open_entry.company_id,
                    work_date=open_entry.work_date,
                    start_time=open_entry.start_time,
                    end_time=new_start.time(),
                    break_minutes=open_entry.break_minutes or 0,
                    break_started_at=None,
                    is_open=False,
                    notes=open_entry.notes or "",
                    status=models.TimeEntryStatus.APPROVED,
                    is_manual=False,
                    is_remote=bool(open_entry.is_remote),
                )
                db.add(first_part)
                open_entry.break_minutes = 0

            # Laufende Buchung ab dem Ende des Nachtrags weiterlaufen lassen
            # (offene Einträge führen end_time als Platzhalter == start_time).
            open_entry.work_date = new_end.date()
            open_entry.start_time = new_end.time()
            open_entry.end_time = new_end.time()

            manual_entry = models.TimeEntry(**payload)
            db.add(manual_entry)
            db.commit()
            db.refresh(manual_entry)
            return manual_entry, True

    # 2. Fällt der Nachtrag in eine abgeschlossene Buchung? → diese teilen.
    containing = _find_containing_closed_entry(db, payload["user_id"], new_start, new_end)
    if containing is not None:
        return _split_closed_entry(db, containing, payload, new_start, new_end), True

    # 3. Sonst normal anlegen (mit Überschneidungsprüfung).
    return create_time_entry(db, entry), False


def create_time_entry(db: Session, entry: schemas.TimeEntryCreate) -> models.TimeEntry:
    payload = entry.model_dump()
    if payload.get("break_started_at") and not payload.get("is_open"):
        payload["break_started_at"] = None
    source = (payload.get("source") or "").strip()
    external_id = (payload.get("external_id") or "").strip()
    payload["source"] = source or None
    payload["external_id"] = external_id or None
    if source and external_id:
        existing = get_time_entry_by_external_reference(db, source, external_id)
        if existing:
            return existing
    _ensure_no_time_overlap(db, payload)
    db_entry = models.TimeEntry(**payload)
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry


def get_time_entry(db: Session, entry_id: int) -> Optional[models.TimeEntry]:
    return db.query(models.TimeEntry).filter(models.TimeEntry.id == entry_id).first()


def get_open_time_entry(db: Session, user_id: int) -> Optional[models.TimeEntry]:
    return (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.is_open.is_(True))
        .order_by(models.TimeEntry.work_date.desc(), models.TimeEntry.start_time.desc())
        .first()
    )


def get_last_finished_time_entry(db: Session, user_id: int) -> Optional[models.TimeEntry]:
    """Most recently finished (closed) booking of the user – the entry a
    'Kommentar nachträglich bearbeiten' action refers to right after clock-out."""
    return (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.is_open.is_(False))
        .order_by(
            models.TimeEntry.work_date.desc(),
            models.TimeEntry.end_time.desc(),
            models.TimeEntry.id.desc(),
        )
        .first()
    )


def update_time_entry_notes(
    db: Session,
    entry: models.TimeEntry,
    notes: str,
    *,
    is_remote: Optional[bool] = None,
) -> models.TimeEntry:
    """Kommentar (und optional den Einsatzort) einer Buchung nachtragen.

    ``is_remote=None`` lässt den Einsatzort unverändert – so ändert ein reiner
    Kommentar-Nachtrag die Angabe nicht versehentlich.
    """
    entry.notes = (notes or "")[:255]
    if is_remote is not None:
        entry.is_remote = bool(is_remote)
    db.commit()
    db.refresh(entry)
    return entry


def _normalize_time(moment: datetime) -> datetime:
    return moment.replace(microsecond=0)


def start_running_entry(
    db: Session,
    *,
    user_id: int,
    started_at: datetime,
    company_id: Optional[int] = None,
    notes: str = "",
    is_remote: bool = False,
) -> models.TimeEntry:
    normalized = _normalize_time(started_at)
    entry = schemas.TimeEntryCreate(
        user_id=user_id,
        company_id=company_id,
        work_date=normalized.date(),
        start_time=normalized.time(),
        end_time=normalized.time(),
        break_minutes=0,
        break_started_at=None,
        is_open=True,
        notes=notes,
        status=models.TimeEntryStatus.APPROVED,
        is_manual=False,
        is_remote=is_remote,
    )
    return create_time_entry(db, entry)


def finish_running_entry(db: Session, entry: models.TimeEntry, finished_at: datetime) -> models.TimeEntry:
    normalized = _normalize_time(finished_at)
    if entry.break_started_at:
        end_break(db, entry, normalized)
        db.refresh(entry)
    entry.end_time = normalized.time()
    entry.is_open = False
    entry.break_started_at = None
    db.commit()
    db.refresh(entry)
    return entry


def start_break(db: Session, entry: models.TimeEntry, started_at: datetime) -> models.TimeEntry:
    normalized = _normalize_time(started_at)
    entry.break_started_at = normalized.time()
    db.commit()
    db.refresh(entry)
    return entry


def end_break(db: Session, entry: models.TimeEntry, finished_at: datetime) -> models.TimeEntry:
    if not entry.break_started_at:
        return entry
    normalized = _normalize_time(finished_at)
    break_start = datetime.combine(entry.work_date, entry.break_started_at)
    break_end = datetime.combine(normalized.date(), normalized.time())
    if break_end < break_start:
        break_end += timedelta(days=1)
    duration = max(int((break_end - break_start).total_seconds() // 60), 0)
    entry.break_minutes += duration
    entry.break_started_at = None
    db.commit()
    db.refresh(entry)
    return entry


def get_time_entries_for_user(
    db: Session,
    user_id: int,
    start: Optional[date] = None,
    end: Optional[date] = None,
    statuses: Optional[Iterable[str]] = None,
) -> List[models.TimeEntry]:
    query = db.query(models.TimeEntry).filter(models.TimeEntry.user_id == user_id)
    if start:
        query = query.filter(models.TimeEntry.work_date >= start)
    if end:
        query = query.filter(models.TimeEntry.work_date <= end)
    if statuses:
        query = query.filter(models.TimeEntry.status.in_(list(statuses)))
    return query.order_by(models.TimeEntry.work_date.desc(), models.TimeEntry.start_time.desc()).all()


def get_time_entries(
    db: Session,
    user_id: Optional[int] = None,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    company_id: Optional[int] = None,
    statuses: Optional[Iterable[str]] = None,
    is_manual: Optional[bool] = None,
) -> List[models.TimeEntry]:
    query = (
        db.query(models.TimeEntry)
        # Firma direkt mitladen: die Auswertungen zeigen den Firmennamen je
        # Buchung (auch im PDF-Export) – ohne Eager-Loading je Zeile eine Abfrage.
        .options(joinedload(models.TimeEntry.company))
        .order_by(models.TimeEntry.work_date.desc(), models.TimeEntry.start_time.desc())
    )
    if user_id:
        query = query.filter(models.TimeEntry.user_id == user_id)
    if start:
        query = query.filter(models.TimeEntry.work_date >= start)
    if end:
        query = query.filter(models.TimeEntry.work_date <= end)
    if company_id:
        query = query.filter(models.TimeEntry.company_id == company_id)
    if statuses:
        query = query.filter(models.TimeEntry.status.in_(list(statuses)))
    if is_manual is not None:
        query = query.filter(models.TimeEntry.is_manual.is_(is_manual))
    return query.all()


def plan_time_entry_overwrite(
    db: Session, entry_id: int, entry: schemas.TimeEntryCreate
) -> list[dict]:
    """Ermittelt, welche Buchungen eine Änderung überschreiben würde.

    Liefert je betroffener Buchung ein Dict mit ``entry`` (die kollidierende
    Buchung), ``action`` (``delete`` | ``shorten`` | ``split``) und – bei
    ``shorten``/``split`` – den resultierenden Zeiten. Nur Konflikte, die neu
    entstehen (siehe ``update_time_entry``), werden gemeldet.
    """
    db_entry = get_time_entry(db, entry_id)
    if not db_entry:
        return []
    payload = entry.model_dump()
    payload["break_started_at"] = None
    payload["is_open"] = False
    payload.pop("source", None)
    payload.pop("external_id", None)

    old_start, old_end = _entry_bounds(
        db_entry.work_date, db_entry.start_time, db_entry.end_time, db_entry.is_open
    )
    new_start, new_end = _entry_bounds(
        payload["work_date"], payload["start_time"], payload["end_time"], False
    )
    new_start, new_end = _floor_to_minute(new_start), _floor_to_minute(new_end)

    plan: list[dict] = []
    for conflict in _overlapping_entries(db, payload, exclude_id=entry_id):
        conflict_start, conflict_end = _entry_bounds(
            conflict.work_date, conflict.start_time, conflict.end_time, conflict.is_open
        )
        if _intervals_overlap_minute(old_start, old_end, conflict_start, conflict_end):
            continue  # bestand schon vorher – kein Überschreiben nötig
        c_start = _floor_to_minute(conflict_start)
        c_end = _floor_to_minute(conflict_end)
        if new_start <= c_start and c_end <= new_end:
            action, result = "delete", None
        elif c_start < new_start and new_end < c_end:
            action = "split"
            result = ((c_start.time(), new_start.time()), (new_end.time(), c_end.time()))
        elif c_start < new_start:
            action, result = "shorten", (c_start.time(), new_start.time())
        else:
            action, result = "shorten", (new_end.time(), c_end.time())
        plan.append({
            "entry": conflict,
            "action": action,
            "result": result,
            "description": _describe_entry(conflict),
        })
    return plan


def _apply_overwrite(
    db: Session, plan: list[dict], new_start: datetime, new_end: datetime
) -> None:
    """Kollidierende Buchungen gemäß Plan kürzen, teilen oder entfernen.

    Offene (laufende) Buchungen werden nie gelöscht, sondern nur verschoben –
    die laufende Zeiterfassung darf durch eine Korrektur nicht abbrechen.
    """
    for item in plan:
        conflict: models.TimeEntry = item["entry"]
        action = item["action"]
        if action == "delete":
            if conflict.is_open:
                # Laufende Buchung ab dem Ende der neuen Buchung fortführen.
                conflict.work_date = new_end.date()
                conflict.start_time = new_end.time()
                conflict.end_time = new_end.time()
                continue
            db.delete(conflict)
        elif action == "shorten":
            start_time, end_time = item["result"]
            conflict.start_time = start_time
            if conflict.is_open:
                conflict.end_time = start_time
            else:
                conflict.end_time = end_time
        elif action == "split":
            (first_start, first_end), (second_start, second_end) = item["result"]
            conflict.start_time = first_start
            conflict.end_time = first_end
            conflict.is_open = False
            db.add(models.TimeEntry(
                user_id=conflict.user_id,
                company_id=conflict.company_id,
                work_date=conflict.work_date,
                start_time=second_start,
                end_time=second_end,
                break_minutes=0,
                break_started_at=None,
                is_open=False,
                notes=conflict.notes or "",
                status=conflict.status,
                is_manual=conflict.is_manual,
                is_remote=bool(conflict.is_remote),
            ))


def update_time_entry(
    db: Session,
    entry_id: int,
    entry: schemas.TimeEntryCreate,
    *,
    overwrite: bool = False,
) -> Optional[models.TimeEntry]:
    """Buchung aktualisieren.

    ``overwrite=True`` löst neu entstehende Überschneidungen auf, statt sie
    abzulehnen: kollidierende Buchungen werden gekürzt, geteilt oder entfernt
    (siehe ``plan_time_entry_overwrite``). Ohne das Flag wird bei einem neuen
    Konflikt ``OVERLAPPING_TIME_ENTRY:<Beschreibung>`` ausgelöst.
    """
    db_entry = get_time_entry(db, entry_id)
    if not db_entry:
        return None
    payload = entry.model_dump()
    payload["break_started_at"] = None
    payload["is_open"] = False
    payload.pop("source", None)
    payload.pop("external_id", None)

    # Beim Bearbeiten nur NEU entstehende Überschneidungen ablehnen. Eine
    # Buchung, die bereits mit dem bisherigen Zeitraum kollidierte (z. B. eine
    # noch laufende Buchung, deren Fenster bis „jetzt" reicht, oder eine bereits
    # vorhandene Doppelbuchung), darf eine Korrektur nicht blockieren – sonst
    # ließe sich eine falsche Buchung nicht einmal verkürzen.
    if overwrite:
        # Kollidierende Buchungen zuerst anpassen/entfernen, damit die
        # anschließende Änderung konfliktfrei ist.
        plan = plan_time_entry_overwrite(db, entry_id, entry)
        new_start, new_end = _entry_bounds(
            payload["work_date"], payload["start_time"], payload["end_time"], False
        )
        _apply_overwrite(db, plan, _floor_to_minute(new_start), _floor_to_minute(new_end))
        db.flush()
    else:
        old_start, old_end = _entry_bounds(
            db_entry.work_date, db_entry.start_time, db_entry.end_time, db_entry.is_open
        )
        for conflict in _overlapping_entries(db, payload, exclude_id=entry_id):
            conflict_start, conflict_end = _entry_bounds(
                conflict.work_date, conflict.start_time, conflict.end_time, conflict.is_open
            )
            if not _intervals_overlap_minute(old_start, old_end, conflict_start, conflict_end):
                # Überschneidung existierte vorher nicht → echter neuer Konflikt.
                # Details der kollidierenden Buchung mitgeben, damit die Meldung
                # nennt, WELCHE Buchung blockiert (Diagnose).
                raise ValueError(f"OVERLAPPING_TIME_ENTRY:{_describe_entry(conflict)}")

    for key, value in payload.items():
        setattr(db_entry, key, value)
    db.commit()
    db.refresh(db_entry)
    return db_entry


def set_time_entry_status(db: Session, entry_id: int, status: str) -> Optional[models.TimeEntry]:
    db_entry = get_time_entry(db, entry_id)
    if not db_entry:
        return None
    db_entry.status = status
    db.commit()
    db.refresh(db_entry)
    return db_entry


def delete_time_entry(db: Session, entry_id: int) -> bool:
    db_entry = get_time_entry(db, entry_id)
    if not db_entry:
        return False
    db.delete(db_entry)
    db.commit()
    return True


def create_vacation_request(db: Session, vacation: schemas.VacationRequestCreate) -> models.VacationRequest:
    _ensure_no_vacation_overlap(db, vacation)
    db_vacation = models.VacationRequest(**vacation.model_dump())
    db.add(db_vacation)
    db.commit()
    db.refresh(db_vacation)
    return db_vacation


def update_vacation_status(
    db: Session,
    vacation_id: int,
    status: str,
    *,
    previous_status: object = _PREVIOUS_STATUS_SENTINEL,
) -> Optional[models.VacationRequest]:
    db_vacation = db.query(models.VacationRequest).filter(models.VacationRequest.id == vacation_id).first()
    if not db_vacation:
        return None
    db_vacation.status = status
    if previous_status is not _PREVIOUS_STATUS_SENTINEL:
        db_vacation.previous_status = previous_status
    elif status != models.VacationStatus.WITHDRAW_REQUESTED:
        db_vacation.previous_status = None
    db.commit()
    db.refresh(db_vacation)
    return db_vacation


def get_vacations_for_user(db: Session, user_id: int) -> List[models.VacationRequest]:
    return (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.user_id == user_id)
        .order_by(models.VacationRequest.start_date)
        .all()
    )


def get_vacations_in_range(
    db: Session,
    start: date,
    end: date,
    *,
    user_id: Optional[int] = None,
    statuses: Optional[Iterable[str]] = None,
) -> List[models.VacationRequest]:
    query = (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.start_date <= end)
        .filter(models.VacationRequest.end_date >= start)
        .order_by(models.VacationRequest.start_date)
    )
    if user_id is not None:
        query = query.filter(models.VacationRequest.user_id == user_id)
    if statuses:
        query = query.filter(models.VacationRequest.status.in_(list(statuses)))
    return query.all()


def request_vacation_withdrawal(db: Session, vacation_id: int) -> Optional[models.VacationRequest]:
    db_vacation = db.query(models.VacationRequest).filter(models.VacationRequest.id == vacation_id).first()
    if not db_vacation:
        return None
    if db_vacation.status == models.VacationStatus.WITHDRAW_REQUESTED:
        return db_vacation
    if db_vacation.status not in (models.VacationStatus.PENDING, models.VacationStatus.APPROVED):
        return None
    previous = db_vacation.status
    return update_vacation_status(
        db,
        vacation_id,
        models.VacationStatus.WITHDRAW_REQUESTED,
        previous_status=previous,
    )


def approve_vacation_withdrawal(db: Session, vacation_id: int) -> Optional[models.VacationRequest]:
    db_vacation = db.query(models.VacationRequest).filter(models.VacationRequest.id == vacation_id).first()
    if not db_vacation or db_vacation.status != models.VacationStatus.WITHDRAW_REQUESTED:
        return None
    return update_vacation_status(
        db,
        vacation_id,
        models.VacationStatus.CANCELLED,
        previous_status=None,
    )


def deny_vacation_withdrawal(db: Session, vacation_id: int) -> Optional[models.VacationRequest]:
    db_vacation = db.query(models.VacationRequest).filter(models.VacationRequest.id == vacation_id).first()
    if not db_vacation or db_vacation.status != models.VacationStatus.WITHDRAW_REQUESTED:
        return None
    previous = db_vacation.previous_status or models.VacationStatus.PENDING
    return update_vacation_status(
        db,
        vacation_id,
        previous,
        previous_status=None,
    )


def get_vacation_request(db: Session, vacation_id: int) -> Optional[models.VacationRequest]:
    return (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.id == vacation_id)
        .first()
    )


def get_vacation_requests(
    db: Session,
    status: Optional[str] = None,
    statuses: Optional[Iterable[str]] = None,
) -> List[models.VacationRequest]:
    query = db.query(models.VacationRequest).order_by(models.VacationRequest.start_date)
    if statuses:
        query = query.filter(models.VacationRequest.status.in_(list(statuses)))
    elif status:
        query = query.filter(models.VacationRequest.status == status)
    return query.all()


def create_holiday(db: Session, holiday: schemas.HolidayCreate) -> models.Holiday:
    db_holiday = models.Holiday(**holiday.model_dump())
    db.add(db_holiday)
    db.commit()
    db.refresh(db_holiday)
    return db_holiday


def get_holidays_for_year(db: Session, year: int, region: str = "DE") -> List[models.Holiday]:
    return (
        db.query(models.Holiday)
        .filter(models.Holiday.region == region)
        .filter(models.Holiday.date >= date(year, 1, 1))
        .filter(models.Holiday.date <= date(year, 12, 31))
        .order_by(models.Holiday.date)
        .all()
    )


def upsert_holidays(db: Session, holidays: Iterable[schemas.HolidayCreate]) -> List[models.Holiday]:
    stored: List[models.Holiday] = []
    for holiday in holidays:
        existing = (
            db.query(models.Holiday)
            .filter(models.Holiday.date == holiday.date)
            .filter(models.Holiday.region == holiday.region)
            .first()
        )
        if existing:
            existing.name = holiday.name
            existing.region = holiday.region
            existing.source = getattr(holiday, "source", existing.source) or existing.source
            stored.append(existing)
        else:
            stored.append(create_holiday(db, holiday))
    db.commit()
    return stored


def get_holiday(db: Session, holiday_id: int) -> Optional[models.Holiday]:
    return db.query(models.Holiday).filter(models.Holiday.id == holiday_id).first()


def delete_holiday(db: Session, holiday_id: int) -> bool:
    holiday = get_holiday(db, holiday_id)
    if not holiday:
        return False
    db.delete(holiday)
    db.commit()
    return True


def get_holidays(db: Session, region: Optional[str] = None) -> List[models.Holiday]:
    query = db.query(models.Holiday)
    if region:
        query = query.filter(models.Holiday.region == region)
    return query.order_by(models.Holiday.date).all()


def get_holiday_regions(db: Session) -> List[str]:
    regions = db.query(models.Holiday.region).distinct().all()
    return [region for (region,) in regions if region]


def get_default_holiday_region(db: Session) -> str:
    latest = (
        db.query(models.Holiday.region)
        .filter(models.Holiday.region.isnot(None))
        .order_by(models.Holiday.created_at.desc())
        .first()
    )
    if latest and latest[0]:
        return latest[0]
    return "DE"


def get_upcoming_holidays(db: Session, region: Optional[str], limit: int = 5) -> List[models.Holiday]:
    query = db.query(models.Holiday).filter(models.Holiday.date >= date.today())
    if region:
        query = query.filter(models.Holiday.region == region)
    return query.order_by(models.Holiday.date).limit(limit).all()


def replace_holidays_for_region(
    db: Session, region: str, year: int, holidays: Iterable[schemas.HolidayCreate]
) -> List[models.Holiday]:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    db.query(models.Holiday).filter(models.Holiday.region == region).filter(models.Holiday.date >= start).filter(
        models.Holiday.date <= end
    ).delete(synchronize_session=False)
    created: List[models.Holiday] = []
    for holiday in holidays:
        payload = holiday.model_dump()
        payload.setdefault("region", region)
        db_holiday = models.Holiday(**payload)
        db.add(db_holiday)
        created.append(db_holiday)
    db.commit()
    for holiday in created:
        db.refresh(holiday)
    return created

def apply_statutory_holidays(
    db: Session, region: str, year: int, holidays: Iterable[schemas.HolidayCreate]
) -> dict[str, int]:
    """Replace statutory holidays for ``region``/``year`` while preserving any
    custom holidays the administrator added (§22).

    - existing rows with ``source='statutory'`` for the region/year are removed
      and re-inserted from the freshly calculated set,
    - custom rows (``source='custom'``) are never touched,
    - a statutory entry that collides with an existing custom entry on the same
      date is skipped so the custom one wins (no duplicates, no overwrite).
    """

    start = date(year, 1, 1)
    end = date(year, 12, 31)
    base_query = (
        db.query(models.Holiday)
        .filter(models.Holiday.region == region)
        .filter(models.Holiday.date >= start)
        .filter(models.Holiday.date <= end)
    )
    base_query.filter(models.Holiday.source == "statutory").delete(synchronize_session=False)
    db.flush()

    # Dates already occupied by custom holidays must not be overwritten.
    occupied = {
        row.date
        for row in base_query.filter(models.Holiday.source == "custom").all()
    }

    created = 0
    skipped = 0
    for holiday in holidays:
        payload = holiday.model_dump()
        payload["region"] = region
        payload["source"] = "statutory"
        if payload["date"] in occupied:
            skipped += 1
            continue
        db.add(models.Holiday(**payload))
        created += 1
    db.commit()
    return {"created": created, "preserved_custom": len(occupied), "skipped": skipped}


def get_company(db: Session, company_id: int) -> Optional[models.Company]:
    return db.query(models.Company).filter(models.Company.id == company_id).first()


def get_companies(db: Session) -> List[models.Company]:
    return db.query(models.Company).order_by(models.Company.name).all()


def get_company_by_name(db: Session, name: str) -> Optional[models.Company]:
    return db.query(models.Company).filter(models.Company.name == name).first()


def find_company_by_name(db: Session, name: str) -> Optional[models.Company]:
    """Exact match first, then case-insensitive – used to resolve the free-text
    company search of the mobile clock-in when no dropdown value was submitted."""
    cleaned = (name or "").strip()
    if not cleaned:
        return None
    company = get_company_by_name(db, cleaned)
    if company:
        return company
    return (
        db.query(models.Company)
        .filter(func.lower(models.Company.name) == cleaned.lower())
        .first()
    )


def create_company(db: Session, company: schemas.CompanyCreate) -> models.Company:
    db_company = models.Company(**company.model_dump())
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company


def update_company(db: Session, company_id: int, company: schemas.CompanyUpdate) -> Optional[models.Company]:
    db_company = get_company(db, company_id)
    if not db_company:
        return None
    for key, value in company.model_dump().items():
        setattr(db_company, key, value)
    db.commit()
    db.refresh(db_company)
    return db_company


def delete_company(db: Session, company_id: int) -> bool:
    db_company = get_company(db, company_id)
    if not db_company:
        return False

    company_name = db_company.name
    (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.company_id == company_id)
        .update(
            {
                models.TimeEntry.company_id: None,
                models.TimeEntry.deleted_company_name: company_name,
            },
            synchronize_session=False,
        )
    )

    db.delete(db_company)
    db.commit()
    return True


def get_mobile_sync_action(
    db: Session, user_id: int, client_action_id: str
) -> Optional[models.MobileSyncAction]:
    return (
        db.query(models.MobileSyncAction)
        .filter(models.MobileSyncAction.user_id == user_id)
        .filter(models.MobileSyncAction.client_action_id == client_action_id)
        .first()
    )


def create_mobile_sync_action(
    db: Session,
    *,
    user_id: int,
    client_action_id: str,
    action: str,
) -> models.MobileSyncAction:
    db_action = models.MobileSyncAction(
        user_id=user_id,
        client_action_id=client_action_id,
        action=action,
    )
    db.add(db_action)
    db.commit()
    db.refresh(db_action)
    return db_action


def get_mobile_history_time_entries(
    db: Session, user_id: int, since_date: date
) -> List[models.TimeEntry]:
    return (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.user_id == user_id)
        .filter(models.TimeEntry.work_date >= since_date)
        .order_by(models.TimeEntry.work_date.desc(), models.TimeEntry.start_time.desc())
        .all()
    )


def get_mobile_history_vacations(
    db: Session, user_id: int, since_date: date
) -> List[models.VacationRequest]:
    return (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.user_id == user_id)
        .filter(models.VacationRequest.end_date >= since_date)
        .order_by(models.VacationRequest.start_date.desc())
        .all()
    )


# --- Backup-Jobs (§0.9.2) -------------------------------------------------

def get_backup_jobs(db: Session) -> List[models.BackupJob]:
    return db.query(models.BackupJob).order_by(models.BackupJob.name).all()


def get_backup_job(db: Session, job_id: int) -> Optional[models.BackupJob]:
    return db.query(models.BackupJob).filter(models.BackupJob.id == job_id).first()


def create_backup_job(db: Session, **fields) -> models.BackupJob:
    job = models.BackupJob(**fields)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_backup_job(db: Session, job_id: int, **fields) -> Optional[models.BackupJob]:
    job = get_backup_job(db, job_id)
    if not job:
        return None
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    return job


def delete_backup_job(db: Session, job_id: int) -> bool:
    job = get_backup_job(db, job_id)
    if not job:
        return False
    db.delete(job)
    db.commit()
    return True


def get_active_backup_jobs(db: Session) -> List[models.BackupJob]:
    return db.query(models.BackupJob).filter(models.BackupJob.active.is_(True)).all()


def add_backup_run(db: Session, **fields) -> models.BackupRun:
    run = models.BackupRun(**fields)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_backup_runs(db: Session, limit: int = 100) -> List[models.BackupRun]:
    return (
        db.query(models.BackupRun)
        .order_by(models.BackupRun.started_at.desc())
        .limit(limit)
        .all()
    )


def get_backup_run(db: Session, run_id: int) -> Optional[models.BackupRun]:
    return db.query(models.BackupRun).filter(models.BackupRun.id == run_id).first()


def prune_backup_runs(db: Session, job_id: int, keep: int = 200) -> None:
    """Keep the history table from growing without bound."""
    runs = (
        db.query(models.BackupRun)
        .filter(models.BackupRun.job_id == job_id)
        .order_by(models.BackupRun.started_at.desc())
        .offset(keep)
        .all()
    )
    for run in runs:
        db.delete(run)
    if runs:
        db.commit()


# --- Terminalverwaltung (§0.9.8) ------------------------------------------

def get_terminals(db: Session) -> List[models.Terminal]:
    return db.query(models.Terminal).order_by(models.Terminal.name).all()


def get_terminal(db: Session, terminal_id: int) -> Optional[models.Terminal]:
    return db.query(models.Terminal).filter(models.Terminal.id == terminal_id).first()


def get_active_terminals(db: Session) -> List[models.Terminal]:
    return db.query(models.Terminal).filter(models.Terminal.active.is_(True)).all()


def create_terminal(db: Session, **fields) -> models.Terminal:
    terminal = models.Terminal(**fields)
    db.add(terminal)
    db.commit()
    db.refresh(terminal)
    return terminal


def update_terminal(db: Session, terminal_id: int, **fields) -> Optional[models.Terminal]:
    terminal = get_terminal(db, terminal_id)
    if not terminal:
        return None
    for key, value in fields.items():
        setattr(terminal, key, value)
    db.commit()
    db.refresh(terminal)
    return terminal


def delete_terminal(db: Session, terminal_id: int) -> bool:
    terminal = get_terminal(db, terminal_id)
    if not terminal:
        return False
    db.delete(terminal)
    db.commit()
    return True


def add_terminal_sync_run(db: Session, **fields) -> models.TerminalSyncRun:
    run = models.TerminalSyncRun(**fields)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_terminal_sync_runs(db: Session, limit: int = 100) -> List[models.TerminalSyncRun]:
    return (
        db.query(models.TerminalSyncRun)
        .order_by(models.TerminalSyncRun.started_at.desc())
        .limit(limit)
        .all()
    )


# --- Restore-Historie (§0.9.4) --------------------------------------------

def add_restore_run(db: Session, **fields) -> models.RestoreRun:
    run = models.RestoreRun(**fields)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_restore_runs(db: Session, limit: int = 100) -> List[models.RestoreRun]:
    return (
        db.query(models.RestoreRun)
        .order_by(models.RestoreRun.started_at.desc())
        .limit(limit)
        .all()
    )
