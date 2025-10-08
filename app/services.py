from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import crud, models, schemas


def calculate_dashboard_metrics(db: Session, user_id: int) -> schemas.DashboardMetrics:
    entries = crud.get_time_entries_for_user(
        db,
        user_id,
        statuses=[models.TimeEntryStatus.APPROVED],
    )
    user = crud.get_user(db, user_id)
    total_work = sum(entry.worked_minutes for entry in entries)
    total_overtime = sum(entry.overtime_minutes for entry in entries)
    worked_days = {entry.work_date for entry in entries}
    target_minutes = len(worked_days) * (user.standard_daily_minutes if user else 0)
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
