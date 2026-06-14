"""Regression tests for 0.9.7 – Datenbankverwaltung & -migration.

Covers: version bump, the new Administration → System → Datenbank area
(recommendation cards + ⭐ badges + config modal), the ``database`` log channel,
the ``database_logging`` setting, and the cross-database migration engine
(SQLite → SQLite as a stand-in exercising the full copy/integrity/backup/
rollback machinery) including the automatic pre-migration safety backup and the
data-loss guard / rollback when a target is not empty.
"""

from __future__ import annotations

import re
import shutil
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
    assert client.main.APP_VERSION == "0.9.7"
    assert client.get("/health").json()["version"] == "0.9.7"


# --- navigation + page -----------------------------------------------------

def test_nav_has_database_entry(client):
    login(client)
    html = client.get("/admin/system/status").text
    assert 'href="/admin/system/database"' in html


def test_database_page_renders(client):
    login(client)
    resp = client.get("/admin/system/database")
    assert resp.status_code == 200
    html = resp.text
    # Recommendation cards + ⭐ badge for MariaDB and PostgreSQL.
    assert "Empfohlene Datenbanken" in html
    assert html.count("⭐ Empfohlen") >= 2
    assert "PostgreSQL" in html and "MariaDB" in html
    # Config modal + active-database dropdown + connection test hook.
    assert 'id="db-modal"' in html
    assert "Datenbank konfigurieren" in html
    assert "/admin/system/database/test" in html
    # Supported versions are surfaced.
    assert "16" in html and "10.11 LTS" in html


def test_database_progress_route(client):
    login(client)
    assert client.get("/admin/system/database/progress").status_code == 200


# --- logging channel + setting ---------------------------------------------

def test_database_log_channel(client):
    from app import logging_setup

    assert logging_setup.CHANNELS["database"] == "database.log"
    login(client)
    html = client.get("/admin/system/logs?channel=database").text
    assert "database" in html


def test_settings_has_database_logging(client):
    login(client)
    html = client.get("/admin/system/settings").text
    assert 'name="database_logging"' in html


# --- connection test -------------------------------------------------------

def test_connection_test_invalid(client):
    login(client)
    token = _csrf(client, "/admin/system/database")
    resp = client.post(
        "/admin/system/database/test",
        data={"type": "postgresql", "host": "", "name": "", "user": "", "csrf_token": token},
    )
    body = resp.json()
    assert body["ok"] is False


def test_connection_test_sqlite_ok(client):
    login(client)
    token = _csrf(client, "/admin/system/database")
    target = str(client.tmp_path / "probe.db")
    resp = client.post(
        "/admin/system/database/test",
        data={"type": "sqlite", "sqlite_path": target, "csrf_token": token},
    )
    body = resp.json()
    assert body["ok"] is True


# --- migration engine (full pipeline) --------------------------------------

def test_migration_sqlite_to_sqlite(client):
    """End-to-end migration: copies all data, verifies integrity, writes a
    safety backup and the database.log, and switches the active backend."""
    from app import app_config, database, db_migrator, log_tools, models

    src = database.SessionLocal()
    try:
        users_before = src.query(models.User).count()
        groups_before = src.query(models.Group).count()
    finally:
        src.close()
    assert users_before >= 1 and groups_before >= 1

    target_path = str(client.tmp_path / "target.db")
    target = app_config.DatabaseConfig(type="sqlite", sqlite_path=target_path)
    result = db_migrator.migrate(target, username="admin", token="t1")

    assert result["status"] == "success", result["message"]
    assert result["integrity"]["ok"] is True
    assert result["records"] >= users_before + groups_before
    # Mandatory pre-migration safety backup created.
    assert result["safety_backup"] and result["safety_backup"].startswith("pre_db_migration_")
    backups = list((client.tmp_path / "data" / "backups").glob("pre_db_migration_*.zip"))
    assert backups, "safety backup file must exist"
    # Active engine now points at the target and carries the same data.
    assert database.SQLALCHEMY_DATABASE_URL.endswith("target.db")
    db = database.SessionLocal()
    try:
        assert db.query(models.User).count() == users_before
        assert db.query(models.Group).count() == groups_before
    finally:
        db.close()
    # database.log records the migration.
    lines = " ".join(line.message for line in log_tools.read_log("database", limit=200))
    assert "Migration erfolgreich" in lines
    assert "Sicherheitsbackup erstellt" in lines
    # Persisted selection updated.
    assert app_config.load_database_config().sqlite_path.endswith("target.db")


def test_migration_rollback_on_nonempty_target(client):
    """A non-empty target must abort the migration (data-loss guard) and leave
    the original database active (rollback)."""
    from app import app_config, database, db_migrator, log_tools

    original_url = database.SQLALCHEMY_DATABASE_URL
    # Pre-populate the target with a copy of the live (non-empty) database.
    live_db = client.tmp_path / "erfassung.db"
    target_path = client.tmp_path / "occupied.db"
    shutil.copy(live_db, target_path)

    target = app_config.DatabaseConfig(type="sqlite", sqlite_path=str(target_path))
    result = db_migrator.migrate(target, username="admin", token="t2")

    assert result["status"] == "error"
    assert "nicht leer" in result["message"].lower()
    # Old database is still active – no switch happened.
    assert database.SQLALCHEMY_DATABASE_URL == original_url
    lines = " ".join(line.message for line in log_tools.read_log("database", limit=200))
    assert "Rollback durchgeführt" in lines
