"""Regression tests for 0.9.12 – team-level vs. global scope for team permissions.

Covers: version bump, the scope registry (``<key>_scope`` columns), scoped form
parsing (none/group/all incl. admin implies all), scope enforcement on the
approvals page and its status POSTs, on team/user reports, and on editing time
entries of other users, plus the schema migration for existing databases.
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


def _create_group(**overrides):
    from app import crud, database, schemas

    db = database.SessionLocal()
    try:
        payload = {"name": overrides.pop("name", "Testgruppe")}
        payload.update(overrides)
        group = crud.create_group(db, schemas.GroupCreate(**payload))
        return group.id
    finally:
        db.close()


def _create_member(group_id, username: str):
    from app import crud, database, schemas, security

    db = database.SessionLocal()
    try:
        user = crud.create_user(
            db,
            schemas.UserCreate(
                username=username,
                full_name=f"User {username}",
                email=f"{username}@example.com",
                password="Worker!0000",
                group_id=group_id,
            ),
        )
        user.must_change_password = False
        user.password_hash = security.hash_password("Worker!0000")
        db.commit()
        return user.id
    finally:
        db.close()


def _create_pending_entry(user_id: int, day: date):
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        entry = crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=user_id,
                company_id=None,
                work_date=day,
                start_time=time(8, 0),
                end_time=time(12, 0),
                break_minutes=0,
                break_started_at=None,
                is_open=False,
                notes="",
                status=models.TimeEntryStatus.PENDING,
                is_manual=True,
            ),
        )
        return entry.id
    finally:
        db.close()


def _create_pending_vacation(user_id: int, start: date, end: date):
    from app import crud, database, schemas

    db = database.SessionLocal()
    try:
        vacation = crud.create_vacation_request(
            db,
            schemas.VacationRequestCreate(
                user_id=user_id,
                start_date=start,
                end_date=end,
                comment="",
                use_overtime=False,
                overtime_minutes=0,
            ),
        )
        return vacation.id
    finally:
        db.close()


@pytest.fixture()
def team_setup(client):
    """Two groups: team lead (group-scoped rights) + a foreign group."""
    lead_group = _create_group(
        name="Teamleitung",
        can_approve_manual_entries=True,
        can_approve_manual_entries_scope="group",
        can_manage_vacations=True,
        can_manage_vacations_scope="group",
        can_view_time_reports=True,
        can_view_time_reports_scope="group",
        can_edit_time_entries=True,
        can_edit_time_entries_scope="group",
    )
    other_group = _create_group(name="Anderes Team")
    lead_id = _create_member(lead_group, "lead")
    mate_id = _create_member(lead_group, "mate")
    outsider_id = _create_member(other_group, "outsider")
    return {
        "lead_group": lead_group,
        "other_group": other_group,
        "lead": lead_id,
        "mate": mate_id,
        "outsider": outsider_id,
    }


# --- version -------------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.9.22"
    assert client.get("/health").json()["version"] == "0.9.22"


# --- registry / model ------------------------------------------------------------

def test_scope_columns_exist(client):
    from app import models, permissions

    # Team-Rechte (0.9.12) + Benutzerverwaltung (ab 0.9.19 ebenfalls scoped)
    assert set(permissions.SCOPED_KEYS) == {
        "can_approve_manual_entries",
        "can_manage_vacations",
        "can_view_time_reports",
        "can_edit_time_entries",
        "can_manage_users",
    }
    for key in permissions.SCOPED_KEYS:
        assert hasattr(models.Group, permissions.scope_column(key))


def test_group_form_scope_parsing(client):
    login(client)
    token = _csrf(client, "/admin/groups/new")
    client.post(
        "/admin/groups/create",
        data={
            "csrf_token": token,
            "name": "Scoped",
            "can_manage_vacations_scope": "group",
            "can_view_time_reports_scope": "all",
            "can_approve_manual_entries_scope": "none",
        },
        follow_redirects=False,
    )
    from app import crud, database

    db = database.SessionLocal()
    try:
        group = next(g for g in crud.get_groups(db) if g.name == "Scoped")
        assert group.can_manage_vacations and group.can_manage_vacations_scope == "group"
        assert group.can_view_time_reports and group.can_view_time_reports_scope == "all"
        assert not group.can_approve_manual_entries
        assert not group.can_edit_time_entries
    finally:
        db.close()

    html = client.get("/admin/groups").text
    assert "eigenes Team" in html


def test_admin_toggle_grants_all_scope(client):
    login(client)
    token = _csrf(client, "/admin/groups/new")
    client.post(
        "/admin/groups/create",
        data={"csrf_token": token, "name": "Vollzugriff", "is_admin": "on"},
        follow_redirects=False,
    )
    from app import crud, database

    db = database.SessionLocal()
    try:
        group = next(g for g in crud.get_groups(db) if g.name == "Vollzugriff")
        assert group.can_manage_vacations_scope == "all"
        assert group.can_edit_time_entries_scope == "all"
    finally:
        db.close()


# --- approvals scope --------------------------------------------------------------

def test_approvals_filtered_to_own_team(client, team_setup):
    mate_entry = _create_pending_entry(team_setup["mate"], date(2026, 7, 1))
    outsider_entry = _create_pending_entry(team_setup["outsider"], date(2026, 7, 1))
    _create_pending_vacation(team_setup["mate"], date(2026, 8, 3), date(2026, 8, 4))
    _create_pending_vacation(team_setup["outsider"], date(2026, 8, 5), date(2026, 8, 6))

    login(client, "lead", "Worker!0000")
    html = client.get("/admin/approvals").text
    assert "User mate" in html
    assert "User outsider" not in html

    # Approving a foreign entry is rejected server-side
    token = _csrf(client, "/admin/approvals")
    response = client.post(
        f"/admin/time-entries/{outsider_entry}/status",
        data={"csrf_token": token, "action": "approve"},
        follow_redirects=False,
    )
    assert "nicht+zu+deinem+Team" in response.headers["location"]
    from app import crud, database, models

    db = database.SessionLocal()
    try:
        assert crud.get_time_entry(db, outsider_entry).status == models.TimeEntryStatus.PENDING
    finally:
        db.close()

    # Approving a team member's entry works
    response = client.post(
        f"/admin/time-entries/{mate_entry}/status",
        data={"csrf_token": token, "action": "approve"},
        follow_redirects=False,
    )
    assert "msg=" in response.headers["location"]


def test_vacation_approval_scope(client, team_setup):
    mate_vac = _create_pending_vacation(team_setup["mate"], date(2026, 9, 1), date(2026, 9, 2))
    outsider_vac = _create_pending_vacation(team_setup["outsider"], date(2026, 9, 3), date(2026, 9, 4))

    login(client, "lead", "Worker!0000")
    token = _csrf(client, "/admin/approvals")
    response = client.post(
        f"/admin/vacations/{outsider_vac}/status",
        data={"csrf_token": token, "action": "approve"},
        follow_redirects=False,
    )
    assert "nicht+zu+deinem+Team" in response.headers["location"]
    response = client.post(
        f"/admin/vacations/{mate_vac}/status",
        data={"csrf_token": token, "action": "approve"},
        follow_redirects=False,
    )
    assert "msg=" in response.headers["location"]


# --- reports scope -----------------------------------------------------------------

def test_reports_filtered_to_own_team(client, team_setup):
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        for uid in (team_setup["mate"], team_setup["outsider"]):
            crud.create_time_entry(
                db,
                schemas.TimeEntryCreate(
                    user_id=uid,
                    company_id=None,
                    work_date=date.today().replace(day=1),
                    start_time=time(8, 0),
                    end_time=time(12, 0),
                    break_minutes=0,
                    break_started_at=None,
                    is_open=False,
                    notes="",
                    status=models.TimeEntryStatus.APPROVED,
                    is_manual=False,
                ),
            )
    finally:
        db.close()

    login(client, "lead", "Worker!0000")
    html = client.get("/admin/reports/time").text
    assert "User mate" in html
    assert "User outsider" not in html

    html = client.get("/admin/reports/users").text
    assert "User mate" in html
    assert "User outsider" not in html


def test_reports_all_scope_shows_everyone(client, team_setup):
    from app import database, models

    db = database.SessionLocal()
    try:
        group = db.get(models.Group, team_setup["lead_group"])
        group.can_view_time_reports_scope = "all"
        db.commit()
    finally:
        db.close()

    login(client, "lead", "Worker!0000")
    html = client.get("/admin/reports/users").text
    assert "User mate" in html
    assert "User outsider" in html


# --- edit time entries scope ---------------------------------------------------------

def test_edit_entries_scope(client, team_setup):
    mate_entry = _create_pending_entry(team_setup["mate"], date(2026, 7, 2))
    outsider_entry = _create_pending_entry(team_setup["outsider"], date(2026, 7, 2))

    login(client, "lead", "Worker!0000")
    # Own team: edit page opens
    response = client.get(f"/admin/time-entries/{mate_entry}/edit", follow_redirects=False)
    assert response.status_code == 200
    # Foreign team: redirected with error
    response = client.get(f"/admin/time-entries/{outsider_entry}/edit", follow_redirects=False)
    assert response.status_code == 303
    assert "nicht+zu+deinem+Team" in response.headers["location"]

    # Delete of a foreign entry is blocked
    token = _csrf(client, f"/admin/time-entries/{mate_entry}/edit")
    response = client.post(
        f"/admin/time-entries/{outsider_entry}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert "nicht+zu+deinem+Team" in response.headers["location"]
    from app import crud, database

    db = database.SessionLocal()
    try:
        assert crud.get_time_entry(db, outsider_entry) is not None
    finally:
        db.close()

    # Update must not reassign a booking to a foreign user either
    response = client.post(
        f"/admin/time-entries/{mate_entry}/update",
        data={
            "csrf_token": token,
            "user_id": str(team_setup["outsider"]),
            "work_date": "2026-07-02",
            "start_time": "08:00",
            "end_time": "12:00",
            "break_minutes": "0",
        },
        follow_redirects=False,
    )
    assert "nicht+zu+deinem+Team" in response.headers["location"]


# --- migration -------------------------------------------------------------------------

def test_migration_adds_scope_columns(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE groups (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            is_admin BOOLEAN DEFAULT 0,
            can_manage_users BOOLEAN DEFAULT 0,
            can_manage_vacations BOOLEAN DEFAULT 1,
            can_approve_manual_entries BOOLEAN DEFAULT 0,
            can_create_companies BOOLEAN DEFAULT 0,
            can_view_time_reports BOOLEAN DEFAULT 0,
            can_edit_time_entries BOOLEAN DEFAULT 0
        );
        INSERT INTO groups (name, is_admin, can_manage_vacations) VALUES ('Administration', 1, 1);
        INSERT INTO groups (name, is_admin, can_manage_vacations) VALUES ('Teamleiter', 0, 1);
        """
    )
    conn.commit()
    conn.close()

    main = _fresh_app(tmp_path, monkeypatch, {"DATABASE_URL": f"sqlite:///{db_path}"})
    from fastapi.testclient import TestClient

    with TestClient(main.app):
        pass

    conn = sqlite3.connect(db_path)
    rows = {
        row[0]: row
        for row in conn.execute(
            "SELECT name, can_manage_vacations, can_manage_vacations_scope FROM groups"
        )
    }
    conn.close()
    # Bestandsgruppen behalten ihr Verhalten: Recht galt bisher für ALLE Benutzer.
    assert rows["Teamleiter"][1] == 1
    assert rows["Teamleiter"][2] == "all"
