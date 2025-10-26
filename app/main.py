from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time
from typing import List, Optional
from urllib.parse import urlencode, urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import crud, database, holiday_calculator, models, schemas, services
from .excel_export import export_time_entries
from .pdf_export import export_time_overview_pdf

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Erfassung", description="Zeiterfassung mit Überstunden & Urlaub")

app.add_middleware(SessionMiddleware, secret_key="zeit-erfassung-secret-key")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.utcnow


def _format_minutes(value: object) -> str:
    if value is None:
        return "00:00"
    try:
        minutes = int(round(float(value)))
    except (TypeError, ValueError):
        return "00:00"
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    hours, remainder = divmod(minutes, 60)
    return f"{sign}{hours:02d}:{remainder:02d}"


templates.env.filters["format_minutes"] = _format_minutes

HOLIDAY_STATE_CHOICES = sorted(holiday_calculator.GERMAN_STATES.items(), key=lambda item: item[1])
HOLIDAY_STATE_CODES = set(holiday_calculator.GERMAN_STATES.keys())


def get_logged_in_user(request: Request, db: Session) -> Optional[models.User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return crud.get_user(db, user_id)


def ensure_schema() -> None:
    with database.engine.connect() as connection:
        inspector = inspect(connection)
        table_names = inspector.get_table_names()
        if "companies" not in table_names:
            models.Base.metadata.tables["companies"].create(bind=connection)
        if "time_entries" in table_names:
            columns = {column["name"] for column in inspector.get_columns("time_entries")}
            if "company_id" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN company_id INTEGER"))
            if "break_started_at" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN break_started_at TIME"))
            if "is_open" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN is_open INTEGER DEFAULT 0"))
            if "status" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN status VARCHAR DEFAULT 'approved'"))
            if "is_manual" not in columns:
                connection.execute(text("ALTER TABLE time_entries ADD COLUMN is_manual INTEGER DEFAULT 0"))
            connection.execute(text("UPDATE time_entries SET is_open = 0 WHERE is_open IS NULL"))
        if "users" in table_names:
            columns = {column["name"] for column in inspector.get_columns("users")}
            if "standard_weekly_hours" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN standard_weekly_hours FLOAT DEFAULT 40"))
                connection.execute(
                    text(
                        "UPDATE users SET standard_weekly_hours = COALESCE(standard_daily_minutes, 480) * 5.0 / 60.0"
                    )
                )
            if "time_account_enabled" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN time_account_enabled BOOLEAN DEFAULT 0")
                )
            if "overtime_vacation_enabled" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN overtime_vacation_enabled BOOLEAN DEFAULT 0")
                )
            if "annual_vacation_days" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN annual_vacation_days INTEGER DEFAULT 30")
                )
            if "vacation_carryover_enabled" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN vacation_carryover_enabled BOOLEAN DEFAULT 0")
                )
            if "vacation_carryover_days" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN vacation_carryover_days INTEGER DEFAULT 0")
                )
            if "rfid_tag" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN rfid_tag VARCHAR"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_rfid_tag ON users(rfid_tag)"))
        if "groups" in table_names:
            columns = {column["name"] for column in inspector.get_columns("groups")}
            if "can_manage_users" not in columns:
                connection.execute(text("ALTER TABLE groups ADD COLUMN can_manage_users BOOLEAN DEFAULT 0"))
            if "can_manage_vacations" not in columns:
                connection.execute(text("ALTER TABLE groups ADD COLUMN can_manage_vacations BOOLEAN DEFAULT 0"))
            if "can_approve_manual_entries" not in columns:
                connection.execute(
                    text("ALTER TABLE groups ADD COLUMN can_approve_manual_entries BOOLEAN DEFAULT 0")
                )
            if "can_create_companies" not in columns:
                connection.execute(
                    text("ALTER TABLE groups ADD COLUMN can_create_companies BOOLEAN DEFAULT 0")
                )
        if "holidays" in table_names:
            index_rows = connection.execute(text("PRAGMA index_list('holidays')")).fetchall()
            legacy_unique_index = None
            for row in index_rows:
                name = row["name"] if "name" in row.keys() else row[1]
                is_unique = row["unique"] if "unique" in row.keys() else row[2]
                if not is_unique or not str(name).startswith("sqlite_autoindex"):
                    continue
                index_info = connection.execute(text(f"PRAGMA index_info('{name}')")).fetchall()
                columns = [info["name"] if "name" in info.keys() else info[2] for info in index_info]
                if columns == ["date"]:
                    legacy_unique_index = name
                    break
            if legacy_unique_index:
                connection.execute(text("DROP TABLE IF EXISTS holidays_migrated"))
                connection.execute(
                    text(
                        """
CREATE TABLE holidays_migrated (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    date DATE NOT NULL,
    region VARCHAR DEFAULT 'DE',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, region)
)
"""
                    )
                )
                connection.execute(
                    text(
                        """
INSERT INTO holidays_migrated (id, name, date, region, created_at)
SELECT id, name, date, region, created_at FROM holidays
"""
                    )
                )
                connection.execute(text("DROP TABLE holidays"))
                connection.execute(text("ALTER TABLE holidays_migrated RENAME TO holidays"))
        if "vacation_requests" in table_names:
            columns = {column["name"] for column in inspector.get_columns("vacation_requests")}
            if "use_overtime" not in columns:
                connection.execute(
                    text("ALTER TABLE vacation_requests ADD COLUMN use_overtime BOOLEAN DEFAULT 0")
                )
            if "overtime_minutes" not in columns:
                connection.execute(
                    text("ALTER TABLE vacation_requests ADD COLUMN overtime_minutes INTEGER DEFAULT 0")
                )


