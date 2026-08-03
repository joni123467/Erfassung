"""Regressionstests für den grafischen Kalender in Version 0.20.5."""

from datetime import date
import sys
import re

import pytest
import licensed_env


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    for name in [name for name in sys.modules if name.startswith("app")]:
        del sys.modules[name]
    import app.main as main
    licensed_env.activate()
    from app import crud, database, security
    from fastapi.testclient import TestClient
    with TestClient(main.app) as test_client:
        db = database.SessionLocal()
        admin = crud.get_user_by_username(db, "admin")
        admin.password_hash = security.hash_password("Admin!0000")
        admin.must_change_password = False
        db.commit()
        db.close()
        token = re.search(r'name="csrf_token" value="([^"]+)"', test_client.get("/login").text).group(1)
        test_client.post("/login", data={"username": "admin", "password": "Admin!0000", "csrf_token": token})
        yield test_client


@pytest.mark.parametrize("view", ["month", "week", "list", "not-a-view"])
def test_calendar_views_and_invalid_parameters_are_safe(client, view):
    response = client.get(f"/records/vacations/calendar?scope=self&view={view}&month=invalid&anchor=invalid")
    assert response.status_code == 200
    assert "Mein Kalender" in response.text
    assert "calendar-grid" in response.text or "Abwesenheiten" in response.text


def test_personal_calendar_marks_half_days_holidays_and_pending(client):
    from app import database, models
    db = database.SessionLocal()
    db.add(models.VacationRequest(user_id=1, start_date=date(2026, 8, 3), end_date=date(2026, 8, 3),
                                  status=models.VacationStatus.PENDING, half_day_start=True))
    db.add(models.Holiday(name="Testfeiertag", date=date(2026, 8, 4), region="DE-TEST"))
    db.commit()
    db.close()
    page = client.get("/records/vacations/calendar?scope=self&view=month&month=2026-08")
    assert page.status_code == 200
    assert "Testfeiertag" in page.text
    assert "½" in page.text
    assert "pending" in page.text


def test_team_permission_is_a_separate_scoped_permission():
    from app import permissions
    permission = permissions.PERMISSIONS_BY_KEY["Vacation.TeamCalendar"]
    assert permission.scoped is True
    assert permission.key != "Vacation.Overview"
