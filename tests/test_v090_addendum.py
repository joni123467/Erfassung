"""Regression tests for the 0.9.0 addendum (§22–§26).

Covered: holiday overhaul (current year + custom preservation), MySQL-ready
DB layer & dialect-aware migrations, the corrected offline-action counter /
sync diagnostics, and the extended backup system (config, integrity, history).
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
    match = _CSRF_RE.search(html)
    assert match, f"no csrf token on {url}"
    return match.group(1)


def login(client):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"username": "admin", "password": "Admin!0000", "csrf_token": token},
        follow_redirects=False,
    )


# --- §22 Feiertage ---------------------------------------------------------

def test_holidays_page_has_no_year_dropdown(client):
    login(client)
    html = client.get("/admin/holidays").text
    assert 'name="holiday_year"' not in html
    assert "Feiertage übernehmen" in html


def test_holiday_apply_preserves_custom(client):
    from app import crud, database, schemas, holiday_calculator
    from datetime import date

    login(client)
    db = database.SessionLocal()
    year = date.today().year
    try:
        # a custom holiday in Bavaria for the current year
        crud.upsert_holidays(
            db,
            [schemas.HolidayCreate(name="Betriebsfest", date=date(year, 7, 1), region="BY", source="custom")],
        )
    finally:
        db.close()

    token = _csrf(client, "/admin/holidays?state=BY")
    response = client.post(
        "/admin/holidays/apply",
        data={"state": "BY", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303

    db = database.SessionLocal()
    try:
        holidays = crud.get_holidays_for_year(db, year, "BY")
        names = [h.name for h in holidays]
        sources = {h.source for h in holidays}
        # custom preserved
        assert "Betriebsfest" in names
        # statutory loaded
        assert "statutory" in sources
        # no duplicate dates
        dates = [h.date for h in holidays]
        assert len(dates) == len(set(dates))
    finally:
        db.close()


def test_holiday_apply_twice_no_duplicates(client):
    from app import crud, database
    from datetime import date

    login(client)
    year = date.today().year
    for _ in range(2):
        token = _csrf(client, "/admin/holidays?state=NW")
        client.post(
            "/admin/holidays/apply",
            data={"state": "NW", "csrf_token": token},
            follow_redirects=False,
        )
    db = database.SessionLocal()
    try:
        holidays = crud.get_holidays_for_year(db, year, "NW")
        dates = [h.date for h in holidays]
        assert len(dates) == len(set(dates))
    finally:
        db.close()


# --- §23 MySQL-readiness ---------------------------------------------------

def test_models_have_string_lengths():
    """MySQL's create_all rejects VARCHAR without a length."""
    from app import models

    for table in models.Base.metadata.tables.values():
        for column in table.columns:
            type_name = type(column.type).__name__
            if type_name == "String":
                assert column.type.length, f"{table.name}.{column.name} needs a length"


def test_database_backend_detection(client):
    """Backend detection logic for SQLite and MySQL URLs.

    The MySQL branch is verified at URL level (instantiating a MySQL engine
    would eagerly import the PyMySQL driver, which is only present in a real
    deployment, not in the unit-test sandbox).
    """
    from sqlalchemy.engine import make_url
    from app import database

    # current engine is sqlite
    assert database.DB_BACKEND == "sqlite"
    assert database.IS_SQLITE is True

    mysql_url = make_url("mysql+pymysql://u:p@localhost/erfassung")
    assert mysql_url.get_backend_name() == "mysql"


def test_schema_migrations_tracked(client):
    from app import database, db_schema, db_migrations

    applied = db_schema.applied_versions(database.engine)
    all_versions = {v for v, _ in db_migrations.MIGRATIONS}
    assert all_versions.issubset(applied)
    assert 5 in applied  # holidays.source migration