def _sanitize_next(next_url: str, default: str = "/time") -> str:
    if not next_url:
        return default
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return default
    path = parsed.path or default
    if not path.startswith("/"):
        return default
    return path


def _build_redirect(path: str, **params: str) -> str:
    query = urlencode({key: value for key, value in params.items() if value})
    if query:
        return f"{path}?{query}"
    return path


def _resolve_month_period(month_param: Optional[str]) -> tuple[date, date, date]:
    try:
        if month_param:
            year, month = map(int, month_param.split("-"))
            selected_month = date(year, month, 1)
        else:
            selected_month = date.today().replace(day=1)
    except ValueError:
        selected_month = date.today().replace(day=1)
    last_day = monthrange(selected_month.year, selected_month.month)[1]
    start_date = selected_month
    end_date = date(selected_month.year, selected_month.month, last_day)
    return selected_month, start_date, end_date


def _aggregate_company_totals(source_entries: List[models.TimeEntry]):
    totals: dict[str, dict[str, object]] = {}
    for entry in source_entries:
        key = "none" if entry.company_id is None else str(entry.company_id)
        record = totals.setdefault(
            key,
            {
                "company_id": entry.company_id,
                "name": entry.company.name if entry.company else "Allgemein",
                "minutes": 0,
                "count": 0,
            },
        )
        record["minutes"] = int(record["minutes"]) + entry.worked_minutes
        record["count"] = int(record["count"]) + 1
    return sorted(totals.values(), key=lambda item: str(item["name"]).lower())


@app.on_event("startup")
def ensure_seed_data():
    ensure_schema()
    db = database.SessionLocal()
    try:
        if not crud.get_groups(db):
            admin_group = crud.create_group(
                db,
                schemas.GroupCreate(
                    name="Administration",
                    is_admin=True,
                    can_manage_users=True,
                    can_manage_vacations=True,
                    can_approve_manual_entries=True,
                    can_create_companies=True,
                ),
            )
        else:
            admin_group = db.query(models.Group).filter(models.Group.is_admin == True).first()  # noqa: E712
            if admin_group:
                admin_group.can_manage_users = True
                admin_group.can_manage_vacations = True
                admin_group.can_approve_manual_entries = True
                admin_group.can_create_companies = True
                db.commit()
        if not crud.get_companies(db):
            crud.create_company(db, schemas.CompanyCreate(name="Allgemein"))
        if not crud.get_users(db):
            crud.create_user(
                db,
                schemas.UserCreate(
                    username="admin",
                    full_name="Administrator",
                    email="admin@example.com",
                    group_id=admin_group.id if admin_group else None,
                    standard_weekly_hours=40.0,
                    pin_code="0000",
                ),
            )
    finally:
        db.close()


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    response = await call_next(request)
    return response


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "user": None})


@app.post("/login")
def login_submit(request: Request, pin_code: str = Form(...), db: Session = Depends(database.get_db)):
    user = crud.get_user_by_pin(db, pin_code)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "PIN konnte nicht gefunden werden.", "user": None},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    reference_month = date.today()
    metrics = services.calculate_dashboard_metrics(db, user.id, reference_month)
    active_entry = crud.get_open_time_entry(db, user.id)
    holiday_region = crud.get_default_holiday_region(db)
    holiday_region_label = holiday_calculator.GERMAN_STATES.get(holiday_region, holiday_region)
    holidays = crud.get_holidays_for_year(db, date.today().year, holiday_region)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    companies = crud.get_companies(db)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "metrics": metrics,
            "holidays": holidays,
            "holiday_region": holiday_region,
            "holiday_region_label": holiday_region_label,
            "companies": companies,
            "message": message,
            "error": error,
            "active_entry": active_entry,
            "metrics_month": reference_month.replace(day=1),
            "can_create_companies": _can_create_companies(user),
        },
    )


