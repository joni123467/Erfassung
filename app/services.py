from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from . import crud, models, schemas


_SCHEDULE_FIELDS = (
    "monday_minutes", "tuesday_minutes", "wednesday_minutes",
    "thursday_minutes", "friday_minutes", "saturday_minutes", "sunday_minutes",
)


def target_minutes_for_date(user: models.User | None, day: date) -> int:
    """Historisch gültige Sollzeit; ohne Plan exakt das bisherige Mo–Fr-Verhalten."""
    if not user:
        return 0
    schedules = getattr(user, "work_schedules", ()) or ()
    applicable = [
        item for item in schedules
        if item.valid_from <= day and (item.valid_until is None or item.valid_until >= day)
    ]
    if applicable:
        plan = max(applicable, key=lambda item: item.valid_from)
        return max(0, int(getattr(plan, _SCHEDULE_FIELDS[day.weekday()]) or 0))
    return int(round(user.daily_target_minutes or 0)) if day.weekday() < 5 else 0


def calculate_monthly_target_minutes(user: models.User | None, year: int, month: int) -> int:
    if not user:
        return 0
    return sum(
        target_minutes_for_date(user, date(year, month, day))
        for day in range(1, monthrange(year, month)[1] + 1)
    )


def calculate_required_vacation_minutes(
    user: models.User | None, start: date, end: date
) -> int:
    """Sollminuten eines Zeitraums nach historisch gültigem Arbeitszeitplan.

    **Nicht für die Urlaubsanrechnung verwenden.** Diese Funktion kennt keine
    halben Tage – sie sieht den Antrag gar nicht, nur den Zeitraum. Genau
    daran krankte bis 0.14.2 die Adminauswertung: Ein Antrag über zwei halbe
    Tage erschien mit 16:00 statt 8:00 Stunden.

    Für Urlaub gilt :func:`vacation_minutes_in_range` (Minuten) bzw.
    :func:`vacation_days_in_range` (Tage). Der Name ist historisch; geblieben
    ist die Funktion als Sollzeitrechnung, siehe
    :func:`calculate_target_minutes_in_range`.
    """
    if not user:
        return 0
    current = start
    total = 0
    while current <= end:
        total += target_minutes_for_date(user, current)
        current += timedelta(days=1)
    return total


def holiday_credit_minutes(
    user: models.User | None, holidays: Iterable[date] | None, start: date, end: date
) -> int:
    """Gutschrift für gesetzliche Feiertage im Zeitraum.

    Ein Feiertag ist ein bezahlter Ausfalltag: Er wird mit der **individuellen
    Tagessollzeit** gutgeschrieben, genau wie ein Urlaubstag. Ohne diese
    Gutschrift entstünde für jeden Feiertag ein Minus in Höhe eines
    Arbeitstages, obwohl niemand etwas versäumt hat.

    Gezählt werden nur Feiertage von **Montag bis Freitag** – die Sollzeit
    kennt ohnehin nur diese Tage, ein Feiertag am Wochenende fällt also auf
    keinen Arbeitstag und ist nichts gutzuschreiben.
    """
    if not user or not holidays:
        return 0
    return sum(
        target_minutes_for_date(user, day)
        for day in holidays if start <= day <= end
    )


def holiday_credit_by_day(
    user: models.User | None, holidays: Iterable[date] | None, start: date, end: date
) -> dict[date, int]:
    """Feiertagsgutschrift je Tag – für Tages- und Wochenansichten."""
    if not user or not holidays:
        return {}
    return {
        day: target_minutes_for_date(user, day)
        for day in holidays
        if start <= day <= end and target_minutes_for_date(user, day) > 0
    }


def half_day_factor(vacation: models.VacationRequest, day: date) -> float:
    """Anteil, mit dem ``day`` in diesen Urlaubsantrag eingeht.

    ``1.0`` für einen ganzen Tag, ``0.5`` für einen halben. Ein eintägiger
    Antrag gilt als halb, sobald eines der beiden Kennzeichen gesetzt ist –
    dort gibt es kein „erster“ und „letzter“ Tag.
    """
    if vacation.start_date == vacation.end_date:
        return 0.5 if (vacation.half_day_start or vacation.half_day_end) else 1.0
    if day == vacation.start_date and vacation.half_day_start:
        return 0.5
    if day == vacation.end_date and vacation.half_day_end:
        return 0.5
    return 1.0


def _counts_as_vacation_day(
    day: date, holidays: Optional[frozenset[date]]
) -> bool:
    """Zählt ``day`` als Urlaubstag?

    Nein an Wochenenden – und nein an gesetzlichen Feiertagen: Ein Feiertag
    im Urlaub verbraucht **keinen** Urlaubstag. Er wird ohnehin über
    :func:`holiday_credit_minutes` gutgeschrieben; würde er zusätzlich vom
    Urlaubsanspruch abgehen, wäre der Tag doppelt gezählt und der Anspruch zu
    Unrecht kleiner.
    """
    if day.weekday() >= 5:
        return False
    return not (holidays and day in holidays)


