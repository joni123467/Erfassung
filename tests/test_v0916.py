"""Regression tests for 0.9.16 – editing a booking is not blocked by
pre-existing overlaps.

Reproduces the reported bug: an automatic entry 14:18–19:20 could not be
shortened to 16:00 ("Zeiten überschneiden sich …") because another entry
(a still-running open entry whose window extends to "now", or an already
existing double booking) overlapped it. Shrinking/adjusting must be allowed as
long as no *new* overlap is introduced; genuinely new conflicts stay rejected.
"""

from __future__ import annotations

import re
import sys
from datetime import date, time

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


def _entry(user_id, start, end, *, is_open=False, notes="", status=None, is_manual=False):
    from app import database, models

    db = database.SessionLocal()
    try:
        entry = models.TimeEntry(
            user_id=user_id, company_id=None, work_date=DAY,
            start_time=start, end_time=end, break_minutes=0, break_started_at=None,
            is_open=is_open, notes=notes,
            status=status or models.TimeEntryStatus.APPROVED, is_manual=is_manual,
        )
        db.add(entry)
        db.commit()
        return entry.id
    finally:
        db.close()


def _update(entry_id, user_id, start, end):
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        return crud.update_time_entry(
            db, entry_id,
            schemas.TimeEntryCreate(
                user_id=user_id, company_id=None, work_date=DAY,
                start_time=start, end_time=end, break_minutes=0, break_started_at=None,
                is_open=False, notes="", status=models.TimeEntryStatus.APPROVED,
                is_manual=False,
            ),
            reason="Test: Korrektur",
        )
    finally:
        db.close()


def _get(entry_id):
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_time_entry(db, entry_id)
    finally:
        db.close()


# --- version -------------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.20.4"
    assert client.get("/health").json()["version"] == "0.20.4"


# --- the reported case ---------------------------------------------------------

def test_shrink_entry_despite_running_open_entry(client):
    """14:18–19:20 verkürzen auf 16:00, obwohl eine noch laufende Buchung das
    Fenster (bis „jetzt") überlappt."""
    uid = _admin_id()
    hist = _entry(uid, time(14, 18), time(19, 20), notes="Bis 16:00")
    _entry(uid, time(6, 0), time(6, 0), is_open=True, notes="läuft noch")

    updated = _update(hist, uid, time(14, 18), time(16, 0))
    assert updated is not None
    assert updated.start_time == time(14, 18) and updated.end_time == time(16, 0)


def test_shrink_entry_despite_existing_double_booking(client):
    """Zwei bereits überlappende abgeschlossene Buchungen: die eine lässt sich
    trotzdem verkürzen."""
    uid = _admin_id()
    a = _entry(uid, time(14, 18), time(19, 20), notes="A")
    _entry(uid, time(15, 0), time(17, 0), notes="B überlappt")

    updated = _update(a, uid, time(14, 18), time(16, 0))
    assert updated.end_time == time(16, 0)


def test_new_conflict_still_rejected(client):
    """Wird die Buchung auf einen Zeitraum verschoben, der eine bislang NICHT
    überlappende Buchung trifft, bleibt die Ablehnung."""
    uid = _admin_id()
    a = _entry(uid, time(14, 18), time(19, 20), notes="A")
    _entry(uid, time(20, 0), time(21, 0), notes="Später")

    with pytest.raises(ValueError, match="OVERLAPPING_TIME_ENTRY"):
        _update(a, uid, time(20, 30), time(20, 45))
    # Unverändert
    assert _get(a).end_time == time(19, 20)


def test_edit_route_shrink_despite_overlap(client):
    """Über die HTTP-Route /admin/time-entries/{id}/update."""
    login(client)
    uid = _admin_id()
    hist = _entry(uid, time(14, 18), time(19, 20), notes="Bis 16:00")
    _entry(uid, time(6, 0), time(6, 0), is_open=True, notes="läuft noch")

    token = _csrf(client, f"/admin/time-entries/{hist}/edit?next=/admin/reports/time&user={uid}")
    response = client.post(
        f"/admin/time-entries/{hist}/update",
        data={
            "csrf_token": token,
            "change_reason": "Test: Korrektur",
            "user_id": str(uid),
            "work_date": DAY.isoformat(),
            "start_time": "14:18",
            "end_time": "16:00",
            "break_minutes": "0",
            "notes": "Bis 16:00",
            "next_url": "/admin/reports/time",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "msg=" in response.headers["location"]
    assert _get(hist).end_time == time(16, 0)


def test_regular_edit_without_overlap_still_works(client):
    """Sicherstellen, dass gewöhnliche Änderungen ohne Konflikt unverändert
    funktionieren."""
    uid = _admin_id()
    e = _entry(uid, time(8, 0), time(12, 0))
    updated = _update(e, uid, time(8, 0), time(11, 30))
    assert updated.end_time == time(11, 30)
