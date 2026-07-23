"""Regression tests for 0.9.11 – reworked group permissions.

Covers: version bump, the central permission registry, the categorized group
form + overview, dynamic form parsing (create/update incl. admin implies all),
the new self-service permissions (manual entries, own-notes editing, vacation
requests) and their server-side enforcement, the delegable company management
permission, the sync-data permission payload, and the schema migration for
existing databases.
"""

from __future__ import annotations

import re
import sys

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
    """Create a group directly in the DB and return its id."""
    from app import crud, database, schemas

    db = database.SessionLocal()
    try:
        payload = {"name": overrides.pop("name", "Testgruppe")}
        payload.update(overrides)
        group = crud.create_group(db, schemas.GroupCreate(**payload))
        return group.id
    finally:
        db.close()


def _create_member(group_id, username: str = "worker"):
    from app import crud, database, schemas, security

    db = database.SessionLocal()
    try:
        user = crud.create_user(
            db,
            schemas.UserCreate(
                username=username,
                full_name="Worker",
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


def _get_group(group_id):
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_group(db, group_id)
    finally:
        db.close()


# --- version -----------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.9.15"
    assert client.get("/health").json()["version"] == "0.9.15"


# --- permission registry ------------------------------------------------------

def test_registry_matches_group_model(client):
    from app import models, permissions

    for key in permissions.PERMISSION_KEYS:
        assert hasattr(models.Group, key), f"Group model missing column for {key}"
    # Self-service permissions default to allowed, management ones to denied.
    assert set(permissions.SELF_SERVICE_KEYS) == {
        "can_manual_time_entries", "can_edit_own_notes", "can_request_vacations",
    }
    for permission in permissions.ALL_PERMISSIONS:
        assert permission.default is permission.self_service


def test_group_form_shows_categorized_matrix(client):
    from markupsafe import escape

    login(client)
    html = client.get("/admin/groups/new").text
    from app import permissions

    for category in permissions.CATEGORIES:
        assert str(escape(category.label)) in html
        for permission in category.permissions:
            if permission.scoped:
                # Team-Rechte werden seit 0.9.12 als Bereichsauswahl gerendert.
                assert f'name="{permission.scope_key}"' in html
            else:
                assert f'name="{permission.key}"' in html
            assert str(escape(permission.label)) in html
    assert "Administratorrechte" in html


def test_group_create_via_form_and_overview_badges(client):
    login(client)
    token = _csrf(client, "/admin/groups/new")
    response = client.post(
        "/admin/groups/create",
        data={
            "csrf_token": token,
            "name": "Teamleitung",
            "can_view_time_reports_scope": "all",
            "can_manage_vacations_scope": "all",
            "can_edit_own_notes": "on",
            "can_manual_time_entries": "on",
            "can_request_vacations": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    from app import crud, database

    db = database.SessionLocal()
    try:
        group = next(g for g in crud.get_groups(db) if g.name == "Teamleitung")
        assert group.can_view_time_reports and group.can_manage_vacations
        assert group.can_edit_own_notes and group.can_request_vacations
        assert not group.can_manage_users
        # Unchecked self-service boxes are stored as denied.
        assert not group.can_create_companies
    finally:
        db.close()

    html = client.get("/admin/groups").text
    assert "Team &amp; Freigaben: 2/4" in html or "Team & Freigaben: 2/4" in html


def test_group_update_admin_grants_everything(client):
    from app import permissions

    login(client)
    group_id = _create_group(name="Aufsteiger")
    token = _csrf(client, f"/admin/groups/{group_id}")
    client.post(
        f"/admin/groups/{group_id}/update",
        data={"csrf_token": token, "name": "Aufsteiger", "is_admin": "on"},
        follow_redirects=False,
    )
    group = _get_group(group_id)
    assert group.is_admin
    for key in permissions.PERMISSION_KEYS:
        assert getattr(group, key) is True, key


# --- self-service permission enforcement --------------------------------------

def _punch(client, data: dict):
    payload = {"csrf_token": _csrf(client, "/mobile"), "next_url": "/mobile", **data}
    return client.post("/punch", data=payload, headers={"Accept": "application/json"}, follow_redirects=False)


def test_update_notes_denied_without_permission(client):
    group_id = _create_group(name="Ohne Kommentar", can_edit_own_notes=False)
    _create_member(group_id, "worker1")
    login(client, "worker1", "Worker!0000")
    assert _punch(client, {"action": "start_work"}).json()["ok"]
    assert _punch(client, {"action": "end_work"}).json()["ok"]
    body = _punch(client, {"action": "update_notes", "notes": "verboten"}).json()
    assert body["ok"] is False and body["retryable"] is False
    assert "nachträglich" in body["message"]
    # UI: weder Dialog noch Button werden gerendert
    html = client.get("/mobile").text
    assert 'id="mobile-notes-modal"' not in html
    assert 'id="mobile-notes-launch"' not in html


def test_update_notes_allowed_by_default_group(client):
    group_id = _create_group(name="Standardgruppe")
    _create_member(group_id, "worker2")
    login(client, "worker2", "Worker!0000")
    assert _punch(client, {"action": "start_work"}).json()["ok"]
    assert _punch(client, {"action": "end_work"}).json()["ok"]
    assert _punch(client, {"action": "update_notes", "notes": "erlaubt"}).json()["ok"] is True


def test_manual_time_entry_denied_without_permission(client):
    group_id = _create_group(name="Ohne Nachtrag", can_manual_time_entries=False)
    _create_member(group_id, "worker3")
    login(client, "worker3", "Worker!0000")
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/time",
        data={
            "csrf_token": token,
            "work_date": "2026-07-01",
            "start_time": "08:00",
            "end_time": "10:00",
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "manuellen" in response.headers["location"]
    html = client.get("/dashboard").text
    assert "Deine Gruppe darf keine manuellen Zeitbuchungen nachtragen." in html


def test_vacation_request_denied_without_permission(client):
    group_id = _create_group(name="Ohne Urlaub", can_request_vacations=False)
    _create_member(group_id, "worker4")
    login(client, "worker4", "Worker!0000")
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/vacations",
        data={
            "csrf_token": token,
            "start_date": "2026-08-01",
            "end_date": "2026-08-05",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    body = response.json()
    assert body["ok"] is False
    html = client.get("/records/vacations").text
    assert "darf keine Urlaubsanträge stellen" in html


# --- company management delegation ---------------------------------------------

def test_company_admin_delegable(client):
    group_id = _create_group(name="Firmenpfleger", can_manage_companies=True)
    _create_member(group_id, "worker5")
    login(client, "worker5", "Worker!0000")
    assert client.get("/admin/companies", follow_redirects=False).status_code == 200
    token = _csrf(client, "/admin/companies/new")
    response = client.post(
        "/admin/companies/create",
        data={"csrf_token": token, "name": "Delegiert GmbH", "description": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303 and "msg=" in response.headers["location"]


def test_company_admin_denied_without_permission(client):
    group_id = _create_group(name="Nur Mitarbeiter")
    _create_member(group_id, "worker6")
    login(client, "worker6", "Worker!0000")
    response = client.get("/admin/companies", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/dashboard")


# --- sync payload ---------------------------------------------------------------

def test_sync_data_contains_permissions(client):
    group_id = _create_group(
        name="Sync", can_edit_own_notes=False, can_request_vacations=False,
    )
    _create_member(group_id, "worker7")
    login(client, "worker7", "Worker!0000")
    payload = client.get("/mobile/sync-data?days=7").json()
    perms = payload["permissions"]
    assert perms["edit_own_notes"] is False
    assert perms["request_vacations"] is False
    assert perms["manual_time_entries"] is True
    assert perms["create_companies"] is False


# --- migration of existing databases --------------------------------------------

def test_migration_adds_permission_columns(tmp_path, monkeypatch):
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
            can_manage_vacations BOOLEAN DEFAULT 0,
            can_approve_manual_entries BOOLEAN DEFAULT 0,
            can_create_companies BOOLEAN DEFAULT 0,
            can_view_time_reports BOOLEAN DEFAULT 0,
            can_edit_time_entries BOOLEAN DEFAULT 0
        );
        INSERT INTO groups (name, is_admin) VALUES ('Administration', 1);
        INSERT INTO groups (name, is_admin) VALUES ('Mitarbeiter', 0);
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
            "SELECT name, can_manage_companies, can_manual_time_entries, "
            "can_edit_own_notes, can_request_vacations FROM groups"
        )
    }
    conn.close()
    # Admin group gets company management; startup grant sets everything to 1.
    assert rows["Administration"][1] == 1
    # Existing non-admin groups keep their behaviour: self-service allowed,
    # company management denied.
    assert rows["Mitarbeiter"][1] == 0
    assert rows["Mitarbeiter"][2] == 1
    assert rows["Mitarbeiter"][3] == 1
    assert rows["Mitarbeiter"][4] == 1
