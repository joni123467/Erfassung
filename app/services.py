from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import crud, models, schemas


def calculate_dashboard_metrics(db: Session, user_id: int) -> schemas.DashboardMetrics:
    entries = crud.get_time_entries_for_user(db, user_id)
    total_work = sum(entry.worked_minutes for entry in entries)
    total_overtime = sum(entry.overtime_minutes for entry in entries)
    pending_vacations = (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.user_id == user_id)
        .filter(models.VacationRequest.status == models.VacationStatus.PENDING)
        .count()
    )
    upcoming_holidays = (
        db.query(models.Holiday)
        .filter(models.Holiday.date >= date.today())
        .order_by(models.Holiday.date)
        .limit(5)
        .all()
    )
    return schemas.DashboardMetrics(
        total_work_minutes=total_work,
        total_overtime_minutes=total_overtime,
        pending_vacations=pending_vacations,
        upcoming_holidays=upcoming_holidays,
    )
