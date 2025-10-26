from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from typing import Dict, Iterable, List, Optional, Set

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


def calculate_required_vacation_minutes(
    user: models.User | None,
    start: date,
    end: date,
    holiday_dates: Iterable[date] | None = None,
) -> int:
    if not user:
        return 0
    daily_minutes = int(round(user.daily_target_minutes or 0))
    if daily_minutes <= 0:
        return 0
    current = start
    total = 0
    skipped: Set[date] = set(holiday_dates or [])
    while current <= end:
        if current.weekday() < 5 and current not in skipped:
            total += daily_minutes
        current += timedelta(days=1)
    return total


def calculate_vacation_overtime_in_range(
    user: models.User | None,
    vacations: list[models.VacationRequest],
    start: date,
    end: date,
    holiday_dates: Iterable[date] | None = None,
) -> int:
    if not user or not vacations:
        return 0
    total = 0
    for vacation in vacations:
        if not vacation.use_overtime:
            continue
        if vacation.status != models.VacationStatus.APPROVED:
            continue
        overlap_start = max(start, vacation.start_date)
        overlap_end = min(end, vacation.end_date)
        if overlap_start > overlap_end:
            continue
        total += calculate_required_vacation_minutes(
            user,
            overlap_start,
            overlap_end,
            holiday_dates,
        )
    return total


def calculate_approved_vacation_minutes(
    user: models.User | None,
    vacations: list[models.VacationRequest],
    start: date,
    end: date,
    holiday_dates: Iterable[date] | None = None,
) -> int:
    if not user or not vacations:
        return 0
    total = 0
    for vacation in vacations:
        if vacation.status != models.VacationStatus.APPROVED:
            continue
        overlap_start = max(start, vacation.start_date)
        overlap_end = min(end, vacation.end_date)
        if overlap_start > overlap_end:
            continue
        total += calculate_required_vacation_minutes(
            user,
            overlap_start,
            overlap_end,
            holiday_dates,
        )
    return total


def calculate_vacation_minutes_by_day(
    user: models.User | None,
    vacations: list[models.VacationRequest],
    start: date,
    end: date,
    holiday_dates: Iterable[date] | None = None,
) -> dict[date, int]:
    if not user or not vacations:
        return {}
    daily_minutes = int(round(user.daily_target_minutes or 0))
    if daily_minutes <= 0:
        return {}
    totals: Dict[date, int] = {}
    skipped: Set[date] = set(holiday_dates or [])
    for vacation in vacations:
        if vacation.status != models.VacationStatus.APPROVED:
            continue
        overlap_start = max(start, vacation.start_date)
        overlap_end = min(end, vacation.end_date)
        if overlap_start > overlap_end:
            continue
        current = overlap_start
        while current <= overlap_end:
            if current.weekday() < 5 and current not in skipped:
                totals[current] = totals.get(current, 0) + daily_minutes
            current += timedelta(days=1)
    return totals


