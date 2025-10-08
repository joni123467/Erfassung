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

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Erfassung", description="Zeiterfassung mit Überstunden & Urlaub")

app.add_middleware(SessionMiddleware, secret_key="zeit-erfassung-secret-key")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.utcnow

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


@app.on_event("startup")
def ensure_seed_data():
    ensure_schema()
    db = database.SessionLocal()
    try:
        if not crud.get_groups(db):
            admin_group = crud.create_group(db, schemas.GroupCreate(name="Administration", is_admin=True))
        else:
            admin_group = db.query(models.Group).filter(models.Group.is_admin == True).first()  # noqa: E712
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
                    standard_daily_minutes=480,
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
    metrics = services.calculate_dashboard_metrics(db, user.id)
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
    company_value = int(company_id) if company_id else None
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
        if active_entry:
            error = "Es läuft bereits eine Arbeitszeit."
        elif not company_id:
            error = "Bitte eine Firma auswählen."
        else:
            try:
                company_value = int(company_id)
            except ValueError:
                error = "Ungültige Firma ausgewählt."
            else:
                company = crud.get_company(db, company_value)
                if not company:
                    error = "Firma wurde nicht gefunden."
                else:
                    crud.start_running_entry(
                        db,
                        user_id=user.id,
                        started_at=now,
                        company_id=company.id,
                        notes=notes.strip(),
                    )
                    message = f"Auftrag bei {company.name} gestartet."
    elif action == "end_work":
        if not active_entry:
            error = "Keine laufende Arbeitszeit vorhanden."
        else:
            crud.finish_running_entry(db, active_entry, now)
            message = "Arbeitszeit beendet."
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
    crud.create_vacation_request(
        db,
        schemas.VacationRequestCreate(
            user_id=user.id,
            start_date=start_date,
            end_date=end_date,
            comment=comment,
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
    entries = crud.get_time_entries(
        db,
        user.id,
        start=start_date,
        end=end_date,
    )
    if company_filter_none:
        entries = [entry for entry in entries if entry.company_id is None]
    elif company_filter_id is not None:
        entries = [entry for entry in entries if entry.company_id == company_filter_id]
    approved_entries = [entry for entry in entries if entry.status == models.TimeEntryStatus.APPROVED]
    total_work_minutes = sum(entry.worked_minutes for entry in approved_entries)
    total_overtime_minutes = sum(entry.overtime_minutes for entry in approved_entries)
    worked_days = {entry.work_date for entry in approved_entries}
    target_minutes = len(worked_days) * (user.standard_daily_minutes or 0)

    def aggregate_company_totals(source_entries: List[models.TimeEntry]):
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

    approved_month_entries = [
        entry
        for entry in crud.get_time_entries(db, user.id, start=start_date, end=end_date)
        if entry.status == models.TimeEntryStatus.APPROVED
    ]
    company_totals_all = aggregate_company_totals(approved_month_entries)
    company_totals_filtered = aggregate_company_totals(approved_entries)

    companies = crud.get_companies(db)
    vacations = crud.get_vacations_for_user(db, user.id)
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
            "target_minutes": target_minutes,
            "company_totals_all": company_totals_all,
            "company_totals_filtered": company_totals_filtered,
            "companies": companies,
            "vacations": vacations,
            "selected_month": selected_month,
            "month_value": month_value,
            "company_filter_id": company_filter_id,
            "company_filter_none": company_filter_none,
            "focus": focus,
        },
    )


def _ensure_admin(user: models.User) -> bool:
    return bool(user.group and user.group.is_admin)


def _admin_template(
    template: str,
    request: Request,
    user: models.User,
    *,
    message: Optional[str] = None,
    error: Optional[str] = None,
    **context,
):
    payload = {"request": request, "user": user, "message": message, "error": error}
    payload.update(context)
    return templates.TemplateResponse(template, payload)


@app.get("/admin", include_in_schema=False)
def admin_portal(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_list(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
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
    if not _ensure_admin(user):
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
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    pending_entries = crud.get_time_entries(
        db,
        statuses=[models.TimeEntryStatus.PENDING],
        is_manual=True,
    )
    pending_vacations = crud.get_vacation_requests(db, status=models.VacationStatus.PENDING)
    return _admin_template(
        "admin/approvals.html",
        request,
        user,
        message=message,
        error=error,
        pending_entries=pending_entries,
        pending_vacations=pending_vacations,
    )


@app.post("/admin/groups/create")
def create_group_html(
    request: Request,
    name: str = Form(...),
    is_admin: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    is_admin_value = is_admin == "on"
    try:
        crud.create_group(db, schemas.GroupCreate(name=name, is_admin=is_admin_value))
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
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    is_admin_value = is_admin == "on"
    try:
        updated = crud.update_group(db, group_id, schemas.GroupCreate(name=name, is_admin=is_admin_value))
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
    standard_daily_minutes: int = Form(480),
    group_id: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    group_value = int(group_id) if group_id else None
    try:
        crud.create_user(
            db,
            schemas.UserCreate(
                username=username,
                full_name=full_name,
                email=email,
                pin_code=pin_code,
                standard_daily_minutes=standard_daily_minutes,
                group_id=group_value,
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
    standard_daily_minutes: int = Form(480),
    group_id: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    group_value = int(group_id) if group_id else None
    try:
        updated = crud.update_user(
            db,
            user_id,
            schemas.UserUpdate(
                username=username,
                full_name=full_name,
                email=email,
                pin_code=pin_code,
                standard_daily_minutes=standard_daily_minutes,
                group_id=group_value,
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
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
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
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        crud.create_company(
            db,
            schemas.CompanyCreate(name=name.strip(), description=description.strip()),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/admin/companies?error=Firma+existiert+bereits",
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
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        updated = crud.update_company(
            db,
            company_id,
            schemas.CompanyUpdate(name=name.strip(), description=description.strip()),
        )
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/admin/companies?error=Firmenname+bereits+vergeben",
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
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
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
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
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
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
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
    db_vacation = crud.create_vacation_request(db, vacation)
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
