"""Regression tests for 0.9.6 – Administration UI/UX overhaul.

Covers: version bump, the reiter-style admin navigation, the separated
Backup-Historie view (own route + own data query), navigation collapse on
edit/form pages, the QR code inside the user edit dialog and the restructured
system settings page.
"""

from __future__ import annotations

import re
import sys

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
    assert client.main.APP_VERSION == "0.9.7"
    assert client.get("/health").json()["version"] == "0.9.7"


# --- navigation: reiter design + single open behaviour ---------------------

def test_admin_nav_is_reiter_style(client):
    login(client)
    html = client.get("/admin/users").text
    # Tabs/Reiter markup with summaries; collapse + modal-close hooks present.
    assert 'class="adminnav"' in html
    assert "adminnav__summary" in html
    assert "adminnav:close" in html
    assert "modal-open" in html


def test_active_group_open_on_list_page(client):
    login(client)
    html = client.get("/admin/users").text
    # The users list is not a form page -> active group is rendered open.
    assert re.search(r'<details class="adminnav__group[^"]*is-active"[^>]*\sopen', html)


def test_nav_collapsed_on_edit_page(client):
    login(client)
    html = client.get("/admin/users/1").text
    # On the edit page no group must be force-opened (admin_nav_collapse).
    assert "<details" in html
    assert not re.search(r"<details[^>]*\sopen", html), "no nav group may be open on a form page"


# --- backup history: separate view -----------------------------------------

def test_backup_history_has_own_route(client):
    login(client)
    resp = client.get("/admin/system/backups/history")
    assert resp.status_code == 200
    html = resp.text
    assert "Backup-Historie" in html
    # History view does not render the job management table/button.
    assert "Neuer Backup-Job" not in html
    assert "backup-job-modal" not in html
    # History-specific columns.
    assert "Dauer" in html and "Ziel" in html


def test_backup_jobs_page_has_no_history_table(client):
    login(client)
    html = client.get("/admin/system/backups").text
    assert "Neuer Backup-Job" in html
    # The inline history section was removed; it now links to the dedicated page.
    assert "/admin/system/backups/history" in html
    assert "Backup-Historie</h2>" not in html


def test_nav_links_history_to_dedicated_route(client):
    login(client)
    html = client.get("/admin/system/backups").text
    assert 'href="/admin/system/backups/history"' in html
    assert 'href="/admin/system/backups#history"' not in html


# --- user edit dialog: QR code ---------------------------------------------

def test_user_edit_shows_qr_code(client):
    login(client)
    html = client.get("/admin/users/1").text
    assert "user-qr" in html
    assert "create-qr-code" in html
    assert "Mobile Anmeldung" in html
    assert "Neu generieren" in html


def test_user_create_has_no_qr(client):
    login(client)
    html = client.get("/admin/users/new").text
    # QR only makes sense for an existing user.
    assert "user-qr__code" not in html


# --- system settings: structured sections ----------------------------------

def test_settings_has_sections(client):
    login(client)
    html = client.get("/admin/system/settings").text
    for section in ("Allgemein", "Logging", "Log-Rotation", "Synchronisation"):
        assert f"<legend>{section}</legend>" in html
    assert "settings-section" in html
    # Allgemein shows the running version and database backend.
    assert "0.9.7" in html
    assert "SQLite" in html


def test_settings_save_still_works(client):
    login(client)
    token = _csrf(client, "/admin/system/settings")
    resp = client.post(
        "/admin/system/settings",
        data={
            "level": "DEBUG",
            "rotation_max_mb": "5",
            "rotation_backup_count": "5",
            "auto_cleanup_days": "90",
            "sync_interval_minutes": "60",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    from app import app_config

    assert app_config.load_logging_config().level == "DEBUG"
