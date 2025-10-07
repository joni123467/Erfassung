from __future__ import annotations

from datetime import date
from typing import Iterable, List, Optional

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
    db_user = models.User(**user.model_dump())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def update_user(db: Session, user_id: int, user: schemas.UserUpdate) -> Optional[models.User]:
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    for key, value in user.model_dump().items():
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


def create_time_entry(db: Session, entry: schemas.TimeEntryCreate) -> models.TimeEntry:
    db_entry = models.TimeEntry(**entry.model_dump())
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry


def get_time_entry(db: Session, entry_id: int) -> Optional[models.TimeEntry]:
    return db.query(models.TimeEntry).filter(models.TimeEntry.id == entry_id).first()


def get_time_entries_for_user(db: Session, user_id: int, start: Optional[date] = None, end: Optional[date] = None) -> List[models.TimeEntry]:
    query = db.query(models.TimeEntry).filter(models.TimeEntry.user_id == user_id)
    if start:
        query = query.filter(models.TimeEntry.work_date >= start)
    if end:
        query = query.filter(models.TimeEntry.work_date <= end)
    return query.order_by(models.TimeEntry.work_date).all()


def get_time_entries(db: Session, user_id: Optional[int] = None) -> List[models.TimeEntry]:
    query = db.query(models.TimeEntry).order_by(
        models.TimeEntry.work_date.desc(), models.TimeEntry.start_time.desc()
    )
    if user_id:
        query = query.filter(models.TimeEntry.user_id == user_id)
    return query.all()


def update_time_entry(db: Session, entry_id: int, entry: schemas.TimeEntryCreate) -> Optional[models.TimeEntry]:
    db_entry = get_time_entry(db, entry_id)
    if not db_entry:
        return None
    for key, value in entry.model_dump().items():
        setattr(db_entry, key, value)
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
    db_vacation = models.VacationRequest(**vacation.model_dump())
    db.add(db_vacation)
    db.commit()
    db.refresh(db_vacation)
    return db_vacation


def update_vacation_status(db: Session, vacation_id: int, status: str) -> Optional[models.VacationRequest]:
    db_vacation = db.query(models.VacationRequest).filter(models.VacationRequest.id == vacation_id).first()
    if not db_vacation:
        return None
    db_vacation.status = status
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
        existing = db.query(models.Holiday).filter(models.Holiday.date == holiday.date).first()
        if existing:
            existing.name = holiday.name
            existing.region = holiday.region
            stored.append(existing)
        else:
            stored.append(create_holiday(db, holiday))
    db.commit()
    return stored

def get_company(db: Session, company_id: int) -> Optional[models.Company]:
    return db.query(models.Company).filter(models.Company.id == company_id).first()


def get_companies(db: Session) -> List[models.Company]:
    return db.query(models.Company).order_by(models.Company.name).all()


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