def vacation_minutes_in_range(
    user: models.User | None,
    vacation: models.VacationRequest,
    start: date,
    end: date,
    holidays: Optional[Iterable[date]] = None,
) -> int:
    """Urlaubsminuten dieses Antrags im Zeitraum – halbe Tage eingerechnet.

    Zählt wie die Sollzeit nur Montag bis Freitag; halbe Tage gehen mit der
    Hälfte der Tagessollzeit ein. Gesetzliche Feiertage bleiben außen vor –
    sie werden getrennt gutgeschrieben (siehe :func:`_counts_as_vacation_day`).
    """
    if not user:
        return 0
    overlap_start = max(start, vacation.start_date)
    overlap_end = min(end, vacation.end_date)
    if overlap_start > overlap_end:
        return 0
    holiday_set = frozenset(holidays) if holidays else None
    total = 0.0
    current = overlap_start
    while current <= overlap_end:
        day_minutes = target_minutes_for_date(user, current)
        if day_minutes > 0 and not (holiday_set and current in holiday_set):
            total += day_minutes * half_day_factor(vacation, current)
        current += timedelta(days=1)
    return int(round(total))


def vacation_days(
    vacation: models.VacationRequest,
    holidays: Optional[Iterable[date]] = None,
    user: models.User | None = None,
) -> float:
    """Angerechnete Arbeitstage eines Antrags, halbe Tage als 0,5.

    Gesetzliche Feiertage verbrauchen keinen Urlaubstag.
    """
    holiday_set = frozenset(holidays) if holidays else None
    total = 0.0
    current = vacation.start_date
    while current <= vacation.end_date:
        is_workday = target_minutes_for_date(user, current) > 0 if user else current.weekday() < 5
        if is_workday and not (holiday_set and current in holiday_set):
            total += half_day_factor(vacation, current)
        current += timedelta(days=1)
    return total


def vacation_days_in_range(
    vacation: models.VacationRequest,
    start: date,
    end: date,
    holidays: Optional[Iterable[date]] = None,
    user: models.User | None = None,
) -> float:
    """Urlaubstage dieses Antrags **im Zeitraum** – halbe Tage als 0,5.

    Wie :func:`vacation_days`, aber auf einen Ausschnitt begrenzt. Nötig für
    Auswertungen über einen Monat, in den ein Antrag hineinragt.
    """
    overlap_start = max(start, vacation.start_date)
    overlap_end = min(end, vacation.end_date)
    if overlap_start > overlap_end:
        return 0.0
    holiday_set = frozenset(holidays) if holidays else None
    total = 0.0
    current = overlap_start
    while current <= overlap_end:
        is_workday = target_minutes_for_date(user, current) > 0 if user else current.weekday() < 5
        if is_workday and not (holiday_set and current in holiday_set):
            total += half_day_factor(vacation, current)
        current += timedelta(days=1)
    return total


def calculate_target_minutes_in_range(
    user: models.User | None, start: date, end: date
) -> int:
    """Sollminuten eines Zeitraums nach dem gültigen Arbeitszeitplan.

    Verwendet dieselbe Tagesregel wie die Urlaubsgutschrift, damit Soll und Ist
    in Dashboard, Berichten und Exporten vergleichbar bleiben.
    """
    return calculate_required_vacation_minutes(user, start, end)


def calculate_vacation_overtime_in_range(
    user: models.User | None,
    vacations: list[models.VacationRequest],
    start: date,
    end: date,
    holidays: Optional[Iterable[date]] = None,
) -> int:
    if not user or not vacations:
        return 0
    total = 0
    for vacation in vacations:
        if not vacation.use_overtime:
            continue
        if vacation.status != models.VacationStatus.APPROVED:
            continue
        total += vacation_minutes_in_range(user, vacation, start, end, holidays)
    return total


def calculate_approved_vacation_minutes(
    user: models.User | None,
    vacations: list[models.VacationRequest],
    start: date,
    end: date,
    holidays: Optional[Iterable[date]] = None,
) -> int:
    if not user or not vacations:
        return 0
    total = 0
    for vacation in vacations:
        if vacation.status != models.VacationStatus.APPROVED:
            continue
        if getattr(vacation, "absence_type_key", "vacation") in {"parental", "unpaid"}:
            continue
        total += vacation_minutes_in_range(user, vacation, start, end, holidays)
    return total


