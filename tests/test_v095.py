"""Regression tests for 0.9.5 – asynchronous restore + status API.

Covers: version, async restore job (no 500 in the request), status API,
progress page, restart-safe status file, detailed backup.log entries, restore
history with duration/log-token, error handling for invalid/missing backups,
and the extended system status.
"""

from __future__ import annotations

import re
import sys
import time
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


def _make_backup(client) -> str:
    token = _csrf(client, "/admin/system/backups")
    client.post(
        "/admin/system/backups/jobs",
        data={"name": "Local", "active": "on", "schedule": "manual",
              "contents": ["database", "config"], "target_type": "local",
              "retention_count": "10", "retention_days": "0", "csrf_token": token},
        follow_redirects=False,
    )
    from app import crud, database
    db = database.SessionLocal()
    try:
        job = crud.get_backup_jobs(db)[0]
    finally:
        db.close()
    token = _csrf(client, "/admin/system/backups")
    client.post(f"/admin/system/backups/jobs/{job.id}/run", data={"csrf_token": token},
                follow_redirects=False)
    from app import backup_manager
    return Path(backup_manager.list_local_backups()[0]["path"]).name


def _wait_terminal(timeout=15.0):
    from app import restore_jobs
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = restore_jobs.read_status()
        if status.get("state") in {"completed", "failed"}:
            return status
        time.sleep(0.2)
    raise AssertionError(f"restore did not finish in time: {restore_jobs.read_status()}")


# --- version ---------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.9.7"
    assert client.get("/health").json()["version"] == "0.9.7"


# --- async restore: no 500, runs in background -----------------------------

def test_restore_is_async_and_succeeds(client):
    from app import crud, database

    login(client)
    name = _make_backup(client)

    token = _csrf(client, "/admin/system/restore")
    # The request must return immediately with a redirect to the progress page,
    # never a 500 – even though the restore swaps the database.
    resp = client.post(
        "/admin/system/restore/run",
        data={"file": name, "confirm": "WIEDERHERSTELLEN", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/admin/system/restore/progress")

    status = _wait_terminal()
    assert status["state"] == "completed"
    assert status["result_status"] in {"success", "warning"}
    assert status.get("redirect") == "/login"

    # history recorded with duration + log token
    db = database.SessionLocal()
    try:
        runs = crud.get_restore_runs(db)
        assert runs and runs[0].status in {"success", "warning"}
        assert runs[0].duration_seconds is not None
        assert runs[0].log_token
    finally:
        db.close()


def test_restore_creates_safety_backup_and_logs(client):
    from app import backup_manager, paths

    login(client)
    name = _make_backup(client)
    token = _csrf(client, "/admin/system/restore")
    client.post("/admin/system/restore/run",
                data={"file": name, "confirm": "WIEDERHERSTELLEN", "csrf_token": token},
                follow_redirects=False)
    _wait_terminal()

    safety = [b for b in backup_manager.list_local_backups() if b["source"] == "safety"]
    assert safety, "a pre_restore safety backup must be created"

    backup_log = (paths.LOGS_DIR / "backup.log").read_text(encoding="utf-8")
    for needle in ("Restore gestartet", "Sicherheitsbackup erstellt", "Migration gestartet",
                   "Migration erfolgreich", "Restore erfolgreich", "Anwendung wieder verfügbar"):
        assert needle in backup_log, f"missing backup.log entry: {needle}"


# --- status API ------------------------------------------------------------

def test_status_api_requires_session(client):
    # without login -> 401, never 500
    resp = client.get("/api/restore/status")
    assert resp.status_code == 401
    assert resp.json()["state"] == "unauthorized"


def test_status_api_returns_state(client):
    login(client)
    resp = client.get("/api/restore/status")
    assert resp.status_code == 200
    assert "state" in resp.json()


def test_progress_page_renders(client):
    login(client)
    assert client.get("/admin/system/restore/progress").status_code == 200


# --- error handling --------------------------------------------------------

def test_restore_rejects_without_confirmation(client):
    login(client)
    name = _make_backup(client)
    token = _csrf(client, "/admin/system/restore")
    resp = client.post("/admin/system/restore/run",
                       data={"file": name, "confirm": "nein", "csrf_token": token},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_restore_rejects_invalid_backup(client):
    from app import paths

    login(client)
    # a damaged "backup" (not a zip)
    bad = paths.DATA_DIR / "backups"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "backup_broken.zip").write_text("not a zip", encoding="utf-8")
    token = _csrf(client, "/admin/system/restore")
    resp = client.post("/admin/system/restore/run",
                       data={"file": "backup_broken.zip", "confirm": "WIEDERHERSTELLEN",
                             "csrf_token": token},
                       follow_redirects=False)
    assert resp.status_code == 303
    # rejected at validation -> back to restore page with an error, no job queued
    assert "error=" in resp.headers["location"]
    from app import restore_jobs
    assert restore_jobs.read_status().get("state") in {"idle", None}


def test_restore_rejects_missing_file(client):
    login(client)
    token = _csrf(client, "/admin/system/restore")
    resp = client.post("/admin/system/restore/run",
                       data={"file": "does_not_exist.zip", "confirm": "WIEDERHERSTELLEN",
                             "csrf_token": token},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


# --- migration 8 + system status ------------------------------------------

def test_migration_8_columns_present(client):
    from app import database
    from sqlalchemy import inspect

    cols = {c["name"] for c in inspect(database.engine).get_columns("restore_runs")}
    assert {"duration_seconds", "log_token"}.issubset(cols)


def test_system_status_shows_restore_fields(client):
    login(client)
    html = client.get("/admin/system/status").text
    assert "Aktiver Restore-Job" in html
    assert "Letzte Migrationsausführung" in html
    assert "Letzte Wiederherstellung erfolgreich" in html