@app.post("/time")
def submit_time_entry(
    request: Request,
    work_date: date = Form(...),
    start_time: time = Form(...),
    end_time: time = Form(...),
    break_minutes: int = Form(0),
    notes: str = Form(""),
    company_id: Optional[str] = Form(None),
    new_company_name: Optional[str] = Form(None),
    next_url: str = Form("/time"),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if break_minutes < 0:
        break_minutes = 0
    if end_time <= start_time:
        redirect = _build_redirect(_sanitize_next(next_url), error="Endzeit muss nach der Startzeit liegen")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    new_company_value = (new_company_name or "").strip()
    company_value: Optional[int] = None
    if new_company_value:
        if not _can_create_companies(user):
            redirect = _build_redirect(
                _sanitize_next(next_url), error="Du darfst keine neuen Firmen anlegen."
            )
            return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
        existing_company = crud.get_company_by_name(db, new_company_value)
        if existing_company:
            company_value = existing_company.id
        else:
            created_company = crud.create_company(db, schemas.CompanyCreate(name=new_company_value))
            company_value = created_company.id
    elif company_id:
        try:
            company_value = int(company_id)
        except (TypeError, ValueError):
            redirect = _build_redirect(_sanitize_next(next_url), error="Ungültige Firmenauswahl")
            return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    try:
        entry = schemas.TimeEntryCreate(
            user_id=user.id,
            company_id=company_value,
            work_date=work_date,
            start_time=start_time,
            end_time=end_time,
            break_minutes=break_minutes,
            break_started_at=None,
            is_open=False,
            notes=notes,
            status=models.TimeEntryStatus.PENDING,
            is_manual=True,
        )
        crud.create_time_entry(db, entry)
    except ValueError:
        redirect = _build_redirect(_sanitize_next(next_url), error="Ungültige Zeiteingabe")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        _sanitize_next(next_url), msg="Zeitbuchung eingereicht und wartet auf Freigabe"
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/punch")
def punch_action(
    request: Request,
    action: str = Form(...),
    company_id: Optional[str] = Form(None),
    new_company_name: Optional[str] = Form(None),
    notes: str = Form(""),
    next_url: str = Form("/dashboard"),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    target = _sanitize_next(next_url)
    active_entry = crud.get_open_time_entry(db, user.id)
    now = datetime.now()
    message = ""
    error = ""

    if action == "start_work":
        if active_entry:
            error = "Es läuft bereits eine Arbeitszeit."
        else:
            crud.start_running_entry(db, user_id=user.id, started_at=now, notes=notes.strip())
            message = "Arbeitszeit gestartet."
    elif action == "start_company":
        new_company_value = (new_company_name or "").strip()
        target_company = None
        created_company = False
        if new_company_value:
            if not _can_create_companies(user):
                error = "Du darfst keine neuen Firmen anlegen."
            else:
                existing_company = crud.get_company_by_name(db, new_company_value)
                if existing_company:
                    target_company = existing_company
                else:
                    try:
                        target_company = crud.create_company(
                            db,
                            schemas.CompanyCreate(name=new_company_value, description=""),
                        )
                        created_company = True
                    except IntegrityError:
                        db.rollback()
                        error = "Firma existiert bereits."
        else:
            if not company_id:
                error = "Bitte eine Firma auswählen oder neu anlegen."
            else:
                try:
                    company_value = int(company_id)
                except ValueError:
                    error = "Ungültige Firma ausgewählt."
                else:
                    target_company = crud.get_company(db, company_value)
                    if not target_company:
                        error = "Firma wurde nicht gefunden."
        if not error and target_company:
            if active_entry and active_entry.company_id == target_company.id:
                error = "Dieser Auftrag läuft bereits."
            else:
                previous_company = active_entry.company if active_entry else None
                if active_entry:
                    crud.finish_running_entry(db, active_entry, now)
                crud.start_running_entry(
                    db,
                    user_id=user.id,
                    started_at=now,
                    company_id=target_company.id,
                    notes=notes.strip(),
                )
                if created_company:
                    message = f"Neue Firma {target_company.name} angelegt und Auftrag gestartet."
                elif previous_company and previous_company.id != target_company.id:
                    message = f"Auftrag zu {target_company.name} gewechselt."
                else:
                    message = f"Auftrag bei {target_company.name} gestartet."
    elif action == "end_work":
        if not active_entry:
            error = "Keine laufende Arbeitszeit vorhanden."
        else:
            crud.finish_running_entry(db, active_entry, now)
            message = "Arbeitszeit beendet."
    elif action == "end_company":
        if not active_entry or active_entry.company_id is None:
            error = "Es läuft kein Auftrag."
        else:
            crud.finish_running_entry(db, active_entry, now)
            crud.start_running_entry(
                db,
                user_id=user.id,
                started_at=now,
                notes=notes.strip(),
            )
            message = "Auftrag beendet. Arbeitszeit läuft weiter."
    elif action == "start_break":
        if not active_entry:
            error = "Keine laufende Arbeitszeit vorhanden."
        elif active_entry.break_started_at:
            error = "Pause läuft bereits."
        else:
            crud.start_break(db, active_entry, now)
            message = "Pause gestartet."
    elif action == "end_break":
        if not active_entry:
            error = "Keine laufende Arbeitszeit vorhanden."
        elif not active_entry.break_started_at:
            error = "Es läuft keine Pause."
        else:
            crud.end_break(db, active_entry, now)
            message = "Pause beendet."
    else:
        error = "Unbekannte Aktion."

    params = {}
    if message and not error:
        params["msg"] = message
    if error:
        params["error"] = error
    redirect = _build_redirect(target, **params)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/vacations", response_class=HTMLResponse)
def vacation_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    focus = request.query_params.get("focus", "vacations")
    params = {}
    if focus:
        params["focus"] = focus
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    if message:
        params["msg"] = message
    if error:
        params["error"] = error
    redirect = _build_redirect("/records", **params)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/vacations")
def submit_vacation(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    comment: str = Form(""),
    use_overtime: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if end_date < start_date:
        return RedirectResponse(
            url="/records?error=Enddatum+darf+nicht+vor+dem+Startdatum+liegen&focus=vacations",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    use_overtime_value = bool(use_overtime == "on" and user.overtime_vacation_enabled)
    overtime_minutes = 0
    if use_overtime_value:
        overtime_minutes = services.calculate_required_vacation_minutes(user, start_date, end_date)
    crud.create_vacation_request(
        db,
        schemas.VacationRequestCreate(
            user_id=user.id,
            start_date=start_date,
            end_date=end_date,
            comment=comment,
            use_overtime=use_overtime_value,
            overtime_minutes=overtime_minutes,
        ),
    )
    return RedirectResponse(
        url="/records?msg=Urlaubsantrag+erstellt&focus=vacations",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/records", response_class=HTMLResponse)
def records_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    focus = request.query_params.get("focus", "")
    month_param = request.query_params.get("month")
    selected_month, start_date, end_date = _resolve_month_period(month_param)
    company_param = request.query_params.get("company")
    company_filter_id: Optional[int] = None
    company_filter_none = False
    if company_param == "none":
        company_filter_none = True
    elif company_param:
        try:
            company_filter_id = int(company_param)
        except ValueError:
            company_filter_id = None
    month_entries = list(
        crud.get_time_entries(
            db,
            user.id,
            start=start_date,
            end=end_date,
        )
    )
    entries = list(month_entries)
    if company_filter_none:
        entries = [entry for entry in entries if entry.company_id is None]
    elif company_filter_id is not None:
        entries = [entry for entry in entries if entry.company_id == company_filter_id]
    approved_month_entries = [
        entry for entry in month_entries if entry.status == models.TimeEntryStatus.APPROVED
    ]
    approved_entries = [entry for entry in entries if entry.status == models.TimeEntryStatus.APPROVED]
    total_work_minutes = sum(entry.worked_minutes for entry in approved_month_entries)
    target_minutes = services.calculate_monthly_target_minutes(
        user, selected_month.year, selected_month.month
    )
    vacations = crud.get_vacations_for_user(db, user.id)
    overtime_taken_minutes = services.calculate_vacation_overtime_in_range(
        user, vacations, start_date, end_date
    )
    effective_minutes = total_work_minutes + overtime_taken_minutes
    balance = effective_minutes - target_minutes
    total_overtime_minutes = max(balance, 0)
    total_undertime_minutes = max(-balance, 0) if user.time_account_enabled else 0
    vacation_summary = services.calculate_vacation_summary(user, vacations, selected_month.year)

    company_totals_all = _aggregate_company_totals(approved_month_entries)
    company_totals_filtered = _aggregate_company_totals(approved_entries)

    companies = crud.get_companies(db)
    month_value = f"{selected_month.year:04d}-{selected_month.month:02d}"
    return templates.TemplateResponse(
        "records.html",
        {
            "request": request,
            "user": user,
            "message": message,
            "error": error,
            "entries": entries,
            "approved_entries": approved_entries,
            "total_work_minutes": total_work_minutes,
            "total_overtime_minutes": total_overtime_minutes,
            "total_undertime_minutes": total_undertime_minutes,
            "target_minutes": target_minutes,
            "overtime_taken_minutes": overtime_taken_minutes,
            "company_totals_all": company_totals_all,
            "company_totals_filtered": company_totals_filtered,
            "companies": companies,
            "vacations": vacations,
            "vacation_summary": vacation_summary,
            "selected_month": selected_month,
            "month_value": month_value,
            "company_filter_id": company_filter_id,
            "company_filter_none": company_filter_none,
            "focus": focus,
        },
    )


@app.get("/records/pdf")
def export_records_pdf(request: Request, month: Optional[str] = None, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    selected_month, start_date, end_date = _resolve_month_period(month)
    month_entries = list(
        crud.get_time_entries(
            db,
            user.id,
            start=start_date,
            end=end_date,
        )
    )
    approved_month_entries = [
        entry for entry in month_entries if entry.status == models.TimeEntryStatus.APPROVED
    ]
    total_work_minutes = sum(entry.worked_minutes for entry in approved_month_entries)
    target_minutes = services.calculate_monthly_target_minutes(
        user, selected_month.year, selected_month.month
    )
    vacations = crud.get_vacations_for_user(db, user.id)
    overtime_taken_minutes = services.calculate_vacation_overtime_in_range(
        user, vacations, start_date, end_date
    )
    effective_minutes = total_work_minutes + overtime_taken_minutes
    balance = effective_minutes - target_minutes
    total_overtime_minutes = max(balance, 0)
    total_undertime_minutes = max(-balance, 0) if user.time_account_enabled else 0
    vacation_summary = services.calculate_vacation_summary(user, vacations, selected_month.year)
    company_totals_all = _aggregate_company_totals(approved_month_entries)
    buffer = export_time_overview_pdf(
        user=user,
        selected_month=selected_month,
        entries=month_entries,
        total_work_minutes=total_work_minutes,
        target_minutes=target_minutes,
        overtime_taken_minutes=overtime_taken_minutes,
        total_overtime_minutes=total_overtime_minutes,
        total_undertime_minutes=total_undertime_minutes,
        vacation_summary=vacation_summary,
        company_totals=company_totals_all,
    )
    filename = f"arbeitszeit_{user.username}_{selected_month.strftime('%Y_%m')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _ensure_admin(user: models.User) -> bool:
    return bool(user.group and user.group.is_admin)


def _has_group_permission(user: models.User, attribute: str) -> bool:
    if _ensure_admin(user):
        return True
    if not user.group:
        return False
    return bool(getattr(user.group, attribute, False))


def _can_manage_users(user: models.User) -> bool:
    return _has_group_permission(user, "can_manage_users")


def _can_manage_vacations(user: models.User) -> bool:
    return _has_group_permission(user, "can_manage_vacations")


def _can_approve_manual_entries(user: models.User) -> bool:
    return _has_group_permission(user, "can_approve_manual_entries")


def _can_create_companies(user: models.User) -> bool:
    return _has_group_permission(user, "can_create_companies")


def _resolve_admin_permissions(user: models.User) -> dict[str, bool]:
    permissions = {
        "users": _can_manage_users(user),
        "groups": _ensure_admin(user),
        "companies": _ensure_admin(user),
        "holidays": _ensure_admin(user),
        "approvals_manual": _can_approve_manual_entries(user),
        "approvals_vacations": _can_manage_vacations(user),
    }
    permissions["approvals"] = permissions["approvals_manual"] or permissions["approvals_vacations"]
    permissions["create_companies"] = _can_create_companies(user)
    return permissions


def _admin_template(
    template: str,
    request: Request,
    user: models.User,
    *,
    message: Optional[str] = None,
    error: Optional[str] = None,
    **context,
):
    payload = {
        "request": request,
        "user": user,
        "message": message,
        "error": error,
        "admin_permissions": _resolve_admin_permissions(user),
    }
    payload.update(context)
    return templates.TemplateResponse(template, payload)


@app.get("/admin", include_in_schema=False)
def admin_portal(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_list(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    users = crud.get_users(db)
    return _admin_template(
        "admin/users_list.html",
        request,
        user,
        message=message,
        error=error,
        users=users,
    )


@app.get("/admin/users/new", response_class=HTMLResponse)
def admin_users_new(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    groups = crud.get_groups(db)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/users_form.html",
        request,
        user,
        message=message,
        error=error,
        groups=groups,
        form_user=None,
    )


@app.get("/admin/users/{user_id}", response_class=HTMLResponse)
def admin_users_edit(request: Request, user_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    target = crud.get_user(db, user_id)
    if not target:
        return RedirectResponse(
            url="/admin/users?error=Benutzer+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    groups = crud.get_groups(db)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/users_form.html",
        request,
        user,
        message=message,
        error=error,
        groups=groups,
        form_user=target,
    )


@app.get("/admin/groups", response_class=HTMLResponse)
def admin_groups_list(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    groups = crud.get_groups(db)
    return _admin_template(
        "admin/groups_list.html",
        request,
        user,
        message=message,
        error=error,
        groups=groups,
    )


@app.get("/admin/groups/new", response_class=HTMLResponse)
def admin_groups_new(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/group_form.html",
        request,
        user,
        message=message,
        error=error,
        group=None,
    )


@app.get("/admin/groups/{group_id}", response_class=HTMLResponse)
def admin_groups_edit(request: Request, group_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    group = crud.get_group(db, group_id)
    if not group:
        return RedirectResponse(
            url="/admin/groups?error=Gruppe+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/group_form.html",
        request,
        user,
        message=message,
        error=error,
        group=group,
    )


@app.get("/admin/companies", response_class=HTMLResponse)
def admin_companies_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    companies = crud.get_companies(db)
    return _admin_template(
        "admin/companies.html",
        request,
        user,
        message=message,
        error=error,
        companies=companies,
    )


@app.get("/admin/companies/new", response_class=HTMLResponse)
def admin_companies_new(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/company_form.html",
        request,
        user,
        message=message,
        error=error,
        company=None,
    )


@app.get("/admin/companies/{company_id}", response_class=HTMLResponse)
def admin_companies_edit(request: Request, company_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    company = crud.get_company(db, company_id)
    if not company:
        return RedirectResponse(
            url="/admin/companies?error=Firma+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return _admin_template(
        "admin/company_form.html",
        request,
        user,
        message=message,
        error=error,
        company=company,
    )


@app.get("/admin/holidays", response_class=HTMLResponse)
def admin_holidays_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    selected_state_param = request.query_params.get("state")
    if selected_state_param:
        selected_state_param = selected_state_param.upper()
    selected_year_param = request.query_params.get("holiday_year")
    default_region = crud.get_default_holiday_region(db)
    selected_state = selected_state_param if selected_state_param in HOLIDAY_STATE_CODES else None
    if not selected_state:
        selected_state = default_region if default_region in HOLIDAY_STATE_CODES else "DE"
    try:
        selected_year = int(selected_year_param) if selected_year_param else date.today().year
    except ValueError:
        selected_year = date.today().year
    holidays = crud.get_holidays_for_year(db, selected_year, selected_state)
    return _admin_template(
        "admin/holidays.html",
        request,
        user,
        message=message,
        error=error,
        holidays=holidays,
        holiday_states=HOLIDAY_STATE_CHOICES,
        selected_state=selected_state,
        selected_year=selected_year,
    )


@app.get("/admin/approvals", response_class=HTMLResponse)
def admin_approvals_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    can_manual = _can_approve_manual_entries(user)
    can_vacation = _can_manage_vacations(user)
    if not (can_manual or can_vacation):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    pending_entries = (
        crud.get_time_entries(
            db,
            statuses=[models.TimeEntryStatus.PENDING],
            is_manual=True,
        )
        if can_manual
        else []
    )
    pending_vacations = (
        crud.get_vacation_requests(db, status=models.VacationStatus.PENDING)
        if can_vacation
        else []
    )
    return _admin_template(
        "admin/approvals.html",
        request,
        user,
        message=message,
        error=error,
        pending_entries=pending_entries,
        pending_vacations=pending_vacations,
        show_manual_section=can_manual,
        show_vacation_section=can_vacation,
    )


@app.post("/admin/groups/create")
def create_group_html(
    request: Request,
    name: str = Form(...),
    is_admin: Optional[str] = Form(None),
    can_manage_users: Optional[str] = Form(None),
    can_manage_vacations: Optional[str] = Form(None),
    can_approve_manual_entries: Optional[str] = Form(None),
    can_create_companies: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    is_admin_value = is_admin == "on"
    manage_users_value = can_manage_users == "on"
    manage_vacations_value = can_manage_vacations == "on"
    approve_manual_value = can_approve_manual_entries == "on"
    create_companies_value = can_create_companies == "on"
    if is_admin_value:
        manage_users_value = True
        manage_vacations_value = True
        approve_manual_value = True
        create_companies_value = True
    try:
        crud.create_group(
            db,
            schemas.GroupCreate(
                name=name,
                is_admin=is_admin_value,
                can_manage_users=manage_users_value,
                can_manage_vacations=manage_vacations_value,
                can_approve_manual_entries=approve_manual_value,
                can_create_companies=create_companies_value,
            ),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/admin/groups/new?error=Gruppe+existiert+bereits",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/groups?msg=Gruppe+angelegt", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/groups/{group_id}/update")
def update_group_html(
    request: Request,
    group_id: int,
    name: str = Form(...),
    is_admin: Optional[str] = Form(None),
    can_manage_users: Optional[str] = Form(None),
    can_manage_vacations: Optional[str] = Form(None),
    can_approve_manual_entries: Optional[str] = Form(None),
    can_create_companies: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    is_admin_value = is_admin == "on"
    manage_users_value = can_manage_users == "on"
    manage_vacations_value = can_manage_vacations == "on"
    approve_manual_value = can_approve_manual_entries == "on"
    create_companies_value = can_create_companies == "on"
    if is_admin_value:
        manage_users_value = True
        manage_vacations_value = True
        approve_manual_value = True
        create_companies_value = True
    try:
        updated = crud.update_group(
            db,
            group_id,
            schemas.GroupCreate(
                name=name,
                is_admin=is_admin_value,
                can_manage_users=manage_users_value,
                can_manage_vacations=manage_vacations_value,
                can_approve_manual_entries=approve_manual_value,
                can_create_companies=create_companies_value,
            ),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url=f"/admin/groups/{group_id}?error=Gruppenname+bereits+vergeben",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not updated:
        return RedirectResponse(
            url="/admin/groups?error=Gruppe+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/groups?msg=Gruppe+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/groups/{group_id}/delete")
def delete_group_html(request: Request, group_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    deleted = crud.delete_group(db, group_id)
    if not deleted:
        return RedirectResponse(
            url="/admin/groups?error=Gruppe+konnte+nicht+gelöscht+werden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/groups?msg=Gruppe+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/create")
def create_user_html(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    pin_code: str = Form(...),
    standard_weekly_hours: float = Form(40.0),
    group_id: Optional[str] = Form(None),
    time_account_enabled: Optional[str] = Form(None),
    overtime_vacation_enabled: Optional[str] = Form(None),
    annual_vacation_days: int = Form(30),
    vacation_carryover_enabled: Optional[str] = Form(None),
    vacation_carryover_days: int = Form(0),
    rfid_tag: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    group_value = int(group_id) if group_id else None
    time_account_value = time_account_enabled == "on"
    overtime_vacation_value = overtime_vacation_enabled == "on"
    if not time_account_value:
        overtime_vacation_value = False
    carryover_enabled = vacation_carryover_enabled == "on"
    carryover_days_value = vacation_carryover_days if carryover_enabled else 0
    rfid_value = (rfid_tag or "").strip() or None
    try:
        crud.create_user(
            db,
            schemas.UserCreate(
                username=username,
                full_name=full_name,
                email=email,
                pin_code=pin_code,
                standard_weekly_hours=standard_weekly_hours,
                group_id=group_value,
                time_account_enabled=time_account_value,
                overtime_vacation_enabled=overtime_vacation_value,
                annual_vacation_days=annual_vacation_days,
                vacation_carryover_enabled=carryover_enabled,
                vacation_carryover_days=carryover_days_value,
                rfid_tag=rfid_value,
            ),
        )
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        message = "Ungültige+Eingabe" if isinstance(exc, ValueError) else "Benutzer+konnte+nicht+angelegt+werden"
        return RedirectResponse(
            url=f"/admin/users/new?error={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/users?msg=Benutzer+angelegt", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{user_id}/update")
def update_user_html(
    request: Request,
    user_id: int,
    username: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    pin_code: str = Form(...),
    standard_weekly_hours: float = Form(40.0),
    group_id: Optional[str] = Form(None),
    time_account_enabled: Optional[str] = Form(None),
    overtime_vacation_enabled: Optional[str] = Form(None),
    annual_vacation_days: int = Form(30),
    vacation_carryover_enabled: Optional[str] = Form(None),
    vacation_carryover_days: int = Form(0),
    rfid_tag: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    group_value = int(group_id) if group_id else None
    time_account_value = time_account_enabled == "on"
    overtime_vacation_value = overtime_vacation_enabled == "on"
    if not time_account_value:
        overtime_vacation_value = False
    carryover_enabled = vacation_carryover_enabled == "on"
    carryover_days_value = vacation_carryover_days if carryover_enabled else 0
    rfid_value = (rfid_tag or "").strip() or None
    try:
        updated = crud.update_user(
            db,
            user_id,
            schemas.UserUpdate(
                username=username,
                full_name=full_name,
                email=email,
                pin_code=pin_code,
                standard_weekly_hours=standard_weekly_hours,
                group_id=group_value,
                time_account_enabled=time_account_value,
                overtime_vacation_enabled=overtime_vacation_value,
                annual_vacation_days=annual_vacation_days,
                vacation_carryover_enabled=carryover_enabled,
                vacation_carryover_days=carryover_days_value,
                rfid_tag=rfid_value,
            ),
        )
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        message = "Ungültige+Eingabe" if isinstance(exc, ValueError) else "Aktualisierung+fehlgeschlagen"
        return RedirectResponse(
            url=f"/admin/users/{user_id}?error={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not updated:
        return RedirectResponse(
            url="/admin/users?error=Benutzer+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/users?msg=Benutzer+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{user_id}/delete")
def delete_user_html(request: Request, user_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_users(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if not crud.delete_user(db, user_id):
        return RedirectResponse(
            url="/admin/users?error=Benutzer+konnte+nicht+gelöscht+werden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/users?msg=Benutzer+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/companies/create")
def create_company_html(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    try:
        crud.create_company(
            db,
            schemas.CompanyCreate(name=name.strip(), description=description.strip()),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/admin/companies/new?error=Firma+existiert+bereits",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/companies?msg=Firma+angelegt", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/companies/{company_id}/update")
def update_company_html(
    request: Request,
    company_id: int,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    try:
        updated = crud.update_company(
            db,
            company_id,
            schemas.CompanyUpdate(name=name.strip(), description=description.strip()),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url=f"/admin/companies/{company_id}?error=Firmenname+bereits+vergeben",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not updated:
        return RedirectResponse(
            url="/admin/companies?error=Firma+nicht+gefunden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/companies?msg=Firma+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/companies/{company_id}/delete")
def delete_company_html(request: Request, company_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if not crud.delete_company(db, company_id):
        return RedirectResponse(
            url="/admin/companies?error=Firma+konnte+nicht+gelöscht+werden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin/companies?msg=Firma+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/time-entries/{entry_id}/update")
def update_time_entry_html(
    request: Request,
    entry_id: int,
    user_id: int = Form(...),
    work_date: date = Form(...),
    start_time: time = Form(...),
    end_time: time = Form(...),
    break_minutes: int = Form(0),
    company_id: Optional[str] = Form(None),
    notes: str = Form(""),
    redirect_user: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if end_time <= start_time:
        redirect = _build_redirect(
            "/admin/users",
            error="Endzeit muss nach der Startzeit liegen",
            user=redirect_user,
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    company_value = int(company_id) if company_id else None
    try:
        updated = crud.update_time_entry(
            db,
            entry_id,
            schemas.TimeEntryCreate(
                user_id=user_id,
                company_id=company_value,
                work_date=work_date,
                start_time=start_time,
                end_time=end_time,
                break_minutes=max(break_minutes, 0),
                break_started_at=None,
                is_open=False,
                notes=notes,
            ),
        )
    except ValueError:
        redirect = _build_redirect(
            "/admin/users", error="Ungültige Angaben", user=redirect_user
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    if not updated:
        redirect = _build_redirect(
            "/admin/users", error="Buchung nicht gefunden", user=redirect_user
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect("/admin/users", msg="Buchung aktualisiert", user=redirect_user)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/time-entries/{entry_id}/delete")
def delete_time_entry_html(
    request: Request,
    entry_id: int,
    redirect_user: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not crud.delete_time_entry(db, entry_id):
        redirect = _build_redirect(
            "/admin/users", error="Buchung konnte nicht gelöscht werden", user=redirect_user
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        "/admin/users", msg="Buchung gelöscht", user=redirect_user
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/time-entries/{entry_id}/status")
def set_time_entry_status_admin(
    request: Request,
    entry_id: int,
    action: str = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_approve_manual_entries(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if action == "approve":
        new_status = models.TimeEntryStatus.APPROVED
    elif action == "reject":
        new_status = models.TimeEntryStatus.REJECTED
    else:
        redirect = _build_redirect("/admin/approvals", error="Ungültige Aktion")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    updated = crud.set_time_entry_status(db, entry_id, new_status)
    if not updated:
        redirect = _build_redirect("/admin/approvals", error="Buchung nicht gefunden")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    message = "Buchung freigegeben" if new_status == models.TimeEntryStatus.APPROVED else "Buchung abgelehnt"
    redirect = _build_redirect("/admin/approvals", msg=message)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/holidays/sync")
def sync_holidays_admin(
    request: Request,
    state: str = Form(...),
    year: int = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    state = state.upper()
    if state not in HOLIDAY_STATE_CODES:
        redirect = _build_redirect(
            "/admin/holidays",
            error="Ungültiges Bundesland",
            state=state,
            holiday_year=str(year),
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    if year < 1900 or year > 2100:
        redirect = _build_redirect(
            "/admin/holidays",
            error="Jahr muss zwischen 1900 und 2100 liegen",
            state=state,
            holiday_year=str(year),
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    holidays = holiday_calculator.ensure_holidays(db, year, state)
    redirect = _build_redirect(
        "/admin/holidays",
        msg=f"{len(holidays)}+Feiertage+aktualisiert",
        state=state,
        holiday_year=str(year),
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/vacations/{vacation_id}/status")
def set_vacation_status_admin(
    request: Request,
    vacation_id: int,
    action: str = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _can_manage_vacations(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if action == "approve":
        new_status = models.VacationStatus.APPROVED
    elif action == "reject":
        new_status = models.VacationStatus.REJECTED
    else:
        redirect = _build_redirect("/admin/approvals", error="Ungültige Aktion")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    updated = crud.update_vacation_status(db, vacation_id, new_status)
    if not updated:
        redirect = _build_redirect("/admin/approvals", error="Urlaubsantrag nicht gefunden")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    message = "Urlaub genehmigt" if new_status == models.VacationStatus.APPROVED else "Urlaub abgelehnt"
    redirect = _build_redirect("/admin/approvals", msg=message)
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/holidays/create")
def create_holiday_admin(
    request: Request,
    name: str = Form(...),
    holiday_date: date = Form(...),
    state: str = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    state = state.upper()
    region = state if state in HOLIDAY_STATE_CODES else "DE"
    try:
        crud.upsert_holidays(db, [schemas.HolidayCreate(name=name.strip(), date=holiday_date, region=region)])
    except IntegrityError:
        db.rollback()
        redirect = _build_redirect(
            "/admin/holidays",
            error="Feiertag konnte nicht gespeichert werden",
            state=region,
            holiday_year=str(holiday_date.year),
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        "/admin/holidays",
        msg="Feiertag+gespeichert",
        state=region,
        holiday_year=str(holiday_date.year),
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/holidays/{holiday_id}/delete")
def delete_holiday_admin(
    request: Request,
    holiday_id: int,
    state: str = Form(...),
    year: int = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    state = state.upper()
    if not crud.delete_holiday(db, holiday_id):
        redirect = _build_redirect(
            "/admin/holidays",
            error="Feiertag konnte nicht gelöscht werden",
            state=state,
            holiday_year=str(year),
        )
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(
        "/admin/holidays", msg="Feiertag gelöscht", state=state, holiday_year=str(year)
    )
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/api/groups", response_model=schemas.Group)
def create_group(group: schemas.GroupCreate, db: Session = Depends(database.get_db)):
    return crud.create_group(db, group)


@app.get("/api/groups", response_model=List[schemas.Group])
def list_groups(db: Session = Depends(database.get_db)):
    return crud.get_groups(db)


@app.post("/api/users", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    if crud.get_user_by_username(db, user.username):
        raise HTTPException(status_code=400, detail="Benutzername bereits vergeben")
    return crud.create_user(db, user)


@app.get("/api/users", response_model=List[schemas.User])
def list_users(db: Session = Depends(database.get_db)):
    return crud.get_users(db)


@app.post("/api/time-entries", response_model=schemas.TimeEntry)
def create_time_entry(entry: schemas.TimeEntryCreate, db: Session = Depends(database.get_db)):
    user = crud.get_user(db, entry.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    db_entry = crud.create_time_entry(db, entry)
    return schemas.TimeEntry.model_validate(db_entry)


@app.delete("/api/time-entries/{entry_id}")
def delete_time_entry(entry_id: int, db: Session = Depends(database.get_db)):
    if not crud.delete_time_entry(db, entry_id):
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return {"detail": "Zeitbuchung gelöscht"}


@app.post("/api/vacations", response_model=schemas.VacationRequest)
def create_vacation(vacation: schemas.VacationRequestCreate, db: Session = Depends(database.get_db)):
    user = crud.get_user(db, vacation.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    use_overtime = bool(vacation.use_overtime and user.overtime_vacation_enabled)
    overtime_minutes = (
        services.calculate_required_vacation_minutes(user, vacation.start_date, vacation.end_date)
        if use_overtime
        else 0
    )
    payload = vacation.model_copy(
        update={
            "use_overtime": use_overtime,
            "overtime_minutes": overtime_minutes,
        }
    )
    db_vacation = crud.create_vacation_request(db, payload)
    return schemas.VacationRequest.model_validate(db_vacation)


@app.post("/api/vacations/{vacation_id}/status", response_model=schemas.VacationRequest)
def update_vacation_status(vacation_id: int, status: str, db: Session = Depends(database.get_db)):
    updated = crud.update_vacation_status(db, vacation_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail="Urlaubseintrag nicht gefunden")
    return schemas.VacationRequest.model_validate(updated)


@app.post("/api/holidays/sync")
def sync_holidays(year: int, state: str = "BY", db: Session = Depends(database.get_db)):
    state = state.upper()
    region = state if state in HOLIDAY_STATE_CODES else "DE"
    holidays = holiday_calculator.ensure_holidays(db, year, region)
    return {"count": len(holidays), "state": region}


@app.get("/api/users/{user_id}/excel")
def export_user_time_entries(user_id: int, db: Session = Depends(database.get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    entries = crud.get_time_entries_for_user(db, user_id)
    buffer = export_time_entries(entries)
    filename = f"arbeitszeiten_{user.username}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/health")
def health_check():
    return {"status": "ok"}
