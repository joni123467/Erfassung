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


# --- §1–§10 Job-based Backups ---------------------------------------------

def _create_local_job(client, **overrides):
    token = _csrf(client, "/admin/system/backups")
    data = {
        "name": overrides.get("name", "Lokal-Job"),
        "active": "on",
        "schedule": overrides.get("schedule", "manual"),
        "contents": overrides.get("contents", ["database", "config"]),
        "target_type": overrides.get("target_type", "local"),
        "retention_count": str(overrides.get("retention_count", 10)),
        "retention_days": str(overrides.get("retention_days", 30)),
        "csrf_token": token,
    }
    data.update({k: v for k, v in overrides.items() if k.startswith(("ftp_", "smb_", "local_"))})
    return client.post("/admin/system/backups/jobs", data=data, follow_redirects=False)


def test_backup_job_crud(client):
    from app import crud, database

    login(client)
    assert _create_local_job(client, name="Job A").status_code == 303
    db = database.SessionLocal()
    try:
        jobs = crud.get_backup_jobs(db)
        assert len(jobs) == 1 and jobs[0].name == "Job A"
        job_id = jobs[0].id
    finally:
        db.close()

    # edit
    token = _csrf(client, "/admin/system/backups")
    client.post(
        "/admin/system/backups/jobs",
        data={"job_id": str(job_id), "name": "Job A2", "active": "on", "schedule": "daily",
              "contents": ["database"], "target_type": "local", "retention_count": "3",
              "retention_days": "0", "csrf_token": token},
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        job = crud.get_backup_job(db, job_id)
        assert job.name == "Job A2" and job.schedule == "daily" and job.retention_count == 3
    finally:
        db.close()

    # toggle + delete
    token = _csrf(client, "/admin/system/backups")
    client.post(f"/admin/system/backups/jobs/{job_id}/toggle", data={"csrf_token": token}, follow_redirects=False)
    token = _csrf(client, "/admin/system/backups")
    client.post(f"/admin/system/backups/jobs/{job_id}/delete", data={"csrf_token": token}, follow_redirects=False)
    db = database.SessionLocal()
    try:
        assert crud.get_backup_jobs(db) == []
    finally:
        db.close()


def test_backup_job_run_history_and_integrity(client):
    from app import crud, database, backup_manager
    from pathlib import Path

    login(client)
    _create_local_job(client, name="RunJob")
    db = database.SessionLocal()
    try:
        job = crud.get_backup_jobs(db)[0]
    finally:
        db.close()
    token = _csrf(client, "/admin/system/backups")
    resp = client.post(f"/admin/system/backups/jobs/{job.id}/run", data={"csrf_token": token}, follow_redirects=False)
    assert resp.status_code == 303
    db = database.SessionLocal()
    try:
        runs = crud.get_backup_runs(db)
        assert runs and runs[0].status == "success"
        assert runs[0].filename and Path(runs[0].filename).exists()
        ok, _ = backup_manager.verify_integrity(Path(runs[0].filename))
        assert ok
    finally:
        db.close()


def test_backup_password_persists_on_edit(client):
    from app import crud, database

    login(client)
    # create an FTP job with a password
    token = _csrf(client, "/admin/system/backups")
    client.post(
        "/admin/system/backups/jobs",
        data={"name": "FTP", "active": "on", "schedule": "manual", "contents": ["database"],
              "target_type": "ftp", "ftp_host": "ftp.example.com", "ftp_username": "backupuser",
              "ftp_password": "secret", "retention_count": "5", "retention_days": "0",
              "csrf_token": token},
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        job = crud.get_backup_jobs(db)[0]
        assert job.ftp_password == "secret"
        job_id = job.id
    finally:
        db.close()
    # edit without re-entering the password -> kept
    token = _csrf(client, "/admin/system/backups")
    client.post(
        "/admin/system/backups/jobs",
        data={"job_id": str(job_id), "name": "FTP", "active": "on", "schedule": "manual",
              "contents": ["database"], "target_type": "ftp", "ftp_host": "ftp.example.com",
              "ftp_username": "backupuser", "ftp_password": "", "retention_count": "5",
              "retention_days": "0", "csrf_token": token},
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        assert crud.get_backup_job(db, job_id).ftp_password == "secret"
    finally:
        db.close()


def test_backup_connection_test_local_json(client):
    login(client)
    token = _csrf(client, "/admin/system/backups")
    response = client.post(
        "/admin/system/backups/test",
        data={"target_type": "local", "name": "x", "csrf_token": token},
        headers={"x-csrf-token": token},
    )
    body = response.json()
    assert body["ok"] is True


def test_backup_retention(client):
    from app import backup_manager, models, paths

    login(client)
    job = models.BackupJob(id=999, name="ret", target_type="local", contents="config",
                           retention_count=2, retention_days=0)
    # create several archives for this job id
    for _ in range(4):
        path, _w = backup_manager._build_archive(job, paths.DATA_DIR / "backups")
    removed = backup_manager.apply_retention(job)
    assert removed >= 1
    remaining = list((paths.DATA_DIR / "backups").glob(f"backup_job{job.id}_*.zip"))
    assert len(remaining) <= 2


def test_smb_unc_parsing():
    from app import backup_manager

    assert backup_manager._parse_unc(r"\\192.168.1.10\backup") == ("192.168.1.10", "backup", "")
    assert backup_manager._parse_unc(r"\\server\backup") == ("server", "backup", "")
    assert backup_manager._parse_unc(r"\\nas\firma\backups\daily") == ("nas", "firma", "backups\\daily")


def test_scheduler_due_logic():
    from datetime import datetime, timedelta
    from app import backup_scheduler, models

    now = datetime(2026, 6, 13, 12, 0, 0)
    daily_due = models.BackupJob(name="d", active=True, schedule="daily",
                                 last_run_at=now - timedelta(days=2))
    daily_fresh = models.BackupJob(name="d2", active=True, schedule="daily",
                                   last_run_at=now - timedelta(hours=1))
    manual = models.BackupJob(name="m", active=True, schedule="manual", last_run_at=None)
    never_run = models.BackupJob(name="n", active=True, schedule="weekly", last_run_at=None)
    inactive = models.BackupJob(name="i", active=False, schedule="daily", last_run_at=None)
    assert backup_scheduler.job_due(daily_due, now) is True
    assert backup_scheduler.job_due(daily_fresh, now) is False
    assert backup_scheduler.job_due(manual, now) is False
    assert backup_scheduler.job_due(never_run, now) is True
    assert backup_scheduler.job_due(inactive, now) is False


def test_password_not_logged(client):
    from app import backup_manager, models, paths

    login(client)
    job = models.BackupJob(name="ftp", target_type="ftp", ftp_host="localhost",
                           ftp_password="topsecret", contents="config")
    backup_manager.test_connection(job)
    for name in ("application.log", "audit.log", "error.log"):
        path = paths.LOGS_DIR / name
        if path.exists():
            assert "topsecret" not in path.read_text(encoding="utf-8")


def test_admin_nav_grouped(client):
    login(client)
    html = client.get("/admin/system/status").text
    assert 'class="adminnav"' in html
    for label in ("System", "Benutzer", "Zeiterfassung", "Sicherung", "Einstellungen"):
        assert ">" + label + "<" in html


def test_admin_nav_single_open_accordion(client):
    """0.9.3: nav closes other groups (closeOthers) and supports desktop hover."""
    login(client)
    html = client.get("/admin/system/status").text
    assert "closeOthers" in html
    assert "mouseenter" in html and "mouseleave" in html
    assert "(hover: hover) and (min-width: 769px)" in html


def test_backup_modal_scrollable_with_sticky_footer(client):
    """0.9.3: modal has a scrollable body and a sticky footer with all actions."""
    login(client)
    html = client.get("/admin/system/backups").text
    assert "modal__dialog--scroll" in html
    assert "modal__body" in html and "modal__foot" in html
    for action in ("Abbrechen", "Verbindung testen", "Speichern"):
        assert action in html


def test_backup_modal_css_max_height(client):
    """The scrollable dialog is capped to the viewport height."""
    from app import paths

    css = (paths.PROJECT_ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    assert ".modal__dialog--scroll" in css
    assert "max-height: 90vh" in css