def calculate_vacation_minutes_by_day(
    user: models.User | None,
    vacations: list[models.VacationRequest],
    start: date,
    end: date,
    holidays: Optional[Iterable[date]] = None,
) -> dict[date, int]:
    if not user or not vacations:
        return {}
    holiday_set = frozenset(holidays) if holidays else None
    totals: dict[date, int] = {}
    for vacation in vacations:
        if vacation.status != models.VacationStatus.APPROVED:
            continue
        if getattr(vacation, "absence_type_key", "vacation") in {"parental", "unpaid"}:
            continue
        overlap_start = max(start, vacation.start_date)
        overlap_end = min(end, vacation.end_date)
        if overlap_start > overlap_end:
            continue
        current = overlap_start
        while current <= overlap_end:
            day_minutes = target_minutes_for_date(user, current)
            if day_minutes > 0 and not (holiday_set and current in holiday_set):
                share = int(round(day_minutes * half_day_factor(vacation, current)))
                totals[current] = totals.get(current, 0) + share
            current += timedelta(days=1)
    return totals


def calculate_vacation_summary(
    user: models.User | None,
    vacations: List[models.VacationRequest],
    year: int,
    holidays: Optional[Iterable[date]] = None,
) -> schemas.VacationSummary:
    """Urlaubskonto eines Jahres.

    ``holidays`` sorgt dafür, dass ein Feiertag im Urlaub keinen Urlaubstag
    verbraucht. Wird nichts übergeben, zählt jeder Werktag – dann fehlt diese
    Verrechnung.
    """
    if not user:
        return schemas.VacationSummary(
            total_days=0.0,
            remaining_days=0.0,
            used_days=0.0,
            planned_days=0.0,
            carryover_days=0.0,
        )
    base_days = float(user.annual_vacation_days or 0)
    today = date.today()
    base_days += sum(
        float(item.days or 0)
        for item in (getattr(user, "vacation_entitlement_entries", ()) or ())
        if item.year == year and (item.expires_on is None or item.expires_on >= today)
    )
    carryover_days = float(user.vacation_carryover_days or 0) if user.vacation_carryover_enabled else 0.0
    # Ohne jede gepflegte Sollzeit gibt es keinen Arbeitstag, gegen den sich
    # Urlaub verrechnen ließe. Der Arbeitszeitplan zählt dabei mit: Er kann
    # Arbeitstage vorsehen, ohne dass Wochenstunden hinterlegt sind.
    has_target = bool(user.weekly_target_minutes) or bool(
        getattr(user, "work_schedules", ()) or ()
    )
    if not has_target:
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
    used_days = 0.0
    planned_days = 0.0
    for vacation in vacations:
        if getattr(vacation, "absence_type_key", "vacation") != "vacation":
            continue
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
        # Urlaubstage direkt zählen statt Minuten durch eine pauschale
        # Tagessollzeit zu teilen. Bei ungleichen Wochentagen ging die Division
        # nicht auf: Ein Plan über vier Tage zu je acht Stunden ergibt 32
        # Wochenstunden, der Schnitt daraus 6:24 Std – eine Urlaubswoche zählte
        # damit fünf statt vier Tage. ``vacation_days_in_range`` kennt den Plan,
        # die halben Tage und die Feiertage.
        days = vacation_days_in_range(
            vacation, period_start, period_end, holidays, user
        )
        if vacation.status == models.VacationStatus.APPROVED:
            used_days += days
        elif vacation.status == models.VacationStatus.PENDING:
            planned_days += days
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
    # Feiertage einmal je Monat holen und überall durchreichen: Sie schreiben
    # die Tagessollzeit gut und verbrauchen zugleich keinen Urlaubstag.
    holidays = crud.get_holiday_dates_in_range(db, month_start, month_end)
    holiday_minutes = holiday_credit_minutes(user, holidays, month_start, month_end)
    overtime_taken = calculate_vacation_overtime_in_range(
        user, vacations, month_start, month_end, holidays
    )
    vacation_minutes = calculate_approved_vacation_minutes(
        user, vacations, month_start, month_end, holidays
    )
    target_minutes = calculate_monthly_target_minutes(user, reference.year, reference.month)
    effective_minutes = total_work + vacation_minutes + holiday_minutes
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
    region = crud.get_default_holiday_region(db)
    upcoming_holidays = crud.get_upcoming_holidays(db, region, limit=5)
    year_holidays = crud.get_holiday_dates_in_range(
        db, date(reference.year, 1, 1), date(reference.year, 12, 31)
    )
    vacation_summary = calculate_vacation_summary(
        user, vacations, reference.year, year_holidays
    )
    return schemas.DashboardMetrics(
        total_work_minutes=total_work,
        vacation_minutes=vacation_minutes,
        holiday_minutes=holiday_minutes,
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
