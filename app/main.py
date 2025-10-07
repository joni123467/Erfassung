from __future__ import annotations

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
    time_entries = crud.get_time_entries_for_user(db, user.id)
    vacations = crud.get_vacations_for_user(db, user.id)
    holidays = crud.get_holidays_for_year(db, date.today().year)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    companies = crud.get_companies(db)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "metrics": metrics,
            "entries": time_entries,
            "vacations": vacations,
            "holidays": holidays,
            "companies": companies,
            "message": message,
            "error": error,
        },
    )


@app.get("/time", response_class=HTMLResponse)
def time_tracking_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    entries = crud.get_time_entries_for_user(db, user.id)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    companies = crud.get_companies(db)
    return templates.TemplateResponse(
        "time_tracking.html",
        {
            "request": request,
            "user": user,
            "entries": entries,
            "message": message,
            "error": error,
            "companies": companies,
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
            notes=notes,
        )
        crud.create_time_entry(db, entry)
    except ValueError:
        redirect = _build_redirect(_sanitize_next(next_url), error="Ungültige Zeiteingabe")
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect(_sanitize_next(next_url), msg="Zeitbuchung erfolgreich erfasst")
    return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/vacations", response_class=HTMLResponse)
def vacation_page(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    vacations = crud.get_vacations_for_user(db, user.id)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "vacations.html",
        {
            "request": request,
            "user": user,
            "vacations": vacations,
            "message": message,
            "error": error,
        },
    )


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
            url="/vacations?error=Enddatum+darf+nicht+vor+dem+Startdatum+liegen",
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
        url="/vacations?msg=Urlaubsantrag+erstellt",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _ensure_admin(user: models.User) -> bool:
    return bool(user.group and user.group.is_admin)


@app.get("/admin", response_class=HTMLResponse)
def admin_portal(request: Request, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _ensure_admin(user):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    message = request.query_params.get("msg")
    error = request.query_params.get("error")
    selected_user = request.query_params.get("user")
    selected_user_id = int(selected_user) if selected_user and selected_user.isdigit() else None
    groups = crud.get_groups(db)
    users = crud.get_users(db)
    companies = crud.get_companies(db)
    time_entries = crud.get_time_entries(db, selected_user_id)
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "groups": groups,
            "users": users,
            "companies": companies,
            "time_entries": time_entries,
            "selected_user_id": selected_user_id,
            "message": message,
            "error": error,
        },
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
            url="/admin?error=Gruppe+existiert+bereits",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin?msg=Gruppe+angelegt", status_code=status.HTTP_303_SEE_OTHER)


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
            url="/admin?error=Gruppenname+bereits+vergeben",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not updated:
        return RedirectResponse(url="/admin?error=Gruppe+nicht+gefunden", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?msg=Gruppe+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/groups/{group_id}/delete")
def delete_group_html(request: Request, group_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    deleted = crud.delete_group(db, group_id)
    if not deleted:
        return RedirectResponse(
            url="/admin?error=Gruppe+konnte+nicht+gelöscht+werden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin?msg=Gruppe+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


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
        message = "Ungültige Eingabe" if isinstance(exc, ValueError) else "Benutzer konnte nicht angelegt werden"
        return RedirectResponse(
            url=f"/admin?error={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin?msg=Benutzer+angelegt", status_code=status.HTTP_303_SEE_OTHER)


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
        message = "Ungültige Eingabe" if isinstance(exc, ValueError) else "Aktualisierung fehlgeschlagen"
        return RedirectResponse(
            url=f"/admin?error={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not updated:
        return RedirectResponse(url="/admin?error=Benutzer+nicht+gefunden", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?msg=Benutzer+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{user_id}/delete")
def delete_user_html(request: Request, user_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not crud.delete_user(db, user_id):
        return RedirectResponse(url="/admin?error=Benutzer+konnte+nicht+gelöscht+werden", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?msg=Benutzer+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


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
            url="/admin?error=Firma+existiert+bereits",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin?msg=Firma+angelegt", status_code=status.HTTP_303_SEE_OTHER)


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
        return RedirectResponse(url="/admin?error=Firmenname+bereits+vergeben", status_code=status.HTTP_303_SEE_OTHER)
    if not updated:
        return RedirectResponse(url="/admin?error=Firma+nicht+gefunden", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?msg=Firma+aktualisiert", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/companies/{company_id}/delete")
def delete_company_html(request: Request, company_id: int, db: Session = Depends(database.get_db)):
    user = get_logged_in_user(request, db)
    if not user or not _ensure_admin(user):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if not crud.delete_company(db, company_id):
        return RedirectResponse(
            url="/admin?error=Firma+konnte+nicht+gelöscht+werden",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/admin?msg=Firma+gelöscht", status_code=status.HTTP_303_SEE_OTHER)


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
        redirect = _build_redirect("/admin", error="Endzeit muss nach der Startzeit liegen", user=redirect_user)
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
                notes=notes,
            ),
        )
    except ValueError:
        redirect = _build_redirect("/admin", error="Ungültige Angaben", user=redirect_user)
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    if not updated:
        redirect = _build_redirect("/admin", error="Buchung nicht gefunden", user=redirect_user)
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect("/admin", msg="Buchung aktualisiert", user=redirect_user)
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
        redirect = _build_redirect("/admin", error="Buchung konnte nicht gelöscht werden", user=redirect_user)
        return RedirectResponse(url=redirect, status_code=status.HTTP_303_SEE_OTHER)
    redirect = _build_redirect("/admin", msg="Buchung gelöscht", user=redirect_user)
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
    holidays = holiday_calculator.ensure_holidays(db, year, state)
    return {"count": len(holidays)}


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
