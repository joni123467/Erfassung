from __future__ import annotations

from datetime import date, datetime
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import crud, database, holiday_calculator, models, schemas, services
from .excel_export import export_time_entries

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Erfassung", description="Zeiterfassung mit Überstunden & Urlaub")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.utcnow


@app.on_event("startup")
def ensure_seed_data():
    db = database.SessionLocal()
    try:
        if not crud.get_groups(db):
            admin_group = crud.create_group(db, schemas.GroupCreate(name="Administration", is_admin=True))
        else:
            admin_group = db.query(models.Group).filter(models.Group.is_admin == True).first()  # noqa: E712
        if not crud.get_users(db):
            crud.create_user(
                db,
                schemas.UserCreate(
                    username="admin",
                    full_name="Administrator",
                    email="admin@example.com",
                    group_id=admin_group.id if admin_group else None,
                    standard_daily_minutes=480,
                ),
            )
    finally:
        db.close()


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    response = await call_next(request)
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user_id: int = 1, db: Session = Depends(database.get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    metrics = services.calculate_dashboard_metrics(db, user_id)
    time_entries = crud.get_time_entries_for_user(db, user_id)
    vacations = crud.get_vacations_for_user(db, user_id)
    holidays = crud.get_holidays_for_year(db, date.today().year)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "metrics": metrics,
            "entries": time_entries,
            "vacations": vacations,
            "holidays": holidays,
        },
    )


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
