"""Regression tests for 0.9.19 – department administrators and confirmed
overwriting of conflicting bookings.

Part 1 (Abteilungsadministration): the Administration area is reachable for any
user holding at least one admin permission (not only ``is_admin``), ``/admin``
lands on the first permitted page, and ``can_manage_users`` is scopeable so a
department admin manages only their own group (including protection against
privilege escalation via group assignment).

Part 2 (Überschreiben): editing a booking into a genuinely new conflict now
shows a confirmation page listing the affected bookings; confirming resolves the
conflicts (delete / shorten / split) instead of rejecting the change.
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


def login(client, username: str = "admin", password: str = "Admin!0000"):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _create_group(name="Gruppe"):
    from app import crud, database, schemas

    db = database.SessionLocal()
    try:
        return crud.create_group(db, schemas.GroupCreate(name=name)).id
    finally:
        db.close()


def _create_role(name, permissions):
    """Rolle mit Berechtigungen ``{key: scope}`` (RBAC ab 0.10.0)."""
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.create_role(db, name=name, permissions=permissions).id
    finally:
        db.close()


def _create_member(group_id, username, *, roles=()):
    from app import crud, database, schemas, security

    db = database.SessionLocal()
    try:
        u = crud.create_user(
            db,
            schemas.UserCreate(
                username=username, full_name=f"User {username}",
                email=f"{username}@example.com", password="Worker!0000",
                group_ids=[group_id] if group_id else [],
                role_ids=list(roles),
            ),
        )
        u.must_change_password = False
        u.password_hash = security.hash_password("Worker!0000")
        db.commit()
        return u.id
    finally:
        db.close()


DAY = date(2026, 7, 22)


def _entry(user_id, start, end, *, notes="", is_open=False):
    from app import database, models

    db = database.SessionLocal()
    try:
        e = models.TimeEntry(
            user_id=user_id, company_id=None, work_date=DAY,
            start_time=start, end_time=end, break_minutes=0, break_started_at=None,
            is_open=is_open, notes=notes, status=models.TimeEntryStatus.APPROVED,
            is_manual=False,
        )
        db.add(e)
        db.commit()
        return e.id
    finally:
        db.close()


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


def _get(entry_id):
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_time_entry(db, entry_id)
    finally:
        db.close()


@pytest.fixture()
def dept(client):
    """Abteilungsleitung (Rolle mit Gruppen-Scope) + Kollege + Fremder.

    Seit 0.10.0 kommen die Rechte aus einer Rolle; die Gruppe legt nur noch
    fest, für wen der Geltungsbereich „Eigene Gruppen" gilt.
    """
    lead_group = _create_group("Abteilung A")
    other_group = _create_group("Abteilung B")
    lead_role = _create_role(
        "Abteilungsleitung",
        {
            "User.View": "groups", "User.Create": "groups", "User.Edit": "groups",
            "Time.Approve": "groups", "Time.Edit": "groups", "Time.View": "groups",
        },
    )
    return {
        "lead_group": lead_group,
        "other_group": other_group,
        "lead_role": lead_role,
        "lead": _create_member(lead_group, "deptlead", roles=[lead_role]),
        "mate": _create_member(lead_group, "deptmate"),
        "outsider": _create_member(other_group, "outsider"),
    }


# --- version -------------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.10.1"
    assert client.get("/health").json()["version"] == "0.10.1"


# --- Teil 1: Administrationszugang für Abteilungsadmins --------------------------

def test_admin_link_visible_for_department_admin(client, dept):
    login(client, "deptlead", "Worker!0000")
    html = client.get("/dashboard").text
    assert 'href="/admin"' in html, "Administration-Link fehlt für Abteilungsadmin"


def test_admin_link_hidden_without_any_admin_permission(client):
    group = _create_group("Nur Mitarbeiter")
    _create_member(group, "plain")
    login(client, "plain", "Worker!0000")
    html = client.get("/dashboard").text
    assert 'href="/admin"' not in html


def test_admin_portal_lands_on_permitted_page(client, dept):
    login(client, "deptlead", "Worker!0000")
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users"

    # Ohne Benutzerverwaltung: erste erlaubte Seite ist Freigaben
    group = _create_group("Nur Freigaben")
    role = _create_role("Freigeber", {"Time.Approve": "groups"})
    _create_member(group, "approver", roles=[role])
    login(client, "approver", "Worker!0000")
    response = client.get("/admin", follow_redirects=False)
    assert response.headers["location"] == "/admin/approvals"


def test_admin_portal_denied_without_permissions(client):
    group = _create_group("Ohne Rechte")
    _create_member(group, "nobody")
    login(client, "nobody", "Worker!0000")
    response = client.get("/admin", follow_redirects=False)
    assert response.headers["location"] == "/dashboard"


# --- Teil 1: Benutzerverwaltung scoped -------------------------------------------

def test_user_list_limited_to_own_group(client, dept):
    login(client, "deptlead", "Worker!0000")
    html = client.get("/admin/users").text
    assert "User deptmate" in html
    assert "User outsider" not in html


def test_department_admin_can_open_own_member(client, dept):
    login(client, "deptlead", "Worker!0000")
    assert client.get(f"/admin/users/{dept['mate']}", follow_redirects=False).status_code == 200
    response = client.get(f"/admin/users/{dept['outsider']}", follow_redirects=False)
    assert response.status_code == 303
    assert "Gruppen" in response.headers["location"]


def test_department_admin_cannot_edit_foreign_user(client, dept):
    login(client, "deptlead", "Worker!0000")
    token = _csrf(client, f"/admin/users/{dept['mate']}")
    response = client.post(
        f"/admin/users/{dept['outsider']}/update",
        data={
            "csrf_token": token, "username": "outsider", "full_name": "Gekapert",
            "email": "outsider@example.com", "standard_weekly_hours": "40",
            "group_ids": [str(dept["other_group"])], "annual_vacation_days": "30",
        },
        follow_redirects=False,
    )
    assert "Gruppen" in response.headers["location"]


def test_department_admin_cannot_assign_foreign_group(client, dept):
    """Rechteausweitung verhindern: fremde Gruppen sind nicht zuweisbar."""
    from app import crud, database

    login(client, "deptlead", "Worker!0000")
    token = _csrf(client, f"/admin/users/{dept['mate']}")
    response = client.post(
        f"/admin/users/{dept['mate']}/update",
        data={
            "csrf_token": token, "username": "deptmate", "full_name": "User deptmate",
            "email": "deptmate@example.com", "standard_weekly_hours": "40",
            "group_ids": [str(dept["other_group"])], "annual_vacation_days": "30",
        },
        follow_redirects=False,
    )
    assert "Gruppe+darf+nicht+zugewiesen+werden" in response.headers["location"]
    db = database.SessionLocal()
    try:
        assert crud.get_user(db, dept["mate"]).group_ids == {dept["lead_group"]}
    finally:
        db.close()

    # Formular bietet nur die eigene Gruppe an, und keine Rollen
    html = client.get(f"/admin/users/{dept['mate']}").text
    assert "Abteilung A" in html
    assert "Abteilung B" not in html
    assert 'name="role_ids"' not in html


def test_full_admin_still_sees_everyone(client, dept):
    login(client)
    html = client.get("/admin/users").text
    assert "User deptmate" in html and "User outsider" in html


# --- Teil 2: Überschreiben mit Bestätigung ---------------------------------------

def test_overwrite_confirmation_lists_affected_booking(client):
    from app import crud, database

    login(client)
    db = database.SessionLocal()
    try:
        uid = crud.get_user_by_username(db, "admin").id
    finally:
        db.close()
    a = _entry(uid, time(8, 0), time(9, 0), notes="A")
    _entry(uid, time(10, 0), time(12, 0), notes="B")

    token = _csrf(client, f"/admin/time-entries/{a}/edit?next=/admin/reports/time&user={uid}")
    response = client.post(
        f"/admin/time-entries/{a}/update",
        data={
            "csrf_token": token, "user_id": str(uid), "work_date": DAY.isoformat(),
            "start_time": "10:30", "end_time": "11:00", "break_minutes": "0",
            "notes": "A", "next_url": "/admin/reports/time",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    html = response.text
    assert "Überschneidung bestätigen" in html
    assert "10:00" in html and "12:00" in html
    # Noch nichts geändert
    assert _get(a).start_time == time(8, 0)


def test_overwrite_confirmed_splits_covered_booking(client):
    """Neue Zeiten liegen mitten in B → B wird geteilt."""
    from app import crud, database

    login(client)
    db = database.SessionLocal()
    try:
        uid = crud.get_user_by_username(db, "admin").id
    finally:
        db.close()
    a = _entry(uid, time(8, 0), time(9, 0), notes="A")
    _entry(uid, time(10, 0), time(12, 0), notes="B")

    token = _csrf(client, f"/admin/time-entries/{a}/edit?next=/admin/reports/time&user={uid}")
    response = client.post(
        f"/admin/time-entries/{a}/update",
        data={
            "csrf_token": token, "user_id": str(uid), "work_date": DAY.isoformat(),
            "start_time": "10:30", "end_time": "11:00", "break_minutes": "0",
            "notes": "A", "next_url": "/admin/reports/time", "confirm_overwrite": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303 and "msg=" in response.headers["location"]
    segments = [(e.start_time, e.end_time, e.notes) for e in _entries(uid)]
    assert (time(10, 0), time(10, 30), "B") in segments
    assert (time(10, 30), time(11, 0), "A") in segments
    assert (time(11, 0), time(12, 0), "B") in segments


def test_overwrite_confirmed_deletes_fully_covered_booking(client):
    from app import crud, database

    login(client)
    db = database.SessionLocal()
    try:
        uid = crud.get_user_by_username(db, "admin").id
    finally:
        db.close()
    a = _entry(uid, time(8, 0), time(9, 0), notes="A")
    b = _entry(uid, time(10, 0), time(11, 0), notes="B")

    token = _csrf(client, f"/admin/time-entries/{a}/edit?next=/admin/reports/time&user={uid}")
    client.post(
        f"/admin/time-entries/{a}/update",
        data={
            "csrf_token": token, "user_id": str(uid), "work_date": DAY.isoformat(),
            "start_time": "09:30", "end_time": "11:30", "break_minutes": "0",
            "notes": "A", "next_url": "/admin/reports/time", "confirm_overwrite": "1",
        },
        follow_redirects=False,
    )
    assert _get(b) is None, "vollständig überdeckte Buchung wurde nicht entfernt"
    assert _get(a).start_time == time(9, 30) and _get(a).end_time == time(11, 30)


def test_overwrite_confirmed_shortens_partial_overlap(client):
    from app import crud, database

    login(client)
    db = database.SessionLocal()
    try:
        uid = crud.get_user_by_username(db, "admin").id
    finally:
        db.close()
    a = _entry(uid, time(8, 0), time(9, 0), notes="A")
    b = _entry(uid, time(10, 0), time(12, 0), notes="B")

    token = _csrf(client, f"/admin/time-entries/{a}/edit?next=/admin/reports/time&user={uid}")
    client.post(
        f"/admin/time-entries/{a}/update",
        data={
            "csrf_token": token, "user_id": str(uid), "work_date": DAY.isoformat(),
            "start_time": "09:00", "end_time": "11:00", "break_minutes": "0",
            "notes": "A", "next_url": "/admin/reports/time", "confirm_overwrite": "1",
        },
        follow_redirects=False,
    )
    # B beginnt jetzt erst um 11:00
    assert _get(b).start_time == time(11, 0) and _get(b).end_time == time(12, 0)
    assert _get(a).end_time == time(11, 0)


def test_no_confirmation_without_conflict(client):
    """Ohne neuen Konflikt wird direkt gespeichert (keine Rückfrage)."""
    from app import crud, database

    login(client)
    db = database.SessionLocal()
    try:
        uid = crud.get_user_by_username(db, "admin").id
    finally:
        db.close()
    a = _entry(uid, time(8, 0), time(12, 0))

    token = _csrf(client, f"/admin/time-entries/{a}/edit?next=/admin/reports/time&user={uid}")
    response = client.post(
        f"/admin/time-entries/{a}/update",
        data={
            "csrf_token": token, "user_id": str(uid), "work_date": DAY.isoformat(),
            "start_time": "08:00", "end_time": "11:00", "break_minutes": "0",
            "notes": "", "next_url": "/admin/reports/time",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303 and "msg=" in response.headers["location"]
    assert _get(a).end_time == time(11, 0)


def test_overwrite_keeps_running_entry_alive(client):
    """Eine laufende Buchung wird nie gelöscht, sondern nachgeführt."""
    from app import crud, database, models

    login(client)
    db = database.SessionLocal()
    try:
        uid = crud.get_user_by_username(db, "admin").id
    finally:
        db.close()
    a = _entry(uid, time(8, 0), time(9, 0), notes="A")
    running = _entry(uid, time(10, 0), time(10, 0), notes="läuft", is_open=True)

    token = _csrf(client, f"/admin/time-entries/{a}/edit?next=/admin/reports/time&user={uid}")
    client.post(
        f"/admin/time-entries/{a}/update",
        data={
            "csrf_token": token, "user_id": str(uid), "work_date": DAY.isoformat(),
            "start_time": "09:30", "end_time": "11:00", "break_minutes": "0",
            "notes": "A", "next_url": "/admin/reports/time", "confirm_overwrite": "1",
        },
        follow_redirects=False,
    )
    survivor = _get(running)
    assert survivor is not None, "laufende Buchung darf nicht gelöscht werden"
    assert survivor.is_open is True
