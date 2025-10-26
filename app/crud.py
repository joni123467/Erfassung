from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, Set

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models, schemas


def get_group(db: Session, group_id: int) -> Optional[models.Group]:
    return db.query(models.Group).filter(models.Group.id == group_id).first()


def get_groups(db: Session) -> List[models.Group]:
    return db.query(models.Group).order_by(models.Group.name).all()


def create_group(db: Session, group: schemas.GroupCreate) -> models.Group:
    db_group = models.Group(**group.model_dump())
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group


def get_user(db: Session, user_id: int) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.username == username).first()


def get_users(db: Session) -> List[models.User]:
    return db.query(models.User).order_by(models.User.full_name).all()


def get_user_by_pin(db: Session, pin_code: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.pin_code == pin_code).first()


def create_user(db: Session, user: schemas.UserCreate) -> models.User:
    payload = user.model_dump()
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
    db_user = models.User(**payload)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def update_user(db: Session, user_id: int, user: schemas.UserUpdate) -> Optional[models.User]:
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    payload = user.model_dump()
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
    for key, value in payload.items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
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
    for key, value in group.model_dump().items():
        setattr(db_group, key, value)
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


def _ensure_no_time_overlap(
    db: Session, payload: dict, *, exclude_id: Optional[int] = None
) -> None:
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
    for existing in query.all():
        existing_start, existing_end = _entry_bounds(
            existing.work_date, existing.start_time, existing.end_time, existing.is_open
        )
        if _intervals_overlap(new_start, new_end, existing_start, existing_end):
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


def create_time_entry(db: Session, entry: schemas.TimeEntryCreate) -> models.TimeEntry:
    payload = entry.model_dump()
    if payload.get("break_started_at") and not payload.get("is_open"):
        payload["break_started_at"] = None
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


def _normalize_time(moment: datetime) -> datetime:
    return moment.replace(microsecond=0)


def start_running_entry(
    db: Session,
    *,
    user_id: int,
    started_at: datetime,
    company_id: Optional[int] = None,
    notes: str = "",
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
    query = db.query(models.TimeEntry).order_by(
        models.TimeEntry.work_date.desc(), models.TimeEntry.start_time.desc()
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


def update_time_entry(db: Session, entry_id: int, entry: schemas.TimeEntryCreate) -> Optional[models.TimeEntry]:
    db_entry = get_time_entry(db, entry_id)
    if not db_entry:
        return None
    payload = entry.model_dump()
    payload["break_started_at"] = None
    payload["is_open"] = False
    _ensure_no_time_overlap(db, payload, exclude_id=entry_id)
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


def get_holiday_dates_in_range(
    db: Session,
    start: date,
    end: date,
    region: Optional[str] = None,
) -> Set[date]:
    query = (
        db.query(models.Holiday.date)
        .filter(models.Holiday.date >= start)
        .filter(models.Holiday.date <= end)
    )
    if region:
        query = query.filter(or_(models.Holiday.region == region, models.Holiday.region == "DE"))
    results = query.all()
    return {row[0] for row in results}


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

def get_company(db: Session, company_id: int) -> Optional[models.Company]:
    return db.query(models.Company).filter(models.Company.id == company_id).first()


def get_companies(db: Session) -> List[models.Company]:
    return db.query(models.Company).order_by(models.Company.name).all()


def get_company_by_name(db: Session, name: str) -> Optional[models.Company]:
    return db.query(models.Company).filter(models.Company.name == name).first()


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
    if db_company.time_entries:
        return False
    db.delete(db_company)
    db.commit()
    return True
