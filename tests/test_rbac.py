"""Tests für die rollenbasierte Rechteverwaltung (RBAC).

Ersetzt die Suiten zu den früheren Gruppenberechtigungen (0.9.11/0.9.12) und
deckt zusätzlich Rollenverwaltung, Mehrfachmitgliedschaft und die Migration
bestehender Gruppen ab.

Aufbau:

* Unit-Tests des ``PermissionService`` (Rechte, Scopes, Gruppen-Schnittmenge)
* Selbstbedienungsrechte (eigene Buchungen, Kommentare, Urlaub)
* Geltungsbereiche in Freigaben, Berichten und Buchungsbearbeitung
* Rollenverwaltung (Oberfläche, API, Systemrollen, Schutz vor Rechteausweitung)
* Migration einer Alt-Datenbank mit Gruppenberechtigungen
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


def login(client, username: str = "admin", password: str | None = None):
    """Anmelden; für Testbenutzer gilt das Standardkennwort ``Worker!0000``."""
    if password is None:
        password = "Admin!0000" if username == "admin" else "Worker!0000"
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


# --- Hilfsfunktionen -------------------------------------------------------------

def _make_role(name: str, permissions: dict[str, str]) -> int:
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.create_role(db, name=name, permissions=permissions).id
    finally:
        db.close()


def _make_group(name: str) -> int:
    from app import crud, database, schemas

    db = database.SessionLocal()
    try:
        return crud.create_group(db, schemas.GroupCreate(name=name)).id
    finally:
        db.close()


def _make_user(username: str, *, groups=(), roles=(), password="Worker!0000") -> int:
    from app import crud, database, schemas, security

    db = database.SessionLocal()
    try:
        user = crud.create_user(
            db,
            schemas.UserCreate(
                username=username,
                full_name=username.capitalize(),
                email=f"{username}@example.com",
                password=password,
                group_ids=list(groups),
                role_ids=list(roles),
            ),
        )
        user.must_change_password = False
        user.password_hash = security.hash_password(password)
        db.commit()
        return user.id
    finally:
        db.close()


def _user(username: str):
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_user_by_username(db, username)
    finally:
        db.close()


def _pending_entry(user_id: int, day: date):
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        return crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=user_id, company_id=None, work_date=day,
                start_time=time(8, 0), end_time=time(12, 0), break_minutes=0,
                break_started_at=None, is_open=False, notes="",
                status=models.TimeEntryStatus.PENDING, is_manual=True,
            ),
        ).id
    finally:
        db.close()


def _approved_entry(user_id: int, day: date):
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        return crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=user_id, company_id=None, work_date=day,
                start_time=time(8, 0), end_time=time(12, 0), break_minutes=0,
                break_started_at=None, is_open=False, notes="",
                status=models.TimeEntryStatus.APPROVED, is_manual=False,
            ),
        ).id
    finally:
        db.close()


def _punch(client, data: dict):
    payload = {"csrf_token": _csrf(client, "/mobile"), "next_url": "/mobile", **data}
    return client.post(
        "/punch", data=payload, headers={"Accept": "application/json"}, follow_redirects=False
    )


# --- Registry --------------------------------------------------------------------

def test_registry_is_consistent(client):
    from app import permissions

    assert len(permissions.PERMISSION_KEYS) == len(set(permissions.PERMISSION_KEYS))
    assert set(permissions.SELF_SERVICE_KEYS) == {
        "Own.Time.Edit", "Own.Comment.Edit", "Own.Vacation.Request",
        # Seit 0.16.0: Stornieren ist ein eigener Vorgang – wer nachtragen
        # darf, soll nicht automatisch zurücknehmen dürfen.
        "Own.Time.Cancel",
    }
    assert set(permissions.SCOPED_KEYS) == {
        "Time.Approve", "Time.Edit", "Time.View", "Vacation.Manage",
        # Seit 0.14.2: die Urlaubsübersicht ist ein eigenes Recht – wer den
        # Resturlaub eines Teams sieht, entscheidet nicht zwingend über
        # Anträge.
        "Vacation.Overview",
        # Seit 0.19.0: Compliance-Daten zu bearbeiten ist ein eigenes Recht.
        # ``Time.View`` bleibt reines Leserecht.
        "Time.Compliance.Manage",
        "User.View", "User.Create", "User.Edit", "User.Delete",
    }
    assert set(permissions.SUPERADMIN_KEYS) == {
        "System.Roles", "System.Settings", "System.Backup",
    }
    # Gruppen tragen keine Rechte mehr.
    from app import models

    for key in permissions.PERMISSION_KEYS:
        assert not hasattr(models.Group, key)
    assert not hasattr(models.Group, "is_admin")


def test_system_roles_seeded(client):
    from app import crud, database, permissions

    db = database.SessionLocal()
    try:
        admin_role = crud.get_role_by_name(db, permissions.ROLE_ADMINISTRATOR)
        super_role = crud.get_role_by_name(db, permissions.ROLE_SUPERADMINISTRATOR)
        assert admin_role.is_system and super_role.is_system
        assert set(super_role.permission_map) == set(permissions.PERMISSION_KEYS)
        # Administrator: alles außer den Superadministrator-Vorbehalten.
        assert set(admin_role.permission_map) == set(permissions.PERMISSION_KEYS) - set(
            permissions.SUPERADMIN_KEYS
        )
        assert crud.get_user_by_username(db, "admin").role_names == [
            permissions.ROLE_SUPERADMINISTRATOR
        ]
    finally:
        db.close()


# --- PermissionService (Unit) ----------------------------------------------------

def test_scope_widest_wins(client):
    from app import database, permission_service as ps

    group = _make_group("Team A")
    narrow = _make_role("Schmal", {"Time.View": "groups"})
    wide = _make_role("Weit", {"Time.View": "all"})
    _make_user("multi", groups=[group], roles=[narrow, wide])

    db = database.SessionLocal()
    try:
        user = _user("multi")
        assert ps.scope(user, "Time.View") == "all"
        assert ps.allowed_user_ids(db, user, "Time.View") is None
    finally:
        db.close()


def test_scope_groups_uses_intersection(client):
    """Scope ``groups`` gilt für alle Gruppen des Benutzers – auch mehrere."""
    from app import database, permission_service as ps

    nord = _make_group("Nord")
    sued = _make_group("Süd")
    role = _make_role("Sichter", {"Time.View": "groups"})
    lead_id = _make_user("lead", groups=[nord, sued], roles=[role])
    nord_id = _make_user("nordler", groups=[nord])
    sued_id = _make_user("suedler", groups=[sued])
    extern_id = _make_user("extern", groups=[])

    db = database.SessionLocal()
    try:
        lead = _user("lead")
        allowed = ps.allowed_user_ids(db, lead, "Time.View")
        assert allowed == {lead_id, nord_id, sued_id}
        assert ps.can_access_user(db, lead, "Time.View", nord_id)
        assert ps.can_access_user(db, lead, "Time.View", sued_id)
        assert not ps.can_access_user(db, lead, "Time.View", extern_id)
    finally:
        db.close()


def test_scope_self_and_none(client):
    from app import database, permission_service as ps

    role = _make_role("Nur eigene", {"Time.View": "self"})
    own_id = _make_user("selfy", roles=[role])
    other_id = _make_user("other")

    db = database.SessionLocal()
    try:
        user = _user("selfy")
        assert ps.allowed_user_ids(db, user, "Time.View") == {own_id}
        assert not ps.can_access_user(db, user, "Time.View", other_id)
        # Nicht vergebenes Recht
        assert ps.scope(user, "Time.Edit") == "none"
        assert ps.has(user, "Time.Edit") is False
        assert ps.allowed_user_ids(db, user, "Time.Edit") == set()
    finally:
        db.close()


def test_inactive_role_grants_nothing(client):
    from app import crud, database, permission_service as ps

    role_id = _make_role("Pausiert", {"Time.View": "all"})
    _make_user("paused", roles=[role_id])
    db = database.SessionLocal()
    try:
        crud.update_role(db, role_id, is_active=False)
    finally:
        db.close()
    assert ps.has(_user("paused"), "Time.View") is False


def test_self_service_default_without_role(client):
    """Ohne Rolle bleiben die eigenen Rechte erhalten (Bestandsverhalten)."""
    from app import permission_service as ps

    _make_user("plain")
    user = _user("plain")
    for key in ("Own.Time.Edit", "Own.Comment.Edit", "Own.Vacation.Request"):
        assert ps.has(user, key), key
    assert ps.has(user, "Time.View") is False
    assert ps.has_admin_access(user) is False


def test_anonymous_has_nothing(client):
    from app import database, permission_service as ps

    db = database.SessionLocal()
    try:
        assert ps.has(None, "Time.View") is False
        assert ps.scope(None, "Own.Time.Edit") == "none"
        assert ps.allowed_user_ids(db, None, "Time.View") == set()
        assert ps.has_admin_access(None) is False
    finally:
        db.close()


# --- Selbstbedienungsrechte -------------------------------------------------------

def test_update_notes_denied_without_permission(client):
    role = _make_role("Ohne Kommentar", {"Own.Time.Edit": "self", "Own.Vacation.Request": "self"})
    _make_user("worker1", roles=[role])
    login(client, "worker1")
    assert _punch(client, {"action": "start_work"}).json()["ok"]
    assert _punch(client, {"action": "end_work"}).json()["ok"]
    body = _punch(client, {"action": "update_notes", "notes": "verboten"}).json()
    assert body["ok"] is False and body["retryable"] is False
    html = client.get("/mobile").text
    assert 'id="mobile-notes-modal"' not in html
    assert 'id="mobile-notes-launch"' not in html


def test_update_notes_allowed_without_any_role(client):
    _make_user("worker2")
    login(client, "worker2")
    assert _punch(client, {"action": "start_work"}).json()["ok"]
    assert _punch(client, {"action": "end_work"}).json()["ok"]
    assert _punch(client, {"action": "update_notes", "notes": "erlaubt"}).json()["ok"] is True


def test_manual_time_entry_denied_without_permission(client):
    role = _make_role("Ohne Nachtrag", {"Own.Comment.Edit": "self"})
    _make_user("worker3", roles=[role])
    login(client, "worker3")
    response = client.post(
        "/time",
        data={
            "csrf_token": _csrf(client, "/dashboard"),
            "work_date": "2026-07-01", "start_time": "08:00", "end_time": "10:00",
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "manuellen" in response.headers["location"]


def test_vacation_request_denied_without_permission(client):
    role = _make_role("Ohne Urlaub", {"Own.Time.Edit": "self"})
    _make_user("worker4", roles=[role])
    login(client, "worker4")
    response = client.post(
        "/vacations",
        data={
            "csrf_token": _csrf(client, "/dashboard"),
            "start_date": "2026-08-01", "end_date": "2026-08-05",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.json()["ok"] is False
    assert "darf keine Urlaubsanträge stellen" in client.get("/records/vacations").text


def test_sync_data_contains_permissions(client):
    role = _make_role("Sync", {"Own.Time.Edit": "self"})
    _make_user("worker7", roles=[role])
    login(client, "worker7")
    perms = client.get("/mobile/sync-data?days=7").json()["permissions"]
    assert perms["manual_time_entries"] is True
    assert perms["edit_own_notes"] is False
    assert perms["request_vacations"] is False
    assert perms["create_companies"] is False


# --- Firmenverwaltung delegieren ---------------------------------------------------

def test_company_admin_delegable(client):
    role = _make_role("Firmenpfleger", {"Company.Manage": "all"})
    _make_user("worker5", roles=[role])
    login(client, "worker5")
    assert client.get("/admin/companies", follow_redirects=False).status_code == 200
    response = client.post(
        "/admin/companies/create",
        data={"csrf_token": _csrf(client, "/admin/companies/new"),
              "name": "Delegiert GmbH", "description": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303 and "msg=" in response.headers["location"]


def test_company_admin_denied_without_permission(client):
    _make_user("worker6")
    login(client, "worker6")
    response = client.get("/admin/companies", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].endswith("/dashboard")


# --- Geltungsbereiche in der Oberfläche ---------------------------------------------

@pytest.fixture()
def team(client):
    """Teamleitung mit Gruppen-Scope, ein Teammitglied und ein Externer."""
    nord = _make_group("Nord")
    extern_group = _make_group("Extern")
    lead_role = _make_role(
        "Teamleiter",
        {
            "Own.Time.Edit": "self", "Own.Comment.Edit": "self", "Own.Vacation.Request": "self",
            "Time.View": "groups", "Time.Edit": "groups", "Time.Approve": "groups",
            "Vacation.Manage": "groups", "User.View": "groups", "User.Edit": "groups",
        },
    )
    lead_id = _make_user("lead", groups=[nord], roles=[lead_role])
    member_id = _make_user("member", groups=[nord])
    extern_id = _make_user("extern", groups=[extern_group])
    login(client, "lead")
    return {
        "lead": lead_id, "member": member_id, "extern": extern_id,
        "nord": nord, "extern_group": extern_group, "lead_role": lead_role,
    }


def test_approvals_filtered_to_groups(client, team):
    day = date(2026, 9, 1)
    _pending_entry(team["member"], day)
    _pending_entry(team["extern"], day)
    html = client.get("/admin/approvals").text
    assert "Member" in html
    assert "Extern" not in html


def test_reports_filtered_to_groups(client, team):
    day = date(2026, 9, 2)
    _approved_entry(team["member"], day)
    _approved_entry(team["extern"], day)
    html = client.get("/admin/reports/time?view=month&month=2026-09").text
    assert "Member" in html
    assert "Extern" not in html


def test_user_list_limited_to_groups(client, team):
    html = client.get("/admin/users").text
    assert "member" in html
    assert "extern@example.com" not in html


def test_edit_foreign_entry_denied(client, team):
    day = date(2026, 9, 3)
    own = _pending_entry(team["member"], day)
    foreign = _pending_entry(team["extern"], day)
    assert client.get(f"/admin/time-entries/{own}/edit", follow_redirects=False).status_code == 200
    denied = client.get(f"/admin/time-entries/{foreign}/edit", follow_redirects=False)
    assert denied.status_code == 303


def test_admin_link_and_landing_page(client, team):
    assert "/admin" in client.get("/dashboard").text
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users"


def test_admin_area_hidden_without_permissions(client):
    _make_user("plain2")
    login(client, "plain2")
    assert 'href="/admin"' not in client.get("/dashboard").text
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].endswith("/dashboard")


def test_team_lead_cannot_assign_roles(client, team):
    """Ohne ``System.Roles`` bietet das Formular keine Rollen an und der Server
    lehnt eine Zuweisung ab (Schutz vor Rechteausweitung)."""
    from app import crud, database

    html = client.get(f"/admin/users/{team['member']}").text
    assert 'name="role_ids"' not in html

    db = database.SessionLocal()
    try:
        super_role = crud.get_role_by_name(db, "Superadministrator").id
    finally:
        db.close()
    response = client.post(
        f"/admin/users/{team['member']}/update",
        data={
            "csrf_token": _csrf(client, f"/admin/users/{team['member']}"),
            "username": "member", "full_name": "Member", "email": "member@example.com",
            "standard_weekly_hours": "40", "annual_vacation_days": "30",
            "group_ids": [str(team["nord"])], "role_ids": [str(super_role)],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Rolle+darf+nicht" in response.headers["location"]
    assert _user("member").role_names == []


def test_team_lead_cannot_assign_foreign_group(client, team):
    response = client.post(
        f"/admin/users/{team['member']}/update",
        data={
            "csrf_token": _csrf(client, f"/admin/users/{team['member']}"),
            "username": "member", "full_name": "Member", "email": "member@example.com",
            "standard_weekly_hours": "40", "annual_vacation_days": "30",
            "group_ids": [str(team["extern_group"])],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Gruppe+darf+nicht" in response.headers["location"]


# --- Rollenverwaltung ---------------------------------------------------------------

def test_role_crud_via_ui(client):
    login(client)
    response = client.post(
        "/admin/roles/create",
        data={
            "csrf_token": _csrf(client, "/admin/roles/new"),
            "name": "Auswerter", "description": "Nur Berichte", "is_active": "on",
            "scope__Time.View": "groups",
            "perm__Company.Create": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    from app import crud, database

    db = database.SessionLocal()
    try:
        role = crud.get_role_by_name(db, "Auswerter")
        assert role.permission_map == {"Time.View": "groups", "Company.Create": "all"}
        role_id = role.id
    finally:
        db.close()

    assert "Auswerter" in client.get("/admin/roles").text

    client.post(
        f"/admin/roles/{role_id}/update",
        data={
            "csrf_token": _csrf(client, f"/admin/roles/{role_id}"),
            "name": "Auswerter", "description": "", "is_active": "on",
            "scope__Time.View": "all",
        },
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        assert crud.get_role(db, role_id).permission_map == {"Time.View": "all"}
    finally:
        db.close()

    client.post(
        f"/admin/roles/{role_id}/delete",
        data={"csrf_token": _csrf(client, f"/admin/roles/{role_id}")},
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        assert crud.get_role(db, role_id) is None
    finally:
        db.close()


def test_system_role_is_immutable(client):
    from app import crud, database

    login(client)
    db = database.SessionLocal()
    try:
        role = crud.get_role_by_name(db, "Administrator")
        role_id = role.id
        before = dict(role.permission_map)
    finally:
        db.close()

    html = client.get(f"/admin/roles/{role_id}").text
    assert "Systemrolle" in html

    response = client.post(
        f"/admin/roles/{role_id}/update",
        data={"csrf_token": _csrf(client, f"/admin/roles/{role_id}"),
              "name": "Gekapert", "is_active": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303 and "nicht" in response.headers["location"]

    db = database.SessionLocal()
    try:
        role = crud.get_role(db, role_id)
        assert role.name == "Administrator" and role.permission_map == before
        assert crud.delete_role(db, role_id) is False
    finally:
        db.close()


def test_administrator_role_lacks_superadmin_areas(client):
    """Die Systemrolle „Administrator“ kommt ohne Rollen-, System- und
    Sicherungsverwaltung aus – das bleibt dem Superadministrator vorbehalten."""
    from app import crud, database

    db = database.SessionLocal()
    try:
        admin_role = crud.get_role_by_name(db, "Administrator").id
    finally:
        db.close()
    _make_user("chef", roles=[admin_role], password="Chef!000000")
    login(client, "chef", "Chef!000000")

    assert client.get("/admin/users", follow_redirects=False).status_code == 200
    for url in ("/admin/roles", "/admin/system/status", "/admin/system/backups"):
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 303, url


def test_role_manager_cannot_grant_superadmin_permissions(client):
    """Wer Rollen verwalten darf, aber kein Superadministrator ist, kann die
    Vorbehalte nicht über eine selbst angelegte Rolle weitergeben."""
    from app import crud, database

    manager_role = _make_role(
        "Rollenpfleger", {"System.Roles": "all", "User.View": "all"}
    )
    _make_user("chef", roles=[manager_role], password="Chef!000000")
    login(client, "chef", "Chef!000000")

    response = client.post(
        "/admin/roles/create",
        data={
            "csrf_token": _csrf(client, "/admin/roles/new"),
            "name": "Hintertür", "is_active": "on",
            "perm__System.Roles": "on", "perm__System.Backup": "on",
            "perm__Company.Create": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    db = database.SessionLocal()
    try:
        role = crud.get_role_by_name(db, "Hintertür")
        assert role.permission_map == {"Company.Create": "all"}
    finally:
        db.close()


def test_permissions_overview_lists_every_key(client):
    from app import permissions

    login(client)
    html = client.get("/admin/permissions").text
    for key in permissions.PERMISSION_KEYS:
        assert key in html


def test_roles_api(client):
    login(client)
    assert client.get("/api/roles").status_code == 200
    created = client.post(
        "/api/roles",
        json={"name": "API-Rolle", "description": "", "permissions": {"Time.View": "groups"}},
        headers={"x-csrf-token": client.get("/api/csrf").json()["csrf_token"]},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["name"] == "API-Rolle"
    assert payload["permissions"] == [{"permission_key": "Time.View", "scope": "groups"}]


def test_roles_api_requires_permission(client):
    _make_user("nobody")
    login(client, "nobody")
    assert client.get("/api/roles").status_code == 403


# --- Gruppen sind reine Organisation -------------------------------------------------

def test_group_form_has_no_permissions(client):
    login(client)
    html = client.get("/admin/groups/new").text
    assert 'name="member_ids"' in html
    assert 'name="is_admin"' not in html
    assert "Berechtigung" not in html.split("<form")[1].split("</form>")[0]


def test_group_membership_is_many_to_many(client):
    login(client)
    first = _make_group("Alpha")
    second = _make_group("Beta")
    user_id = _make_user("multi2", groups=[first, second])
    assert sorted(_user("multi2").group_names) == ["Alpha", "Beta"]

    # Mitglieder über den Gruppeneditor setzen
    response = client.post(
        f"/admin/groups/{first}/update",
        data={"csrf_token": _csrf(client, f"/admin/groups/{first}"),
              "name": "Alpha", "description": "Team Alpha", "member_ids": []},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert _user("multi2").group_names == ["Beta"]
    assert user_id  # Benutzer bleibt bestehen


def test_group_api_ignores_legacy_permission_fields(client):
    """Alte API-Aufrufe mit Rechte-Feldern funktionieren weiter."""
    login(client)
    response = client.post(
        "/api/groups",
        json={"name": "Legacy", "is_admin": True, "can_manage_users": True},
        headers={"x-csrf-token": client.get("/api/csrf").json()["csrf_token"]},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Legacy"
    assert "is_admin" not in response.json()


# --- Migration einer Alt-Datenbank ------------------------------------------------

def test_migration_converts_groups_to_roles(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE groups (
            id INTEGER PRIMARY KEY, name VARCHAR(255) UNIQUE NOT NULL,
            is_admin BOOLEAN DEFAULT 0,
            can_manage_users BOOLEAN DEFAULT 0, can_manage_vacations BOOLEAN DEFAULT 0,
            can_approve_manual_entries BOOLEAN DEFAULT 0, can_create_companies BOOLEAN DEFAULT 0,
            can_view_time_reports BOOLEAN DEFAULT 0, can_edit_time_entries BOOLEAN DEFAULT 0,
            can_manage_companies BOOLEAN DEFAULT 0,
            can_manual_time_entries BOOLEAN DEFAULT 1, can_edit_own_notes BOOLEAN DEFAULT 1,
            can_request_vacations BOOLEAN DEFAULT 1,
            can_manage_vacations_scope VARCHAR(10) DEFAULT 'all',
            can_approve_manual_entries_scope VARCHAR(10) DEFAULT 'all',
            can_view_time_reports_scope VARCHAR(10) DEFAULT 'all',
            can_edit_time_entries_scope VARCHAR(10) DEFAULT 'all',
            can_manage_users_scope VARCHAR(10) DEFAULT 'all'
        );
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, username VARCHAR(255) UNIQUE NOT NULL,
            full_name VARCHAR(255) NOT NULL, email VARCHAR(255) UNIQUE NOT NULL,
            standard_daily_minutes INTEGER DEFAULT 480, standard_weekly_hours FLOAT DEFAULT 40,
            pin_code VARCHAR(4) UNIQUE NOT NULL, password_hash VARCHAR(255),
            must_change_password BOOLEAN DEFAULT 0, group_id INTEGER,
            time_account_enabled BOOLEAN DEFAULT 0, overtime_vacation_enabled BOOLEAN DEFAULT 0,
            annual_vacation_days INTEGER DEFAULT 30, vacation_carryover_enabled BOOLEAN DEFAULT 0,
            vacation_carryover_days INTEGER DEFAULT 0, rfid_tag VARCHAR(255),
            monthly_overtime_limit_minutes INTEGER, auto_break_deduction BOOLEAN DEFAULT 1
        );
        INSERT INTO groups (id, name, is_admin) VALUES (1, 'Administration', 1);
        INSERT INTO groups (id, name, can_view_time_reports, can_view_time_reports_scope,
                            can_edit_time_entries, can_edit_time_entries_scope,
                            can_edit_own_notes)
            VALUES (2, 'Pflege Nord', 1, 'group', 1, 'group', 0);
        INSERT INTO users (id, username, full_name, email, pin_code, group_id) VALUES
            (1, 'admin', 'Administrator', 'a@example.com', '0001', 1),
            (2, 'lead', 'Teamleitung', 'l@example.com', '0002', 2),
            (3, 'worker', 'Mitarbeiter', 'w@example.com', '0003', 2);
        """
    )
    conn.commit()
    conn.close()

    main = _fresh_app(tmp_path, monkeypatch, {"DATABASE_URL": f"sqlite:///{db_path}"})
    from fastapi.testclient import TestClient

    with TestClient(main.app):
        from app import crud, database, permission_service as ps

        db = database.SessionLocal()
        try:
            admin = crud.get_user_by_username(db, "admin")
            lead = crud.get_user_by_username(db, "lead")
            worker = crud.get_user_by_username(db, "worker")

            # Administratorgruppe → Superadministrator (verliert nichts)
            assert admin.role_names == ["Superadministrator"]
            assert ps.is_superadmin(admin)

            # Gruppe mit Rechten → Migrationsrolle mit gleichem Umfang
            assert lead.role_names == ["Migration – Pflege Nord"]
            role = crud.get_role_by_name(db, "Migration – Pflege Nord")
            assert role.permission_map["Time.View"] == "groups"
            assert role.permission_map["Time.Edit"] == "groups"
            # Entzogenes Selbstbedienungsrecht bleibt entzogen
            assert "Own.Comment.Edit" not in role.permission_map
            assert role.permission_map["Own.Time.Edit"] == "self"

            # Zugehörigkeit wandert nach user_groups
            assert lead.group_names == ["Pflege Nord"]
            assert worker.group_names == ["Pflege Nord"]

            # Scope wirkt jetzt über die Gruppen-Schnittmenge
            assert ps.allowed_user_ids(db, lead, "Time.View") == {lead.id, worker.id}

            # Gruppen tragen keine Rechte mehr
            from sqlalchemy import text

            row = db.execute(
                text("SELECT is_admin, can_view_time_reports FROM groups WHERE id = 1")
            ).first()
            assert tuple(row) == (0, 0)
        finally:
            db.close()


def test_migration_is_idempotent(client):
    """Ein zweiter Lauf legt keine doppelten Rollen oder Zuordnungen an."""
    from app import crud, database, db_migrations

    db_migrations._migrate_groups_to_roles(database.engine)
    db_migrations._migrate_groups_to_roles(database.engine)

    db = database.SessionLocal()
    try:
        names = [role.name for role in crud.get_roles(db)]
        assert len(names) == len(set(names))
        admin = crud.get_user_by_username(db, "admin")
        assert admin.role_names.count("Superadministrator") <= 1
    finally:
        db.close()
