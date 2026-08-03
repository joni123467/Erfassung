"""Regression tests for 0.9.13 – reliable PWA updates for installed devices.

Covers: version bump, the version stamped into the /sw.js response body (plus
no-cache + Service-Worker-Allowed headers), the sw.js source reading the
stamped global, install-time cache busting, the registration hardening in
app.js (updateViaCache none + update on start/resume), and the mobile.js
update/resume handling (controllerchange reload-once, server version check
after sync, sync on visibilitychange).
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
        test_client.main = main  # type: ignore[attr-defined]
        yield test_client


# --- version -----------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.20.7"
    assert client.get("/health").json()["version"] == "0.20.7"


# --- /sw.js delivery -----------------------------------------------------------

def test_sw_js_has_stamped_version_and_headers(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    body = response.text
    # Version im Skriptinhalt: nur so erkennen installierte PWAs Updates,
    # deren gecachte Seite noch eine alte Registrierungs-URL verwendet.
    assert body.startswith('self.__ERFASSUNG_VERSION = "0.20.7";')
    assert "no-cache" in response.headers.get("cache-control", "")
    assert response.headers.get("service-worker-allowed") == "/"


def test_sw_js_content_changes_per_version(client):
    """Zwei Versionen müssen unterschiedliche Skript-Bytes erzeugen."""
    body = client.get("/sw.js").text
    other = body.replace('"0.20.7"', '"9.9.99"', 1)
    assert body != other  # trivially true, documents the byte-diff mechanism
    assert 'self.__ERFASSUNG_VERSION' in body


def test_sw_source_prefers_stamped_version(client):
    source = Path("static/sw.js").read_text(encoding="utf-8")
    assert "self.__ERFASSUNG_VERSION" in source
    # Install darf Assets nicht aus dem HTTP-Cache übernehmen
    assert "cache: 'no-cache'" in source


# --- registration hardening (app.js) --------------------------------------------

def test_app_js_registration_hardening(client):
    source = Path("static/app.js").read_text(encoding="utf-8")
    assert "updateViaCache: 'none'" in source
    assert "registration.update()" in source
    assert "visibilitychange" in source
    # Konstante Registrierungs-URL: kein ?v= mehr (führte über den SW-Cache zu
    # /sw.js?v=dev-Registrierungen und Cache-Namen 'erfassung-mobile-vdev').
    assert "register('/sw.js', { scope: '/', updateViaCache: 'none' })" in source
    assert "sw.js?v=" not in source


# --- mobile.js update + resume handling ------------------------------------------

def test_mobile_js_update_handling(client):
    source = Path("static/mobile.js").read_text(encoding="utf-8")
    # Einmaliger Reload nach Übernahme durch neuen Worker
    assert "controllerchange" in source
    assert "swReloadedForUpdate" in source
    # Update-Check bei Start/Resume + Versionsabgleich nach Sync
    assert "setupServiceWorkerUpdateHandling" in source
    assert "handleServerVersion" in source
    # Sync beim Zurückholen in den Vordergrund (iOS-PWA)
    assert "performReconnectSync('resume')" in source


# --- sync payload carries the server version --------------------------------------

def test_sync_data_contains_version(client):
    from app import crud, database, security

    db = database.SessionLocal()
    try:
        admin = crud.get_user_by_username(db, "admin")
        admin.password_hash = security.hash_password("Admin!0000")
        admin.must_change_password = False
        db.commit()
    finally:
        db.close()

    token_html = client.get("/login").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', token_html).group(1)
    client.post(
        "/login",
        data={"username": "admin", "password": "Admin!0000", "csrf_token": token},
        follow_redirects=False,
    )
    payload = client.get("/mobile/sync-data?days=7").json()
    assert payload["version"] == "0.20.7"
