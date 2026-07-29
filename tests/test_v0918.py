"""Regression tests for 0.9.18 – seconds-precision boundary between adjacent
bookings no longer causes a false overlap on edit.

Reproduces the reported case: two adjacent automatic (terminal) bookings share
the exact clock second (B ends 14:18:45, A starts 14:18:45). The edit form works
at minute precision, so saving A with start "14:18" (→ 14:18:00) moved the start
45 s earlier and produced a sub-minute overlap with B ("Zeiten überschneiden
sich mit einer bestehenden Buchung: … 11:08–14:18"). Overlap detection is now
minute-precise, so such boundary touches are not treated as conflicts, while
real overlaps (≥ 1 minute) stay rejected.
"""

from __future__ import annotations

import re
import sys
from datetime import date, time

import pytest


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


def _raw_entry(user_id, start, end, *, company_id=None, notes="", is_manual=False):
    """Insert with second precision (like a terminal import), bypassing checks."""
    from app import database, models

    db = database.SessionLocal()
    try:
        e = models.TimeEntry(
            user_id=user_id, company_id=company_id, work_date=DAY,
            start_time=start, end_time=end, break_minutes=0, break_started_at=None,
            is_open=False, notes=notes, status=models.TimeEntryStatus.APPROVED,
            is_manual=is_manual, source="timemoto", external_id=f"{start}-{end}",
        )
        db.add(e)
        db.commit()
        return e.id
    finally:
        db.close()


def _update(entry_id, uid, start, end):
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        return crud.update_time_entry(
            db, entry_id,
            schemas.TimeEntryCreate(
                user_id=uid, company_id=None, work_date=DAY, start_time=start, end_time=end,
                break_minutes=0, break_started_at=None, is_open=False, notes="",
                status=models.TimeEntryStatus.APPROVED, is_manual=False,
            ),
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
    assert client.main.APP_VERSION == "0.10.1"
    assert client.get("/health").json()["version"] == "0.10.1"


# --- the exact reported case ---------------------------------------------------

def test_edit_adjacent_seconds_boundary(client):
    uid = _admin_id()
    # B: 11:08:00–14:18:45  (Allgemeine Arbeitszeit)
    _raw_entry(uid, time(11, 8, 0), time(14, 18, 45))
    # A: 14:18:45–19:20:00  (Auftrag), soll auf 16:00 verkürzt werden
    a = _raw_entry(uid, time(14, 18, 45), time(19, 20, 0), notes="Bis 16:00")

    # Formular sendet Minuten: start 14:18(:00), end 16:00 → früher 45s-Scheinkonflikt
    updated = _update(a, uid, time(14, 18), time(16, 0))
    assert updated is not None
    assert updated.end_time == time(16, 0)


def test_edit_route_adjacent_seconds_boundary(client):
    login(client)
    uid = _admin_id()
    _raw_entry(uid, time(11, 8, 0), time(14, 18, 45))
    a = _raw_entry(uid, time(14, 18, 45), time(19, 20, 0), notes="Bis 16:00")

    token = _csrf(client, f"/admin/time-entries/{a}/edit?next=/admin/reports/time&user={uid}")
    response = client.post(
        f"/admin/time-entries/{a}/update",
        data={
            "csrf_token": token, "user_id": str(uid), "work_date": DAY.isoformat(),
            "start_time": "14:18", "end_time": "16:00", "break_minutes": "0",
            "notes": "Bis 16:00", "next_url": "/admin/reports/time",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "msg=" in response.headers["location"]
    assert _get(a).end_time == time(16, 0)


def test_real_overlap_still_rejected(client):
    """Echte Überschneidung ≥ 1 Minute bleibt abgelehnt."""
    uid = _admin_id()
    _raw_entry(uid, time(11, 8, 0), time(14, 18, 45))
    a = _raw_entry(uid, time(14, 18, 45), time(19, 20, 0))

    with pytest.raises(ValueError, match="OVERLAPPING_TIME_ENTRY"):
        # Start auf 13:00 → überlappt B (11:08–14:18) um >1 Stunde
        _update(a, uid, time(13, 0), time(16, 0))
    assert _get(a).start_time == time(14, 18, 45)


def test_new_manual_entry_touching_seconds_boundary(client):
    """Auch beim Anlegen: eine Buchung, die minutengenau an eine Sekunden-Grenze
    anschließt, wird nicht als Überschneidung abgelehnt."""
    from app import crud, database, models, schemas

    uid = _admin_id()
    _raw_entry(uid, time(8, 0, 0), time(9, 0, 30))  # endet 09:00:30
    db = database.SessionLocal()
    try:
        # Neue Buchung 09:00–10:00 (Minute) grenzt an 09:00:30 → kein Konflikt
        entry, _ = crud.create_manual_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=uid, company_id=None, work_date=DAY,
                start_time=time(9, 0), end_time=time(10, 0),
                break_minutes=0, break_started_at=None, is_open=False, notes="neu",
                status=models.TimeEntryStatus.PENDING, is_manual=True,
            ),
        )
        assert entry.id is not None
    finally:
        db.close()
