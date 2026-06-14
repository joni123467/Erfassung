"""Regression tests for 0.9.4 – Enterprise Backup & Restore.

Covers: dedicated backup.log, backup metadata, verify (green/yellow/red),
upload (streamed + integrity + isolation), restore (safety backup, data
preservation), version-aware restore (auto-migrations), path-traversal guard,
restore history, navigation, and audit logging.
"""

from __future__ import annotations

import io
import re
import sqlite3
import sys
import zipfile
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


def _create_and_run_local_job(client):
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
    backups = backup_manager.list_local_backups()
    assert backups
    return Path(backups[0]["path"])


# --- backup.log + metadata -------------------------------------------------

def test_backup_log_channel_registered(client):
    from app import logging_setup, paths

    assert "backup" in logging_setup.CHANNELS
    login(client)
    _create_and_run_local_job(client)
    backup_log = paths.LOGS_DIR / "backup.log"
    assert backup_log.exists()
    content = backup_log.read_text(encoding="utf-8")
    assert "Backup gestartet" in content
    assert "Backup erfolgreich" in content


def test_backup_log_visible_in_logs_page(client):
    login(client)
    html = client.get("/admin/system/logs?channel=backup").text
    assert html  # renders
    # backup channel offered as a tab
    assert "backup" in client.get("/admin/system/logs").text


def test_backup_archive_has_metadata(client):
    from app import backup_manager

    login(client)
    archive = _create_and_run_local_job(client)
    meta = backup_manager.read_metadata(archive)
    assert meta and meta["app_version"] == "0.9.5"
    assert meta["database_type"] == "sqlite"
    assert "database" in meta["contents"]


# --- verify (green/yellow/red) ---------------------------------------------

def test_verify_levels(client):
    from app import backup_manager, paths

    login(client)
    archive = _create_and_run_local_job(client)
    green = backup_manager.verify(archive)
    assert green["level"] == "green"
    assert green["has_database"] and green["has_metadata"]

    # a zip without a database -> red
    bad = paths.DATA_DIR / "backups" / "backup_job999_x.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("config/system.json", "{}")
    red = backup_manager.verify(bad)
    assert red["level"] == "red"

    # not a zip at all -> red, not readable
    notzip = paths.DATA_DIR / "backups" / "backup_job999_y.zip"
    notzip.write_text("garbage", encoding="utf-8")
    assert backup_manager.verify(notzip)["level"] == "red"


# --- upload ----------------------------------------------------------------