def calculate_vacation_summary(
    user: models.User | None,
    vacations: List[models.VacationRequest],
    year: int,
    holiday_dates: Iterable[date] | None = None,
) -> schemas.VacationSummary:
    if not user:
        return schemas.VacationSummary(
            total_days=0.0,
            remaining_days=0.0,
            used_days=0.0,
            planned_days=0.0,
            carryover_days=0.0,
        )
    daily_minutes = int(round(user.daily_target_minutes or 0))
    base_days = float(user.annual_vacation_days or 0)
    carryover_days = float(user.vacation_carryover_days or 0) if user.vacation_carryover_enabled else 0.0
    if daily_minutes <= 0:
        total_days = base_days + carryover_days
        return schemas.VacationSummary(
            total_days=total_days,
            remaining_days=total_days,
            used_days=0.0,
            planned_days=0.0,
            carryover_days=carryover_days,
        )
    period_start = date(year, 1, 1)
    period_end = date(year, 12, 31)
    used_minutes = 0
    planned_minutes = 0
    skipped: Set[date] = set(holiday_dates or [])
    for vacation in vacations:
        if vacation.use_overtime:
            continue
        if vacation.status in (
            models.VacationStatus.CANCELLED,
            models.VacationStatus.WITHDRAW_REQUESTED,
        ):
            continue
        overlap_start = max(period_start, vacation.start_date)
        overlap_end = min(period_end, vacation.end_date)
        if overlap_start > overlap_end:
            continue
        minutes = calculate_required_vacation_minutes(
            user,
            overlap_start,
            overlap_end,
            skipped,
        )
        if vacation.status == models.VacationStatus.APPROVED:
            used_minutes += minutes
        elif vacation.status == models.VacationStatus.PENDING:
            planned_minutes += minutes
    used_days = used_minutes / daily_minutes if daily_minutes else 0.0
    planned_days = planned_minutes / daily_minutes if daily_minutes else 0.0
    total_days = base_days + carryover_days
    remaining_days = max(total_days - used_days - planned_days, 0.0)
    return schemas.VacationSummary(
        total_days=round(total_days, 2),
        remaining_days=round(remaining_days, 2),
        used_days=round(used_days, 2),
        planned_days=round(planned_days, 2),
        carryover_days=round(carryover_days, 2),
    )


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
    vacations = crud.get_vacations_for_user(db, user_id)
    region = crud.get_default_holiday_region(db)
    holiday_dates = crud.get_holiday_dates_in_range(db, month_start, month_end, region)
    overtime_taken = calculate_vacation_overtime_in_range(
        user,
        vacations,
        month_start,
        month_end,
        holiday_dates,
    )
    vacation_minutes = calculate_approved_vacation_minutes(
        user,
        vacations,
        month_start,
        month_end,
        holiday_dates,
    )
    target_minutes = calculate_monthly_target_minutes(user, reference.year, reference.month)
    effective_minutes = total_work + vacation_minutes
    balance = effective_minutes - target_minutes
    total_overtime = max(balance, 0)
    total_undertime = max(-balance, 0) if user and user.time_account_enabled else 0
    if not (user and user.time_account_enabled):
        total_undertime = 0
        total_overtime = max(balance, 0)
    overtime_limit = int(getattr(user, "monthly_overtime_limit_minutes", 0) or 0) if user else 0
    overtime_limit_exceeded = bool(overtime_limit and total_overtime > overtime_limit)
    overtime_limit_remaining = (
        max(overtime_limit - total_overtime, 0) if overtime_limit and not overtime_limit_exceeded else 0
    )
    overtime_limit_excess = max(total_overtime - overtime_limit, 0) if overtime_limit_exceeded else 0
    pending_vacations = (
        db.query(models.VacationRequest)
        .filter(models.VacationRequest.user_id == user_id)
        .filter(
            models.VacationRequest.status.in_(
                [
                    models.VacationStatus.PENDING,
                    models.VacationStatus.WITHDRAW_REQUESTED,
                ]
            )
        )
        .count()
    )
    upcoming_holidays = crud.get_upcoming_holidays(db, region, limit=5)
    summary_holidays = crud.get_holiday_dates_in_range(
        db,
        date(reference.year, 1, 1),
        date(reference.year, 12, 31),
        region,
    )
    vacation_summary = calculate_vacation_summary(
        user,
        vacations,
        reference.year,
        summary_holidays,
    )
    return schemas.DashboardMetrics(
        total_work_minutes=total_work,
        vacation_minutes=vacation_minutes,
        total_overtime_minutes=total_overtime,
        total_undertime_minutes=total_undertime,
        target_minutes=target_minutes,
        overtime_taken_minutes=overtime_taken,
        pending_vacations=pending_vacations,
        upcoming_holidays=upcoming_holidays,
        vacation_summary=vacation_summary,
        overtime_limit_minutes=overtime_limit,
        overtime_limit_remaining_minutes=overtime_limit_remaining,
        overtime_limit_exceeded=overtime_limit_exceeded,
        overtime_limit_excess_minutes=overtime_limit_excess,
    )


def calculate_available_overtime_minutes(
    db: Session,
    user: models.User | None,
    until: date | None = None,
) -> int:
    if not user:
        return 0
    target_date = until or date.today()
    approved_entries = crud.get_time_entries_for_user(
        db,
        user.id,
        end=target_date,
        statuses=[models.TimeEntryStatus.APPROVED],
    )
    vacations = [
        vacation
        for vacation in crud.get_vacations_for_user(db, user.id)
        if vacation.status == models.VacationStatus.APPROVED
        and vacation.start_date <= target_date
    ]
    if not approved_entries and not vacations:
        return 0
    start_candidates = []
    if approved_entries:
        start_candidates.append(min(entry.work_date for entry in approved_entries))
    if vacations:
        start_candidates.append(min(vacation.start_date for vacation in vacations))
    start_date = min(start_candidates) if start_candidates else target_date
    region = crud.get_default_holiday_region(db)
    holiday_dates = crud.get_holiday_dates_in_range(db, start_date, target_date, region)
    daily_minutes = int(round(user.daily_target_minutes or 0))
    work_minutes = sum(entry.worked_minutes for entry in approved_entries)
    regular_vacation_minutes = 0
    overtime_vacation_minutes = 0
    for vacation in vacations:
        overlap_start = max(start_date, vacation.start_date)
        overlap_end = min(target_date, vacation.end_date)
        if overlap_start > overlap_end:
            continue
        credited = calculate_required_vacation_minutes(
            user,
            overlap_start,
            overlap_end,
            holiday_dates,
        )
        if vacation.use_overtime:
            overtime_vacation_minutes += credited
        else:
            regular_vacation_minutes += credited
    target_total = 0
    if daily_minutes > 0:
        day = start_date
        while day <= target_date:
            if day.weekday() < 5 and day not in holiday_dates:
                target_total += daily_minutes
            day += timedelta(days=1)
    balance = work_minutes + regular_vacation_minutes - target_total - overtime_vacation_minutes
    return balance
