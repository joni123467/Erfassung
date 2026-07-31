"""Regression tests for 0.9.15 – insert manual entries between existing bookings
and admin edit access from the reports view.

Covers: version bump, ``crud.create_manual_time_entry`` splitting a *closed*
entry that fully contains the new manual booking (attributes preserved, breaks
kept on the leading part), the boundary cases (starts at / ends at / exactly
covers the existing entry), the /time route splitting a closed entry, and the
edit links in the time report (present for editors, absent otherwise) plus the
edit page reachability for admins.
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime, time, timedelta

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


def login(client, username: str = "admin", password: str = "Admin!0000"):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _admin_id() -> int:
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_user_by_username(db, "admin").id
    finally:
        db.close()


DAY = date(2026, 6, 15)


def _closed_entry(user_id, start, end, *, company_id=None, notes="Büro",
                  breaks=0, status=None, is_manual=False):
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        entry = crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=user_id,
                company_id=company_id,
                work_date=DAY,
                start_time=start,
                end_time=end,
                break_minutes=breaks,
                break_started_at=None,
                is_open=False,
                notes=notes,
                status=status or models.TimeEntryStatus.APPROVED,
                is_manual=is_manual,
            ),
        )
        return entry.id
    finally:
        db.close()


def _manual_payload(user_id, start, end, **overrides):
    from app import models, schemas

    payload = dict(
        user_id=user_id, company_id=None, work_date=DAY,
        start_time=start, end_time=end, break_minutes=0, break_started_at=None,
        is_open=False, notes="Telefonat", status=models.TimeEntryStatus.PENDING,
        is_manual=True,
    )
    payload.update(overrides)
    return schemas.TimeEntryCreate(**payload)


def _entries(user_id):
    from app import database, models

    db = database.SessionLocal()
    try:
        return (
            db.query(models.TimeEntry)
            .filter(models.TimeEntry.user_id == user_id)
            .order_by(models.TimeEntry.start_time)
            .all()
        )
    finally:
        db.close()


def _insert(user_id, payload):
    from app import crud, database

    db = database.SessionLocal()
    try:
        entry, split = crud.create_manual_time_entry(db, payload)
        return entry, split
    finally:
        db.close()


# --- version -------------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.16.0"
    assert client.get("/health").json()["version"] == "0.16.0"


# --- split a closed entry ----------------------------------------------------------

def test_manual_entry_splits_closed_entry(client):
    from app import models

    uid = _admin_id()
    _closed_entry(uid, time(8, 0), time(12, 0), notes="Büro", breaks=30,
                  status=models.TimeEntryStatus.APPROVED, is_manual=False)

    _, split = _insert(uid, _manual_payload(uid, time(10, 0), time(10, 20)))
    assert split is True

    entries = _entries(uid)
    assert len(entries) == 3
    first, manual, second = entries
    # Erster Abschnitt behält Firma/Kommentar/Status/Pausen der Bestandsbuchung
    assert first.start_time == time(8, 0) and first.end_time == time(10, 0)
    assert first.break_minutes == 30
    assert first.notes == "Büro" and first.status == models.TimeEntryStatus.APPROVED
    assert first.is_manual is False
    # Nachtrag
    assert manual.start_time == time(10, 0) and manual.end_time == time(10, 20)
    assert manual.is_manual and manual.status == models.TimeEntryStatus.PENDING
    # Zweiter Abschnitt: gleiche Attribute, keine Pausen
    assert second.start_time == time(10, 20) and second.end_time == time(12, 0)
    assert second.break_minutes == 0
    assert second.notes == "Büro" and second.status == models.TimeEntryStatus.APPROVED
    assert second.is_manual is False


def test_manual_entry_at_start_of_closed_entry(client):
    uid = _admin_id()
    _closed_entry(uid, time(8, 0), time(12, 0), breaks=15)
    _, split = _insert(uid, _manual_payload(uid, time(8, 0), time(8, 30)))
    assert split is True
    entries = _entries(uid)
    assert len(entries) == 2
    manual, second = entries
    assert manual.is_manual and manual.start_time == time(8, 0)
    # Kein erster Abschnitt → Pausen bleiben am zweiten Abschnitt
    assert second.start_time == time(8, 30) and second.end_time == time(12, 0)
    assert second.break_minutes == 15


def test_manual_entry_at_end_of_closed_entry(client):
    uid = _admin_id()
    _closed_entry(uid, time(8, 0), time(12, 0), breaks=15)
    _, split = _insert(uid, _manual_payload(uid, time(11, 30), time(12, 0)))
    assert split is True
    entries = _entries(uid)
    assert len(entries) == 2
    first, manual = entries
    assert first.start_time == time(8, 0) and first.end_time == time(11, 30)
    assert first.break_minutes == 15
    assert manual.is_manual and manual.end_time == time(12, 0)


def test_manual_entry_covers_closed_entry_exactly(client):
    from app import models

    uid = _admin_id()
    _closed_entry(uid, time(8, 0), time(9, 0))
    _, split = _insert(uid, _manual_payload(uid, time(8, 0), time(9, 0)))
    assert split is True
    entries = _entries(uid)
    # Seit 0.14.0 wird die Bestandsbuchung storniert statt gelöscht: Sie bleibt
    # mit ihrer Historie erhalten und verweist auf den Nachtrag.
    from app import models as _models

    assert len(entries) == 2
    cancelled = [e for e in entries if e.status == _models.TimeEntryStatus.CANCELLED]
    assert len(cancelled) == 1
    assert cancelled[0].replaced_by_id is not None
    entries = [e for e in entries if e.status != _models.TimeEntryStatus.CANCELLED]
    assert len(entries) == 1
    assert entries[0].is_manual and entries[0].status == models.TimeEntryStatus.PENDING


def test_manual_entry_between_two_manual_entries(client):
    """Zwei manuelle Buchungen mit Lücke; Nachtrag in eine davon teilt nur diese."""
    from app import models

    uid = _admin_id()
    _closed_entry(uid, time(8, 0), time(10, 0), notes="A", is_manual=True,
                  status=models.TimeEntryStatus.PENDING)
    _closed_entry(uid, time(13, 0), time(15, 0), notes="B", is_manual=True,
                  status=models.TimeEntryStatus.PENDING)
    _, split = _insert(uid, _manual_payload(uid, time(9, 0), time(9, 15)))
    assert split is True
    entries = _entries(uid)
    starts = [(e.start_time, e.end_time) for e in entries]
    assert (time(8, 0), time(9, 0)) in starts
    assert (time(9, 0), time(9, 15)) in starts
    assert (time(9, 15), time(10, 0)) in starts
    assert (time(13, 0), time(15, 0)) in starts  # unverändert


# --- /time route splits a closed entry --------------------------------------------

def test_time_route_splits_closed_entry(client):
    login(client)
    uid = _admin_id()
    _closed_entry(uid, time(8, 0), time(12, 0), notes="Büro")
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/time",
        data={
            "csrf_token": token,
            "work_date": DAY.isoformat(),
            "start_time": "10:00",
            "end_time": "10:20",
            "break_minutes": "0",
            "notes": "Telefonat Kunde",
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "geteilt" in response.headers["location"]
    entries = _entries(uid)
    assert len(entries) == 3
    assert any(e.is_manual and e.notes == "Telefonat Kunde" for e in entries)


# --- admin edit links in the report -----------------------------------------------

def test_report_shows_edit_links_for_admin(client):
    login(client)
    uid = _admin_id()
    _closed_entry(uid, time(8, 0), time(12, 0))
    html = client.get("/admin/reports/time?view=month&month=2026-06").text
    assert "<th>Aktionen</th>" in html
    assert "/admin/time-entries/" in html and "/edit?next=" in html


def test_report_edit_link_absent_without_permission(client):
    """Ein Benutzer ohne 'Zeitbuchungen bearbeiten' sieht die Berichte, aber
    keine Bearbeiten-Aktionen."""
    from app import crud, database, schemas, security

    db = database.SessionLocal()
    try:
        group = crud.create_group(
            db, schemas.GroupCreate(name="Nur Lesen", can_view_time_reports=True)
        )
        worker = crud.create_user(
            db,
            schemas.UserCreate(
                username="reader", full_name="Reader", email="reader@example.com",
                password="Reader!0000", group_id=group.id,
            ),
        )
        worker.must_change_password = False
        worker.password_hash = security.hash_password("Reader!0000")
        db.commit()
    finally:
        db.close()

    login(client, "reader", "Reader!0000")
    html = client.get("/admin/reports/time").text
    assert "<th>Aktionen</th>" not in html
    assert "/edit?next=" not in html


def test_admin_can_open_and_update_entry(client):
    from app import database, models

    login(client)
    uid = _admin_id()
    entry_id = _closed_entry(uid, time(8, 0), time(12, 0), notes="Alt")
    # Bearbeitungsseite erreichbar
    page = client.get(f"/admin/time-entries/{entry_id}/edit?next=/admin/reports/time&user={uid}")
    assert page.status_code == 200
    assert 'name="notes"' in page.text
    # Update speichern
    token = _csrf(client, f"/admin/time-entries/{entry_id}/edit?next=/admin/reports/time&user={uid}")
    response = client.post(
        f"/admin/time-entries/{entry_id}/update",
        data={
            "csrf_token": token,
            "change_reason": "Test: Korrektur",
            "user_id": str(uid),
            "work_date": DAY.isoformat(),
            "start_time": "08:00",
            "end_time": "11:00",
            "break_minutes": "0",
            "notes": "Neu",
            "next_url": "/admin/reports/time",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303 and "msg=" in response.headers["location"]
    db = database.SessionLocal()
    try:
        entry = db.get(models.TimeEntry, entry_id)
        assert entry.notes == "Neu" and entry.end_time == time(11, 0)
    finally:
        db.close()