def test_upload_backup_streamed_and_registered(client):
    from app import backup_manager, paths

    login(client)
    archive = _create_and_run_local_job(client)
    raw = archive.read_bytes()
    token = _csrf(client, "/admin/system/restore")
    resp = client.post(
        "/admin/system/restore/upload",
        data={"csrf_token": token},
        files={"backup_file": ("mybackup.zip", io.BytesIO(raw), "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "msg=" in resp.headers["location"]
    uploads = [b for b in backup_manager.list_local_backups() if b["source"] == "upload"]
    assert uploads, "uploaded backup should be registered"
    backup_log = (paths.LOGS_DIR / "backup.log").read_text(encoding="utf-8")
    assert "Upload erfolgreich" in backup_log
    assert "Integritätsprüfung erfolgreich" in backup_log
    audit = (paths.LOGS_DIR / "audit.log").read_text(encoding="utf-8")
    assert "Backup hochgeladen" in audit


def test_upload_rejects_non_zip(client):
    login(client)
    token = _csrf(client, "/admin/system/restore")
    resp = client.post(
        "/admin/system/restore/upload",
        data={"csrf_token": token},
        files={"backup_file": ("evil.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


# --- path traversal --------------------------------------------------------

def test_path_traversal_guard(client):
    from app import backup_manager

    assert backup_manager.resolve_backup_path("../../etc/passwd") is None
    assert backup_manager.resolve_backup_path("..\\secret") is None
    assert backup_manager.resolve_backup_path("nonexistent.zip") is None


# --- restore (data preservation + safety backup) ---------------------------

def test_restore_replaces_data_and_creates_safety_backup(client):
    from app import backup_manager, crud, database, restore_manager, schemas

    login(client)
    archive = _create_and_run_local_job(client)

    # mutate DB after backup: add a company that is NOT in the backup
    db = database.SessionLocal()
    try:
        crud.create_company(db, schemas.CompanyCreate(name="AFTER_BACKUP"))
        assert crud.get_company_by_name(db, "AFTER_BACKUP") is not None
        admin = crud.get_user_by_username(db, "admin")
    finally:
        db.close()

    result = restore_manager.restore_from_archive(archive, user=admin)
    assert result["status"] in {"success", "warning"}
    assert result["safety_backup"], "a pre_restore safety backup must be created"

    # safety backup file exists
    safety = [b for b in backup_manager.list_local_backups() if b["source"] == "safety"]
    assert safety

    # the post-backup company is gone (DB was replaced by the snapshot)
    db = database.SessionLocal()
    try:
        assert crud.get_company_by_name(db, "AFTER_BACKUP") is None
        # restore history recorded
        runs = crud.get_restore_runs(db)
        assert runs and runs[0].status in {"success", "warning"}
        assert runs[0].safety_backup
    finally:
        db.close()


def test_restore_runs_migrations_for_old_backup(client):
    """§7: restoring an older backup auto-applies outstanding migrations."""
    from app import backup_manager, database, restore_manager, paths
    import json

    login(client)
    # craft an "old" SQLite DB (schema like 0.7.x: user_version=4, no
    # schema_migrations, no backup tables)
    old_db = paths.DATA_DIR / "old_snapshot.db"
    con = sqlite3.connect(old_db)
    con.executescript(
        "CREATE TABLE users(id INTEGER PRIMARY KEY, username VARCHAR, full_name VARCHAR, "
        "email VARCHAR, standard_daily_minutes INTEGER DEFAULT 480, pin_code VARCHAR, "
        "group_id INTEGER);"
        "CREATE TABLE groups(id INTEGER PRIMARY KEY, name VARCHAR, is_admin INTEGER DEFAULT 0);"
        "INSERT INTO users(username, full_name, email, pin_code) VALUES('legacy','L','l@x.de','1234');"
        "PRAGMA user_version=4;"
    )
    con.commit()
    con.close()

    archive = paths.DATA_DIR / "backups" / "backup_job777_old.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("backup_meta.json", json.dumps({
            "app_version": "0.7.2", "database_type": "sqlite", "schema_version": 4,
            "created_at": "2025-01-01T00:00:00", "backup_type": "job",
            "contents": ["database"],
        }))
        z.write(old_db, arcname="data/erfassung.db")

    db = database.SessionLocal()
    try:
        admin = __import__("app.crud", fromlist=["x"]).get_user_by_username(db, "admin")
    finally:
        db.close()

    result = restore_manager.restore_from_archive(archive, user=admin)
    assert result["status"] in {"success", "warning"}
    # migrations 5,6,7 must have been applied during the restore
    assert set(result["migrations_applied"]) >= {5, 6, 7}

    # the restored + migrated DB has the new tables and the legacy user
    db = database.SessionLocal()
    try:
        from app import crud, db_schema, database as dbmod
        assert 7 in db_schema.applied_versions(dbmod.engine)
        assert crud.get_user_by_username(db, "legacy") is not None
    finally:
        db.close()
    backup_log = (paths.LOGS_DIR / "backup.log").read_text(encoding="utf-8")
    assert "Restore erfolgreich" in backup_log


def test_restore_run_route_requires_confirmation(client):
    login(client)
    archive = _create_and_run_local_job(client)
    name = archive.name
    token = _csrf(client, "/admin/system/restore")
    # wrong confirmation -> rejected
    resp = client.post(
        "/admin/system/restore/run",
        data={"file": name, "confirm": "ja", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


# --- pages / navigation ----------------------------------------------------

@pytest.mark.parametrize("url", ["/admin/system/restore", "/admin/system/restore/history"])
def test_restore_pages_render(client, url):
    login(client)
    assert client.get(url).status_code == 200


def test_navigation_has_restore_entries(client):
    login(client)
    html = client.get("/admin/system/status").text
    assert "Wiederherstellung" in html
    assert "Restore-Historie" in html


def test_restore_history_migration_present(client):
    from app import database, db_schema

    assert 7 in db_schema.applied_versions(database.engine)
    # restore_runs table exists
    from sqlalchemy import inspect
    assert inspect(database.engine).has_table("restore_runs")
