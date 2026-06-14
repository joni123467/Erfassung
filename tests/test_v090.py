"""Regression tests for the 0.9.0 release.

Covered areas: version, dashboard (single holiday block + dynamic ArbZG hint),
logging system (files, rotation, download, ZIP, clear), administration system
pages (status, errors, settings, backups), audit/security logging, health check
and settings/holiday import/export.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")

    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]

    from fastapi.testclient import TestClient
    import app.main as main

    with TestClient(main.app) as test_client:
        # Disable the forced password change for the seeded admin so we can
        # reach the admin pages directly.
        from app import database, security

        db = database.SessionLocal()
        try:
            from app import crud

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
    match = _CSRF_RE.search(html)
    assert match, f"no csrf token on {url}"
    return match.group(1)


def login(client, username="admin", password="Admin!0000"):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


# --- Version ---------------------------------------------------------------

def test_version_is_090(client):
    assert client.main.APP_VERSION == "0.9.8"


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.9.8"
    assert body["checks"]["database"] is True
    assert body["checks"]["volumes"] is True


# --- Logging ---------------------------------------------------------------

def test_security_log_on_failed_and_successful_login(client):
    from app import paths

    login(client, password="wrong")
    login(client)
    security_log = (paths.LOGS_DIR / "security.log").read_text(encoding="utf-8")
    assert "Fehlgeschlagener Login" in security_log
    assert "Erfolgreiche Anmeldung" in security_log


def test_application_log_created_on_startup(client):
    from app import paths

    assert (paths.LOGS_DIR / "application.log").exists()
    content = (paths.LOGS_DIR / "application.log").read_text(encoding="utf-8")
    assert "startet" in content


def test_log_download_and_zip(client):
    login(client)
    single = client.get("/admin/system/logs/download?name=application")
    assert single.status_code == 200
    assert "attachment" in single.headers["content-disposition"]

    archive = client.get("/admin/system/logs/download-zip?names=application&names=security")
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    assert archive.content[:2] == b"PK"


def test_log_clear_requires_admin_and_works(client):
    login(client)
    token = _csrf(client, "/admin/system/logs")
    response = client.post(
        "/admin/system/logs/clear",
        data={"channel": "api", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_log_rotation_config_applied(client):
    from app import app_config, logging_setup

    cfg = app_config.LoggingConfig(rotation_max_bytes=1024, rotation_backup_count=2)
    logging_setup.configure_logging(cfg)
    # write enough records to force at least one rotation
    for index in range(500):
        logging_setup.log_application(f"rotation probe line {index}")
    from app import paths

    rotated = list(paths.LOGS_DIR.glob("application.log.*"))
    assert rotated, "expected at least one rotated log file"


# --- Administration system pages ------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "/admin/system/status",
        "/admin/system/logs",
        "/admin/system/errors",
        "/admin/system/settings",
        "/admin/system/backups",
    ],
)
def test_admin_system_pages_render(client, url):
    login(client)
    response = client.get(url)
    assert response.status_code == 200


def test_admin_system_pages_blocked_without_admin(client):
    # not logged in -> redirect to login
    response = client.get("/admin/system/status", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")


def test_system_settings_save_and_audit(client):
    from app import app_config, paths

    login(client)
    token = _csrf(client, "/admin/system/settings")
    response = client.post(
        "/admin/system/settings",
        data={
            "level": "DEBUG",
            "api_logging": "on",
            "rotation_max_mb": "2",
            "rotation_backup_count": "3",
            "auto_cleanup_days": "30",
            "sync_interval_minutes": "15",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = app_config.load_logging_config()
    assert saved.level == "DEBUG"
    assert saved.rotation_backup_count == 3
    assert saved.security_logging is False  # checkbox not sent
    audit = (paths.LOGS_DIR / "audit.log").read_text(encoding="utf-8")
    assert "Systemeinstellungen geändert" in audit


def test_settings_export_import_roundtrip(client):
    from app import app_config

    login(client)
    export = client.get("/admin/system/settings/export")
    assert export.status_code == 200
    payload = export.text

    token = _csrf(client, "/admin/system/settings")
    response = client.post(
        "/admin/system/settings/import",
        data={"settings_json": payload, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "msg=" in response.headers["location"]


def test_settings_import_rejects_invalid(client):
    login(client)
    token = _csrf(client, "/admin/system/settings")
    response = client.post(
        "/admin/system/settings/import",
        data={"settings_json": '{"logging": {"level": "BOGUS"}}', "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_backup_create(client):
    """Job-based backup: create a local job, run it, expect a history entry."""
    from app import crud, database

    login(client)
    token = _csrf(client, "/admin/system/backups")
    client.post(
        "/admin/system/backups/jobs",
        data={
            "name": "Lokal",
            "active": "on",
            "schedule": "manual",
            "contents": ["database", "config"],
            "target_type": "local",
            "retention_count": "5",
            "retention_days": "30",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        job = crud.get_backup_jobs(db)[0]
    finally:
        db.close()
    token = _csrf(client, "/admin/system/backups")
    response = client.post(
        f"/admin/system/backups/jobs/{job.id}/run",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db = database.SessionLocal()
    try:
        runs = crud.get_backup_runs(db)
        assert runs and runs[0].status in {"success", "warning"}
    finally:
        db.close()


# --- Holidays import/export -----------------------------------------------

def test_holiday_export_import(client):
    login(client)
    export = client.get("/admin/holidays/export")
    assert export.status_code == 200
    import json

    data = json.loads(export.text)
    assert "holidays" in data

    token = _csrf(client, "/admin/holidays")
    payload = json.dumps({"holidays": [{"name": "Testtag", "date": "2030-05-01", "region": "DE"}]})
    response = client.post(
        "/admin/holidays/import",
        data={"holidays_json": payload, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "importiert" in response.headers["location"]


# --- Dashboard / ArbZG hint ------------------------------------------------

def test_dashboard_single_holiday_block_and_hint(client):
    from app import crud, database

    login(client)
    html = client.get("/dashboard").text
    # Feiertage should appear exactly once as a heading.
    assert html.count("Feiertagsübersicht") == 1
    assert "Nächste Feiertage" not in html
    # auto break enabled by default -> pause hint visible
    assert "automatisch gesetzliche Pausen" in html

    db = database.SessionLocal()
    try:
        admin = crud.get_user_by_username(db, "admin")
        admin.auto_break_deduction = False
        db.commit()
    finally:
        db.close()
    html_disabled = client.get("/dashboard").text
    assert "automatisch gesetzliche Pausen" not in html_disabled
    assert "nach Freigabe durch die Administration" in html_disabled