def test_db_status_fields(client):
    from app import database, system_info

    db = database.SessionLocal()
    try:
        status = system_info.database_status(db)
    finally:
        db.close()
    assert status["backend"] == "sqlite"
    assert status["server_version"]
    assert status["pending_migrations"] == []
    assert status["last_migration"] >= 5


# --- §24 Offline counter / sync diagnostics --------------------------------

def test_open_offline_actions_is_zero_even_with_processed_actions(client):
    from app import crud, database, system_info

    login(client)
    db = database.SessionLocal()
    try:
        admin = crud.get_user_by_username(db, "admin")
        for i in range(5):
            crud.create_mobile_sync_action(
                db, user_id=admin.id, client_action_id=f"a{i}", action="punch"
            )
        diag = system_info.sync_diagnostics(db)
    finally:
        db.close()
    # processed actions exist, but there is NO server-side backlog
    assert diag["processed_offline_actions"] == 5
    assert diag["open_actions"] == 0


def test_system_status_shows_zero_open_actions(client):
    login(client)
    html = client.get("/admin/system/status").text
    assert "Offene Offline-Aktionen" in html


def test_sync_page_renders(client):
    login(client)
    response = client.get("/admin/system/sync")
    assert response.status_code == 200
    assert "Synchronisation" in response.text


# --- §25/§26 Backups -------------------------------------------------------

def test_backup_settings_save_and_password_persist(client):
    from app import app_config

    login(client)
    token = _csrf(client, "/admin/system/backups")
    client.post(
        "/admin/system/backups/settings",
        data={
            "target": "ftp",
            "retention_count": "5",
            "retention_days": "14",
            "ftp_host": "ftp.example.com",
            "ftp_username": "backupuser",
            "ftp_password": "secret",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    config = app_config.load_backup_config()
    assert config.target == "ftp"
    assert config.retention_count == 5
    assert config.ftp_password == "secret"
    # masked variant must not leak the password
    assert config.safe_dict()["ftp_password"] == "***"

    # re-saving with a blank password keeps the stored one
    token = _csrf(client, "/admin/system/backups")
    client.post(
        "/admin/system/backups/settings",
        data={"target": "ftp", "ftp_host": "ftp.example.com", "ftp_password": "", "csrf_token": token},
        follow_redirects=False,
    )
    assert app_config.load_backup_config().ftp_password == "secret"


def test_backup_create_records_history_and_integrity(client):
    from app import backup_manager

    login(client)
    token = _csrf(client, "/admin/system/backups")
    response = client.post(
        "/admin/system/backups/create", data={"csrf_token": token}, follow_redirects=False
    )
    assert response.status_code == 303
    history = backup_manager.history()
    assert history, "expected a history entry"
    assert history[0]["result"] == "success"
    # integrity: the created archive is a readable zip
    backups = backup_manager.list_backups()
    assert backups
    ok, _ = backup_manager.verify_integrity(__import__("pathlib").Path(backups[0]["path"]))
    assert ok


def test_backup_local_connection_test(client):
    from app import app_config, backup_manager

    ok, message = backup_manager.test_connection(app_config.BackupConfig(target="local"))
    assert ok is True
    assert "Lokales" in message


def test_backup_retention(client):
    from app import app_config, backup_manager

    # create more archives than the retention count, then prune
    for _ in range(4):
        backup_manager.create_backup(app_config.BackupConfig(target="local", retention_count=0))
    removed = backup_manager.apply_retention(app_config.BackupConfig(retention_count=2, retention_days=0))
    assert removed >= 1
    assert len(backup_manager.list_backups()) <= 2


def test_password_not_logged(client):
    from app import app_config, backup_manager, paths

    login(client)
    backup_manager.test_connection(
        app_config.BackupConfig(target="ftp", ftp_host="localhost", ftp_password="topsecret")
    )
    for name in ("application.log", "audit.log", "error.log"):
        path = paths.LOGS_DIR / name
        if path.exists():
            assert "topsecret" not in path.read_text(encoding="utf-8")
