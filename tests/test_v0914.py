"""Regression tests for 0.9.14 – manual entries while work time is running.

Covers: version bump, and ``crud.create_manual_time_entry``: inserting a manual
booking inside the currently running entry splits it (finished part keeps the
accumulated breaks, the running entry continues after the insert with company/
notes intact), boundary cases (insert starts exactly at the running start),
rejections (running break, partial overlap / future end, collisions with other
closed entries), the unchanged behaviour without a running entry, and the /time
route messages.
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


def _start_running_entry(user_id: int, started_at: datetime, *, company_id=None, notes="", break_minutes=0):
    from app import crud, database

    db = database.SessionLocal()
    try:
        entry = crud.start_running_entry(
            db, user_id=user_id, started_at=started_at, company_id=company_id, notes=notes,
        )
        if break_minutes:
            entry.break_minutes = break_minutes
            db.commit()
        return entry.id
    finally:
        db.close()


def _manual_entry_payload(user_id: int, start: datetime, end: datetime, **overrides):
    from app import models, schemas

    payload = dict(
        user_id=user_id,
        company_id=None,
        work_date=start.date(),
        start_time=start.time(),
        end_time=end.time(),
        break_minutes=0,
        break_started_at=None,
        is_open=False,
        notes="Telefonat",
        status=models.TimeEntryStatus.PENDING,
        is_manual=True,
    )
    payload.update(overrides)
    return schemas.TimeEntryCreate(**payload)


def _entries_for(user_id: int):
    from app import database, models

    db = database.SessionLocal()
    try:
        return (
            db.query(models.TimeEntry)
            .filter(models.TimeEntry.user_id == user_id)
            .order_by(models.TimeEntry.work_date, models.TimeEntry.start_time)
            .all()
        )
    finally:
        db.close()


# --- version -------------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.19.0"
    assert client.get("/health").json()["version"] == "0.19.0"


# --- split behaviour --------------------------------------------------------------

def test_manual_entry_inside_running_entry_splits(client):
    from app import crud, database, models

    uid = _admin_id()
    now = datetime.now()
    work_start = now - timedelta(hours=3)
    _start_running_entry(uid, work_start, notes="Baustelle", break_minutes=15)

    call_start = now - timedelta(hours=1)
    call_end = call_start + timedelta(minutes=30)
    db = database.SessionLocal()
    try:
        manual, split = crud.create_manual_time_entry(
            db, _manual_entry_payload(uid, call_start, call_end)
        )
        assert split is True
        assert manual.status == models.TimeEntryStatus.PENDING
    finally:
        db.close()

    entries = _entries_for(uid)
    assert len(entries) == 3
    first, manual_entry, running = entries
    # Erster Teil: abgeschlossen, behält Pausenminuten und Kommentar
    assert first.is_open is False
    assert first.start_time == work_start.time().replace(microsecond=0)
    assert first.end_time == call_start.time().replace(microsecond=0)
    assert first.break_minutes == 15
    assert first.notes == "Baustelle"
    assert first.status == models.TimeEntryStatus.APPROVED
    # Nachtrag in der Mitte
    assert manual_entry.is_manual and manual_entry.status == models.TimeEntryStatus.PENDING
    # Laufende Buchung: läuft ab Nachtragsende weiter, Pausen zurückgesetzt
    assert running.is_open is True
    assert running.start_time == call_end.time().replace(microsecond=0)
    assert running.break_minutes == 0
    assert running.notes == "Baustelle"


def test_manual_entry_starting_at_running_start(client):
    from app import crud, database

    uid = _admin_id()
    now = datetime.now()
    work_start = (now - timedelta(hours=2)).replace(microsecond=0)
    _start_running_entry(uid, work_start, break_minutes=10)

    call_end = work_start + timedelta(minutes=20)
    db = database.SessionLocal()
    try:
        _, split = crud.create_manual_time_entry(
            db, _manual_entry_payload(uid, work_start, call_end)
        )
        assert split is True
    finally:
        db.close()

    entries = _entries_for(uid)
    # Kein leerer erster Teil: nur Nachtrag + weiterlaufende Buchung
    assert len(entries) == 2
    manual_entry, running = entries
    assert manual_entry.is_manual
    assert running.is_open is True
    assert running.start_time == call_end.time()
    # Pausen bleiben an der weiterlaufenden Buchung, wenn kein erster Teil existiert
    assert running.break_minutes == 10


def test_manual_entry_with_running_break_rejected(client):
    from app import crud, database

    uid = _admin_id()
    now = datetime.now()
    _start_running_entry(uid, now - timedelta(hours=2))
    db = database.SessionLocal()
    try:
        entry = crud.get_open_time_entry(db, uid)
        crud.start_break(db, entry, now - timedelta(minutes=5))
        with pytest.raises(ValueError, match="BREAK_RUNNING"):
            crud.create_manual_time_entry(
                db,
                _manual_entry_payload(uid, now - timedelta(hours=1), now - timedelta(minutes=30)),
            )
    finally:
        db.close()


def test_manual_entry_partially_overlapping_rejected(client):
    from app import crud, database

    uid = _admin_id()
    now = datetime.now()
    work_start = now - timedelta(hours=1)
    _start_running_entry(uid, work_start)
    db = database.SessionLocal()
    try:
        # beginnt vor der laufenden Buchung
        with pytest.raises(ValueError, match="OVERLAPPING_TIME_ENTRY"):
            crud.create_manual_time_entry(
                db,
                _manual_entry_payload(uid, work_start - timedelta(minutes=30), work_start + timedelta(minutes=10)),
            )
        # endet in der Zukunft
        with pytest.raises(ValueError, match="OVERLAPPING_TIME_ENTRY"):
            crud.create_manual_time_entry(
                db,
                _manual_entry_payload(uid, now - timedelta(minutes=10), now + timedelta(hours=1)),
            )
    finally:
        db.close()

    # Laufende Buchung unverändert
    entries = _entries_for(uid)
    assert len(entries) == 1 and entries[0].is_open


def test_manual_entry_partially_overlapping_closed_entry_rejected(client):
    """Nur teilweise Überlappung mit einer abgeschlossenen Buchung (nicht
    vollständig umschlossen) wird weiterhin abgelehnt."""
    from app import crud, database, models, schemas

    uid = _admin_id()
    day = date.today() - timedelta(days=1)
    db = database.SessionLocal()
    try:
        crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=uid,
                company_id=None,
                work_date=day,
                start_time=time(8, 0),
                end_time=time(9, 0),
                break_minutes=0,
                break_started_at=None,
                is_open=False,
                notes="",
                status=models.TimeEntryStatus.APPROVED,
                is_manual=False,
            ),
        )
        # Beginnt innerhalb, endet aber nach der Bestandsbuchung → nicht umschlossen.
        with pytest.raises(ValueError, match="OVERLAPPING_TIME_ENTRY"):
            crud.create_manual_time_entry(
                db,
                _manual_entry_payload(
                    uid,
                    datetime.combine(day, time(8, 30)),
                    datetime.combine(day, time(9, 30)),
                ),
            )
    finally:
        db.close()


def test_manual_entry_without_running_entry_unchanged(client):
    from app import crud, database

    uid = _admin_id()
    yesterday = datetime.combine(date.today() - timedelta(days=1), datetime.min.time())
    db = database.SessionLocal()
    try:
        manual, split = crud.create_manual_time_entry(
            db,
            _manual_entry_payload(uid, yesterday.replace(hour=9), yesterday.replace(hour=10)),
        )
        assert split is False and manual.is_manual
    finally:
        db.close()


def test_manual_entry_outside_running_entry_no_split(client):
    """Nachtrag für gestern, während heute Arbeitszeit läuft → kein Split."""
    from app import crud, database

    uid = _admin_id()
    now = datetime.now()
    _start_running_entry(uid, now - timedelta(hours=2))
    yesterday = datetime.combine(date.today() - timedelta(days=1), datetime.min.time())
    db = database.SessionLocal()
    try:
        _, split = crud.create_manual_time_entry(
            db,
            _manual_entry_payload(uid, yesterday.replace(hour=9), yesterday.replace(hour=10)),
        )
        assert split is False
    finally:
        db.close()
    entries = _entries_for(uid)
    assert sum(1 for e in entries if e.is_open) == 1


# --- /time route -------------------------------------------------------------------

def test_time_route_splits_and_reports_message(client):
    login(client)
    uid = _admin_id()
    now = datetime.now()
    _start_running_entry(uid, now - timedelta(hours=3))
    token = _csrf(client, "/dashboard")
    call_start = (now - timedelta(hours=1)).replace(second=0, microsecond=0)
    call_end = call_start + timedelta(minutes=30)
    response = client.post(
        "/time",
        data={
            "csrf_token": token,
            "work_date": call_start.date().isoformat(),
            "start_time": call_start.strftime("%H:%M"),
            "end_time": call_end.strftime("%H:%M"),
            "break_minutes": "0",
            "notes": "Telefonat Kunde X",
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "geteilt" in response.headers["location"]
    entries = _entries_for(uid)
    assert len(entries) == 3
    assert sum(1 for e in entries if e.is_open) == 1
    assert any(e.is_manual and e.notes == "Telefonat Kunde X" for e in entries)


def test_time_route_break_running_message(client):
    from app import crud, database

    login(client)
    uid = _admin_id()
    now = datetime.now()
    _start_running_entry(uid, now - timedelta(hours=2))
    db = database.SessionLocal()
    try:
        crud.start_break(db, crud.get_open_time_entry(db, uid), now - timedelta(minutes=5))
    finally:
        db.close()
    token = _csrf(client, "/dashboard")
    call_start = (now - timedelta(hours=1)).replace(second=0, microsecond=0)
    response = client.post(
        "/time",
        data={
            "csrf_token": token,
            "work_date": call_start.date().isoformat(),
            "start_time": call_start.strftime("%H:%M"),
            "end_time": (call_start + timedelta(minutes=15)).strftime("%H:%M"),
            "break_minutes": "0",
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert "Pause" in response.headers["location"]
