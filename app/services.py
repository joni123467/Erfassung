from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy.orm import Session

from . import crud, models, schemas


def _count_workdays(year: int, month: int) -> int:
    last_day = monthrange(year, month)[1]
    return sum(
        1
        for day in range(1, last_day + 1)
        if date(year, month, day).weekday() < 5
    )


def calculate_monthly_target_minutes(user: models.User | None, year: int, month: int) -> int:
    if not user:
        return 0
    workdays = _count_workdays(year, month)
    if workdays <= 0:
        return 0
    weekly_minutes = user.weekly_target_minutes
    if weekly_minutes <= 0:
        return 0
    daily_minutes = weekly_minutes / 5
    return int(round(workdays * daily_minutes))


def calculate_dashboard_metrics(
    db: Session, user_id: int, reference_date: date | None = None
) -> schemas.DashboardMetrics:
    reference = reference_date or date.today()
    month_start = reference.replace(day=1)
    month_end = date(reference.year, reference.month, monthrange(reference.year, reference.month)[1])
    entries = crud.get_time_entries_for_user(
        db,
        user_id,
        start=month_start,
        end=month_end,
        statuses=[models.TimeEntryStatus.APPROVED],
    )
    user = crud.get_user(db, user_id)
    total_work = sum(entry.worked_minutes for entry in entries)
    target_minutes = calculate_monthly_target_minutes(user, reference.year, reference.month)
    total_overtime = total_work - target_minutes
    pending_vacations = (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.user_id == user_id)
        .filter(models.VacationRequest.status == models.VacationStatus.PENDING)
        .count()
    )
    region = crud.get_default_holiday_region(db)
    upcoming_holidays = crud.get_upcoming_holidays(db, region, limit=5)
    return schemas.DashboardMetrics(
        total_work_minutes=total_work,
        total_overtime_minutes=total_overtime,
        target_minutes=target_minutes,
        pending_vacations=pending_vacations,
        upcoming_holidays=upcoming_holidays,
    )
