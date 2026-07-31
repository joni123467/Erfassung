"""Regression tests for 0.9.10 – mobile clock-in after company search and
optional comment editing after finishing an order / work time.

Covers: version bump, the ``start_company`` fallback that resolves the free-text
company search (``company_name``) when no dropdown value was submitted, the new
``update_notes`` punch action (by ``entry_id`` and via the last finished entry),
its ownership check, the mobile dashboard notes modal/button, and the frontend
auto-select of exact search matches in ``static/mobile.js``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

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


def _create_company(name: str = "ACME GmbH"):
    from app import crud, database, schemas

    db = database.SessionLocal()
    try:
        company = crud.create_company(db, schemas.CompanyCreate(name=name, description=""))
        return company.id
    finally:
        db.close()


def _punch(client, data: dict, json_mode: bool = False):
    payload = {"csrf_token": _csrf(client, "/mobile"), "next_url": "/mobile", **data}
    headers = {"Accept": "application/json"} if json_mode else {}
    return client.post("/punch", data=payload, headers=headers, follow_redirects=False)


def _open_entry(user_id: int):
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_open_time_entry(db, user_id)
    finally:
        db.close()


def _admin_id(client) -> int:
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_user_by_username(db, "admin").id
    finally:
        db.close()


# --- version -----------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.13.0"
    assert client.get("/health").json()["version"] == "0.13.0"


# --- start_company: company_name fallback (mobile search fix) -----------------

def test_start_company_resolves_search_text_without_company_id(client):
    login(client)
    company_id = _create_company("ACME GmbH")
    response = _punch(client, {"action": "start_company", "company_name": "ACME GmbH"}, json_mode=True)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True, body
    entry = _open_entry(_admin_id(client))
    assert entry is not None and entry.company_id == company_id


def test_start_company_search_text_is_case_insensitive(client):
    login(client)
    company_id = _create_company("ACME GmbH")
    response = _punch(client, {"action": "start_company", "company_name": "acme gmbh"}, json_mode=True)
    assert response.json()["ok"] is True
    entry = _open_entry(_admin_id(client))
    assert entry is not None and entry.company_id == company_id


def test_start_company_unknown_search_text_is_rejected(client):
    login(client)
    _create_company("ACME GmbH")
    response = _punch(client, {"action": "start_company", "company_name": "Gibt Es Nicht"}, json_mode=True)
    body = response.json()
    assert body["ok"] is False and body["retryable"] is False
    assert _open_entry(_admin_id(client)) is None


def test_start_company_without_any_company_is_still_rejected(client):
    login(client)
    response = _punch(client, {"action": "start_company"}, json_mode=True)
    assert response.json()["ok"] is False
    assert _open_entry(_admin_id(client)) is None


def test_start_company_by_id_still_works(client):
    login(client)
    company_id = _create_company("ACME GmbH")
    response = _punch(client, {"action": "start_company", "company_id": str(company_id)}, json_mode=True)
    assert response.json()["ok"] is True
    entry = _open_entry(_admin_id(client))
    assert entry is not None and entry.company_id == company_id


def test_start_company_new_company_still_works(client):
    login(client)
    response = _punch(client, {"action": "start_company", "new_company_name": "Neue Firma"}, json_mode=True)
    assert response.json()["ok"] is True
    entry = _open_entry(_admin_id(client))
    assert entry is not None and entry.company_id is not None


# --- update_notes: edit comment after finishing ------------------------------

def _last_finished(user_id: int):
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_last_finished_time_entry(db, user_id)
    finally:
        db.close()


def test_update_notes_on_last_finished_entry(client):
    login(client)
    _create_company("ACME GmbH")
    assert _punch(client, {"action": "start_company", "company_name": "ACME GmbH", "notes": "Anfahrt"}, json_mode=True).json()["ok"]
    assert _punch(client, {"action": "end_work"}, json_mode=True).json()["ok"]
    response = _punch(client, {"action": "update_notes", "notes": "Anfahrt + Montage"}, json_mode=True)
    assert response.json()["ok"] is True
    entry = _last_finished(_admin_id(client))
    assert entry is not None and entry.notes == "Anfahrt + Montage"


def test_update_notes_with_entry_id(client):
    login(client)
    assert _punch(client, {"action": "start_work"}, json_mode=True).json()["ok"]
    assert _punch(client, {"action": "end_work"}, json_mode=True).json()["ok"]
    entry = _last_finished(_admin_id(client))
    response = _punch(
        client,
        {"action": "update_notes", "entry_id": str(entry.id), "notes": "Nachtrag"},
        json_mode=True,
    )
    assert response.json()["ok"] is True
    assert _last_finished(_admin_id(client)).notes == "Nachtrag"


def test_update_notes_rejects_foreign_entry(client):
    from app import crud, database, schemas, security

    login(client)
    assert _punch(client, {"action": "start_work"}, json_mode=True).json()["ok"]
    assert _punch(client, {"action": "end_work"}, json_mode=True).json()["ok"]
    own_entry = _last_finished(_admin_id(client))

    db = database.SessionLocal()
    try:
        other = crud.create_user(
            db,
            schemas.UserCreate(
                username="worker",
                full_name="Worker",
                email="worker@example.com",
                password="Worker!0000",
            ),
        )
        from datetime import date, time

        foreign = crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=other.id,
                company_id=None,
                work_date=date(2020, 1, 2),
                start_time=time(8, 0),
                end_time=time(9, 0),
                break_minutes=0,
                break_started_at=None,
                is_open=False,
                notes="fremd",
                status="approved",
                is_manual=True,
            ),
        )
        foreign_id = foreign.id
    finally:
        db.close()

    # A foreign entry_id must not be editable: the fallback targets the caller's
    # own last finished entry instead.
    response = _punch(
        client,
        {"action": "update_notes", "entry_id": str(foreign_id), "notes": "gekapert"},
        json_mode=True,
    )
    assert response.json()["ok"] is True
    db = database.SessionLocal()
    try:
        assert crud.get_time_entry(db, foreign_id).notes == "fremd"
        assert crud.get_time_entry(db, own_entry.id).notes == "gekapert"
    finally:
        db.close()


def test_update_notes_without_any_finished_entry(client):
    login(client)
    response = _punch(client, {"action": "update_notes", "notes": "x"}, json_mode=True)
    body = response.json()
    assert body["ok"] is False and body["retryable"] is False


def test_update_notes_is_idempotent_via_client_action_id(client):
    login(client)
    assert _punch(client, {"action": "start_work"}, json_mode=True).json()["ok"]
    assert _punch(client, {"action": "end_work"}, json_mode=True).json()["ok"]
    data = {"action": "update_notes", "notes": "einmal", "client_action_id": "punch-test-notes-1"}
    first = _punch(client, data, json_mode=True).json()
    assert first["ok"] is True and first["duplicate"] is False
    second = _punch(client, data, json_mode=True).json()
    assert second["ok"] is True and second["duplicate"] is True


# --- mobile dashboard UI -----------------------------------------------------

def test_mobile_dashboard_contains_notes_modal_and_button(client):
    login(client)
    html = client.get("/mobile").text
    assert 'id="mobile-notes-modal"' in html
    assert 'id="mobile-notes-launch"' in html
    assert 'value="update_notes"' in html
    # Without a finished entry today the launch button stays hidden.
    assert re.search(r'id="mobile-notes-launch"[^>]*hidden', html, re.S)

    assert _punch(client, {"action": "start_work"}, json_mode=True).json()["ok"]
    assert _punch(client, {"action": "end_work"}, json_mode=True).json()["ok"]
    html = client.get("/mobile").text
    assert not re.search(r'id="mobile-notes-launch"[^>]*hidden', html, re.S)


def test_offline_shell_contains_notes_modal(client):
    shell = Path("static/mobile-offline-shell.html").read_text(encoding="utf-8")
    assert 'id="mobile-notes-modal"' in shell
    assert 'value="update_notes"' in shell


def test_mobile_js_auto_selects_exact_search_match(client):
    js = Path("static/mobile.js").read_text(encoding="utf-8")
    assert "exactMatchValue" in js, "company search must auto-select exact matches"
    assert "resolveCompanyIdByName" in js
    assert "update_notes" in js
    # datalist suggestions are refilled from the offline cache
    assert "HTMLDataListElement" in js
