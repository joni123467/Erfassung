"""Regressionstests für Planung, Kalender, Abwesenheiten und lokale QR-Codes."""

from datetime import date
import sys
import pytest
import licensed_env


@pytest.fixture()
def main(tmp_path, monkeypatch):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    for name in [name for name in sys.modules if name.startswith("app")]:
        del sys.modules[name]
    import app.main as module
    licensed_env.activate()
    return module


@pytest.fixture()
def client(main):
    from fastapi.testclient import TestClient
    from app import crud, database, security
    with TestClient(main.app) as test_client:
        db = database.SessionLocal()
        admin = crud.get_user_by_username(db, "admin")
        admin.password_hash = security.hash_password("Admin!0000")
        admin.must_change_password = False
        db.commit(); db.close()
        yield test_client


def test_schedule_uses_individual_weekdays(client):
    from app import database, models, services
    db = database.SessionLocal()
    try:
        user = db.get(models.User, 1)
        db.add(models.WorkSchedule(user_id=user.id, valid_from=date(2026, 1, 1),
            monday_minutes=0, tuesday_minutes=0, wednesday_minutes=0,
            thursday_minutes=0, friday_minutes=0, saturday_minutes=360, sunday_minutes=0))
        db.commit(); db.refresh(user)
        assert services.target_minutes_for_date(user, date(2026, 1, 3)) == 360
        assert services.target_minutes_for_date(user, date(2026, 1, 5)) == 0
    finally:
        db.close()


def test_new_schema_and_absence_defaults(main, client):
    from sqlalchemy import inspect
    from app import database, models
    names = set(inspect(database.engine).get_table_names())
    assert {"work_schedules", "absence_types", "vacation_entitlement_entries", "calendar_feeds"} <= names
    db = database.SessionLocal()
    try:
        assert db.get(models.AbsenceType, "vacation").deducts_vacation is True
        assert db.get(models.AbsenceType, "sick").confidential is True
    finally:
        db.close()


def test_qr_is_generated_locally(client):
    _login(client)
    page = client.get("/admin/users/1").text
    assert "api.qrserver.com" not in page
    response = client.get("/admin/users/1/mobile-qr.png?size=200")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_calendar_and_private_ics_feed(client):
    from app import database, models
    _login(client)
    db = database.SessionLocal()
    try:
        db.add(models.VacationRequest(user_id=1, start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 7), status=models.VacationStatus.APPROVED,
            absence_type_key="vacation"))
        db.commit()
    finally:
        db.close()
    page = client.get("/records/vacations/calendar?year=2026")
    assert page.status_code == 200 and "06.07.2026" in page.text
    token = _csrf(client, "/records/vacations/calendar")
    response = client.post("/records/vacations/calendar/feed", data={"csrf_token": token, "scope": "self"}, follow_redirects=False)
    assert response.status_code == 303
    feed_url = response.headers["location"].split("feed_url=", 1)[1]
    from urllib.parse import unquote
    ics = client.get(unquote(feed_url)).text
    assert "BEGIN:VCALENDAR" in ics and "UID:absence-" in ics
    assert "DTEND;VALUE=DATE:20260708" in ics


def _csrf(client, url):
    import re
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(url).text)
    assert match
    return match.group(1)


def _login(client):
    return client.post("/login", data={"username": "admin", "password": "Admin!0000", "csrf_token": _csrf(client, "/login")}, follow_redirects=False)
