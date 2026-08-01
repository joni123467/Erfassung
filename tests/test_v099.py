"""Regression tests for 0.9.9 – Docker first-init, database-independent backups
and cross-database restore.

Covers: version bump, Docker ENV first-initialisation (config created + persisted
+ never overwritten), the ``created_by`` origin tracking and its banner, the
logical (database-independent) backup format with metadata + counts, the logical
export/import round-trip, cross-database restore acceptance (logical backup of a
*different* database type restored into the active backend without changing the
configuration), the legacy raw-snapshot rejection across types, and the restore
preview endpoint.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

import licensed_env


def _fresh_app(tmp_path, monkeypatch, env: dict | None = None):
    """(Re)import the application with a clean module state and given ENV."""
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    # Clear DB selectors so each test fully controls the resolution path.
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


def _make_backup(client) -> str:
    """Create + run a local backup job and return the newest archive file name."""
    from app import backup_manager, crud, database

    token = _csrf(client, "/admin/system/backups")
    client.post(
        "/admin/system/backups/jobs",
        data={"name": "Local", "active": "on", "schedule": "manual",
              "contents": ["database", "config"], "target_type": "local",
              "retention_count": "10", "retention_days": "0", "csrf_token": token},
        follow_redirects=False,
    )
    db = database.SessionLocal()
    try:
        job = crud.get_backup_jobs(db)[0]
    finally:
        db.close()
    token = _csrf(client, "/admin/system/backups")
    client.post(f"/admin/system/backups/jobs/{job.id}/run",
                data={"csrf_token": token}, follow_redirects=False)
    return Path(backup_manager.list_local_backups()[0]["path"]).name


# --- version ---------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.16.0"
    assert client.get("/health").json()["version"] == "0.16.0"


# --- Docker ENV first-initialisation ---------------------------------------

def test_env_first_init_creates_and_persists_config(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "app.db"
    main = _fresh_app(tmp_path, monkeypatch, {"DB_TYPE": "sqlite", "DB_PATH": str(db_path)})
    from fastapi.testclient import TestClient

    with TestClient(main.app):
        from app import database, app_config

        assert database.INIT_SOURCE == "env"
        # Config persisted with the env origin.
        cfg_file = tmp_path / "config" / "database.json"
        assert cfg_file.exists()
        stored = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert stored["type"] == "sqlite"
        assert stored["created_by"] == "env"
        cfg = app_config.load_database_config()
        assert cfg.created_by == "env"
        # database.log records the ENV initialisation + migrations.
        log = (tmp_path / "logs" / "database.log").read_text(encoding="utf-8")
        assert "ENV Initialisierung erkannt" in log
        assert "Migration erfolgreich (ENV-Erstinitialisierung)" in log


def test_env_does_not_overwrite_existing_config(tmp_path, monkeypatch):
    # Pre-existing configuration (as if created earlier via the web UI).
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    existing = tmp_path / "data" / "existing.db"
    (config_dir / "database.json").write_text(
        json.dumps({"type": "sqlite", "sqlite_path": str(existing), "created_by": "webinterface"}),
        encoding="utf-8",
    )
    # ENV asks for postgresql, but the existing config must win and be untouched.
    main = _fresh_app(tmp_path, monkeypatch, {
        "DB_TYPE": "postgresql", "DB_HOST": "db", "DB_NAME": "x",
        "DB_USER": "u", "DB_PASSWORD": "secret",
    })
    from fastapi.testclient import TestClient

    with TestClient(main.app):
        from app import database

        assert database.INIT_SOURCE == "file"
        assert database.DB_TYPE == "sqlite"
        stored = json.loads((config_dir / "database.json").read_text(encoding="utf-8"))
        assert stored["type"] == "sqlite"
        assert stored["created_by"] == "webinterface"


def test_env_config_never_exposes_password(tmp_path, monkeypatch):
    """§5: the only place a DB config is logged is ``describe()`` – it must never
    contain the password; ``safe_dict`` masks it for the UI.

    Imports only :mod:`app.database`/:mod:`app.app_config` (no full app start), so
    a server backend is resolved + persisted without attempting a connection.
    """
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    for key in ("DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_SSL", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DB_TYPE", "postgresql")
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "timetracking")
    monkeypatch.setenv("DB_USER", "timetracking")
    monkeypatch.setenv("DB_PASSWORD", "SuperSecret123")
    monkeypatch.setenv("DB_SSL", "false")
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]

    import app.database as database
    import app.app_config as app_config

    assert database.INIT_SOURCE == "env"
    cfg = app_config.load_database_config()
    assert cfg.created_by == "env" and cfg.type == "postgresql"
    assert "SuperSecret123" not in cfg.describe()
    assert cfg.safe_dict()["password"] == "***"
    stored = json.loads((tmp_path / "config" / "database.json").read_text(encoding="utf-8"))
    assert stored["created_by"] == "env"


def test_database_page_shows_init_source(client):
    login(client)
    html = client.get("/admin/system/database").text
    assert "Konfiguration erstellt durch" in html


# --- logical, database-independent backup ----------------------------------

def test_backup_is_logical_with_metadata(client):
    from app import backup_manager

    login(client)
    name = _make_backup(client)
    path = backup_manager.resolve_backup_path(name)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    assert "data/database.json" in names
    # No raw database file is the primary artefact (§8).
    assert not any(n.endswith("erfassung.db") or n.endswith(".sql") for n in names)
    meta = backup_manager.read_metadata(path)
    assert meta["app_version"] == "0.16.0"
    assert meta["backup_format_version"] == 1
    assert "users" in meta["counts"] and meta["counts"]["users"] >= 1


def test_logical_export_import_roundtrip(client):
    from app import data_transfer, database, models

    login(client)
    payload = data_transfer.export_database(database.engine)
    assert "tables" in payload and "users" in payload["tables"]

    db = database.SessionLocal()
    try:
        users_before = db.query(models.User).count()
        groups_before = db.query(models.Group).count()
    finally:
        db.close()

    imported = data_transfer.import_database(database.engine, payload)
    assert imported["users"] == users_before

    db = database.SessionLocal()
    try:
        assert db.query(models.User).count() == users_before
        assert db.query(models.Group).count() == groups_before
    finally:
        db.close()


# --- cross-database restore -------------------------------------------------

def _rewrite_backup_db_type(path: Path, new_type: str) -> Path:
    """Clone an archive but claim a different source database type in metadata."""
    cloned = path.with_name("crossdb_" + path.name)
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(cloned, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.namelist():
            data = src.read(item)
            if item == "backup_meta.json":
                meta = json.loads(data.decode("utf-8"))
                meta["database_type"] = new_type
                data = json.dumps(meta).encode("utf-8")
            dst.writestr(item, data)
    return cloned


def test_cross_database_logical_restore(client):
    """A logical backup labelled as PostgreSQL restores into the active SQLite
    backend without changing the database configuration (§10/§13)."""
    from app import backup_manager, crud, database, restore_manager, schemas

    login(client)
    name = _make_backup(client)
    src = backup_manager.resolve_backup_path(name)
    cross = _rewrite_backup_db_type(src, "postgresql")

    # validate_restore must accept the cross-type logical backup.
    ok, reason, _meta = restore_manager.validate_restore(cross)
    assert ok, reason

    # Mutate data after the backup; the restore must roll it back.
    db = database.SessionLocal()
    try:
        crud.create_company(db, schemas.CompanyCreate(name="AFTER_BACKUP"))
        admin = crud.get_user_by_username(db, "admin")
    finally:
        db.close()

    config_before = json.loads(
        (Path(client.tmp_path) / "config" / "database.json").read_text(encoding="utf-8")
    ) if (Path(client.tmp_path) / "config" / "database.json").exists() else None
    type_before = database.DB_TYPE

    result = restore_manager.restore_from_archive(cross, user=admin)
    assert result["status"] in {"success", "warning"}, result["message"]

    # Restore must never change the active database type/configuration (§10).
    assert database.DB_TYPE == type_before
    config_after = (Path(client.tmp_path) / "config" / "database.json")
    if config_before is not None:
        assert json.loads(config_after.read_text(encoding="utf-8")) == config_before

    db = database.SessionLocal()
    try:
        assert crud.get_company_by_name(db, "AFTER_BACKUP") is None
        runs = crud.get_restore_runs(db)
        assert runs and runs[0].status in {"success", "warning"}
    finally:
        db.close()


def test_cross_database_restore_logs(client):
    from app import backup_manager, crud, database, restore_manager, paths

    login(client)
    name = _make_backup(client)
    cross = _rewrite_backup_db_type(backup_manager.resolve_backup_path(name), "mariadb")
    db = database.SessionLocal()
    try:
        admin = crud.get_user_by_username(db, "admin")
    finally:
        db.close()
    restore_manager.restore_from_archive(cross, user=admin)
    db_log = (paths.LOGS_DIR / "database.log").read_text(encoding="utf-8")
    assert "Cross-Database Restore gestartet" in db_log
    assert "Cross-Database Restore erfolgreich" in db_log
    assert "Migration nach Restore erfolgreich" in db_log


# --- restore preview --------------------------------------------------------

def test_restore_preview_endpoint(client):
    login(client)
    name = _make_backup(client)
    token = _csrf(client, "/admin/system/restore")
    resp = client.post("/admin/system/restore/preview",
                       data={"file": name, "csrf_token": token})
    data = resp.json()
    assert data["ok"] is True
    assert data["backup"]["logical"] is True
    assert data["current"]["database_type"] == "sqlite"
    assert "unverändert" in data["note"]
    assert "users" in data["backup"]["counts"]
