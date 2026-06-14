"""Regression tests for 0.9.8 – Terminalverwaltung, TimeMoto-Migration,
Datenbank-Konfiguration & Dokumentationspflege.

Covers: version bump, the generic terminal management area (list/create/edit/
toggle/delete + driver registry), the ``terminal`` log channel and its setting,
the database-config field/port behaviour, the terminal status on the system
status page, and the legacy ``timemoto.json`` → terminals migration.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")

    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]

    from fastapi.testclient import TestClient
    import app.main as main

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
        test_client.tmp_path = tmp_path  # type: ignore[attr-defined]
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


# --- version ---------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.9.8"
    assert client.get("/health").json()["version"] == "0.9.8"


# --- navigation: TimeMoto removed, Terminals added -------------------------

def test_nav_has_terminals_not_timemoto(client):
    login(client)
    html = client.get("/admin/system/status").text
    assert 'href="/admin/terminals"' in html
    assert ">Terminals<" in html
    assert 'href="/admin/integrations/timemoto"' not in html
    assert ">Zeiterfassung<" in html


def test_timemoto_url_redirects(client):
    login(client)
    resp = client.get("/admin/integrations/timemoto", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/admin/terminals"


# --- terminal management page ----------------------------------------------

def test_terminals_page_renders(client):
    login(client)
    resp = client.get("/admin/terminals")
    assert resp.status_code == 200
    html = resp.text
    assert "Neues Terminal" in html
    assert 'id="terminal-modal"' in html
    assert "/admin/terminals/test" in html
    # Driver dropdown offers TimeMoto.
    assert ">TimeMoto<" in html
    # Required table columns.
    for column in ("Name", "Typ", "Status", "Letzte Verbindung", "Letzte Synchronisation", "Aktionen"):
        assert column in html


def test_driver_registry():
    from app.integrations import terminals

    assert terminals.is_known_type("timemoto")
    keys = {t["key"] for t in terminals.available_types()}
    assert "timemoto" in keys
    driver = terminals.get_driver("timemoto")
    assert driver is not None and driver.label == "TimeMoto"


# --- terminal CRUD lifecycle -----------------------------------------------

def test_terminal_crud_lifecycle(client):
    from app import crud, database

    login(client)
    token = _csrf(client, "/admin/terminals")
    # Create
    resp = client.post(
        "/admin/terminals",
        data={
            "csrf_token": token,
            "type": "timemoto",
            "name": "Eingang",
            "host": "192.168.1.50",
            "port": "80",
            "username": "admin",
            "password": "secret",
            "active": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db = database.SessionLocal()
    try:
        terminals = crud.get_terminals(db)
        assert len(terminals) == 1
        term = terminals[0]
        assert term.name == "Eingang" and term.host == "192.168.1.50"
        term_id = term.id
    finally:
        db.close()

    # Edit – blank password keeps the stored one.
    token = _csrf(client, "/admin/terminals")
    client.post(
        "/admin/terminals",
        data={
            "csrf_token": token,
            "terminal_id": str(term_id),
            "type": "timemoto",
            "name": "Eingang Nord",
            "host": "192.168.1.51",
            "port": "80",
            "username": "admin",
            "password": "",
            "active": "1",
        },
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        term = crud.get_terminal(db, term_id)
        assert term.name == "Eingang Nord" and term.host == "192.168.1.51"
        assert term.password == "secret"  # preserved
    finally:
        db.close()

    # Toggle (deactivate)
    token = _csrf(client, "/admin/terminals")
    client.post(
        f"/admin/terminals/{term_id}/toggle",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        assert crud.get_terminal(db, term_id).active is False
    finally:
        db.close()

    # Delete
    token = _csrf(client, "/admin/terminals")
    client.post(
        f"/admin/terminals/{term_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        assert crud.get_terminals(db) == []
    finally:
        db.close()


def test_terminal_connection_test_unreachable(client):
    login(client)
    token = _csrf(client, "/admin/terminals")
    resp = client.post(
        "/admin/terminals/test",
        data={
            "csrf_token": token,
            "type": "timemoto",
            "name": "Test",
            "host": "203.0.113.255",  # TEST-NET, not reachable
            "port": "1",
            "timeout": "1",
        },
    )
    body = resp.json()
    # The host is unreachable, so the test must fail gracefully (not 500).
    assert body["ok"] is False
    assert "message" in body


# --- logging channel + setting ---------------------------------------------

def test_terminal_log_channel(client):
    from app import logging_setup

    assert logging_setup.CHANNELS["terminal"] == "terminal.log"
    login(client)
    html = client.get("/admin/system/logs?channel=terminal").text
    assert "terminal" in html


def test_settings_has_terminal_logging(client):
    login(client)
    html = client.get("/admin/system/settings").text
    assert 'name="terminal_logging"' in html


# --- system status ---------------------------------------------------------

def test_system_status_shows_terminals(client):
    login(client)
    html = client.get("/admin/system/status").text
    assert "Terminals" in html
    assert "Letzter Synchronisationsfehler" in html


# --- database config: ports + placeholders ---------------------------------

def test_database_config_port_logic(client):
    login(client)
    html = client.get("/admin/system/database").text
    # Default ports for every server backend are present in the modal JS.
    assert "postgresql: 5432" in html
    assert "mysql: 3306" in html and "mariadb: 3306" in html
    # Port placeholder + previous-type tracking keep saved values intact.
    assert "portInput.placeholder" in html
    assert "previousType" in html


# --- legacy timemoto.json migration ----------------------------------------

def test_legacy_timemoto_config_migrated(tmp_path, monkeypatch):
    """A pre-0.9.8 timemoto.json is imported into the terminals table."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "timemoto.json").write_text(
        json.dumps(
            {
                "host": "10.0.0.5",
                "port": 8080,
                "username": "device",
                "password": "pw",
                "use_ssl": True,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")

    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]

    from fastapi.testclient import TestClient
    import app.main as main

    with TestClient(main.app):
        from app import crud, database

        db = database.SessionLocal()
        try:
            terminals = crud.get_terminals(db)
            assert len(terminals) == 1
            term = terminals[0]
            assert term.type == "timemoto"
            assert term.host == "10.0.0.5" and term.port == 8080
            assert term.password == "pw" and term.use_ssl is True
        finally:
            db.close()
