"""Regression tests for 0.9.17 – the overlap error on edit names the conflicting
booking (diagnostic).

When editing a booking is genuinely blocked by a *new* overlap, the error now
identifies which booking collides (date + times), both from ``crud`` and in the
message shown by the /admin/time-entries/{id}/update route.
"""

from __future__ import annotations

import re
import sys
from datetime import date, time
from urllib.parse import unquote

import pytest

import licensed_env


def _fresh_app(tmp_path, monkeypatch, env: dict | None = None):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    for key in ("DATABASE_URL", "DB_TYPE", "DB_HOST", "DB_PORT", "DB_NAME",
                "DB_USER", "DB_PASSWORD", "DB_SSL", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]
    import app.main as main

    licensed_env.activate()
    return main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    main = _fresh_app(tmp_path, monkeypatch, {"DATABASE_URL": f"sqlite:///{tmp_path}/erfassung.db"})
    from fastapi.testclient import TestClient

    with TestClient(main.app) as test_client:
        from app import crud, database, security

        db = database.SessionLocal()
        try:
            admin = crud.get_user_by_username(db, "admin")
            admin.password_hash = security.hash_password("Admin!0000")
            admin.must_change_password = False
            db.commit()
        finally:
            db.close()
        test_client.main = main  # type: ignore[attr-defined]
        yield test_client


_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _csrf(client, url: str) -> str:
    html = client.get(url).text
    m = _CSRF_RE.search(html)
    assert m, f"no csrf token on {url}"
    return m.group(1)


def login(client):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"username": "admin", "password": "Admin!0000", "csrf_token": token},
        follow_redirects=False,
    )


def _admin_id() -> int:
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_user_by_username(db, "admin").id
    finally:
        db.close()


DAY = date(2026, 7, 22)


def _entry(user_id, start, end):
    from app import database, models

    db = database.SessionLocal()
    try:
        e = models.TimeEntry(
            user_id=user_id, company_id=None, work_date=DAY,
            start_time=start, end_time=end, break_minutes=0, break_started_at=None,
            is_open=False, notes="", status=models.TimeEntryStatus.APPROVED, is_manual=False,
        )
        db.add(e)
        db.commit()
        return e.id
    finally:
        db.close()


def test_version(client):
    assert client.main.APP_VERSION == "0.20.5"
    assert client.get("/health").json()["version"] == "0.20.5"


def test_crud_new_conflict_error_names_booking(client):
    from app import crud, database, models, schemas

    uid = _admin_id()
    a = _entry(uid, time(14, 18), time(19, 20))
    _entry(uid, time(20, 0), time(21, 0))  # nicht überlappend

    db = database.SessionLocal()
    try:
        with pytest.raises(ValueError) as excinfo:
            crud.update_time_entry(
                db, a,
                schemas.TimeEntryCreate(
                    user_id=uid, company_id=None, work_date=DAY,
                    start_time=time(20, 30), end_time=time(20, 45),
                    break_minutes=0, break_started_at=None, is_open=False,
                    notes="", status=models.TimeEntryStatus.APPROVED, is_manual=False,
                ),
                reason="Test: Korrektur",
            )
    finally:
        db.close()
    text = str(excinfo.value)
    assert text.startswith("OVERLAPPING_TIME_ENTRY")
    # Detail nennt die kollidierende Buchung 20:00–21:00 am 22.07.2026
    assert "20:00" in text and "21:00" in text and "22.07.2026" in text


def test_route_overlap_shows_confirmation_with_detail(client):
    """Seit 0.9.19 fragt die Route bei einem neuen Konflikt nach (statt hart
    abzulehnen) und nennt dabei die betroffene Buchung."""
    login(client)
    uid = _admin_id()
    a = _entry(uid, time(14, 18), time(19, 20))
    _entry(uid, time(20, 0), time(21, 0))

    token = _csrf(client, f"/admin/time-entries/{a}/edit?next=/admin/reports/time&user={uid}")
    response = client.post(
        f"/admin/time-entries/{a}/update",
        data={
            "csrf_token": token, "user_id": str(uid), "work_date": DAY.isoformat(),
            "change_reason": "Test: Korrektur",
            "start_time": "20:30", "end_time": "20:45", "break_minutes": "0",
            "notes": "", "next_url": "/admin/reports/time",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    html = response.text
    assert "Überschneidung bestätigen" in html
    # Nennt die betroffene Buchung 20:00–21:00
    assert "20:00" in html and "21:00" in html
    assert 'name="confirm_overwrite"' in html


def test_shrink_still_ok_and_no_error_detail(client):
    """Kontrolle: der eigentliche Fix (Verkürzen trotz Überlappung) bleibt."""
    from app import crud, database, models, schemas

    uid = _admin_id()
    a = _entry(uid, time(14, 18), time(19, 20))
    _entry(uid, time(15, 0), time(17, 0))  # überlappt bereits das Original

    db = database.SessionLocal()
    try:
        updated = crud.update_time_entry(
            db, a,
            schemas.TimeEntryCreate(
                user_id=uid, company_id=None, work_date=DAY,
                start_time=time(14, 18), end_time=time(16, 0),
                break_minutes=0, break_started_at=None, is_open=False,
                notes="", status=models.TimeEntryStatus.APPROVED, is_manual=False,
            ),
            reason="Test: Korrektur",
        )
        assert updated.end_time == time(16, 0)
    finally:
        db.close()
