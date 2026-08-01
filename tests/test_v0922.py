"""Regression tests for 0.9.22 – Einsatzort als Umschalter statt Checkbox.

Der Einsatzort (0.9.21) wird nicht mehr als kleine Checkbox angeboten, sondern
als Schaltfläche, die Farbe und Beschriftung wechselt (Vor Ort ⇄ Remote). Das
Formularfeld bleibt eine Checkbox, damit die Offline-Warteschlange der PWA und
das Absenden ohne JavaScript unverändert funktionieren.
"""

from __future__ import annotations

import re
import sys
from datetime import date, time

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
        from app import crud, database, security

        db = database.SessionLocal()
        try:
            admin = crud.get_user_by_username(db, "admin")
            admin.password_hash = security.hash_password("Admin!0000")
            admin.must_change_password = False
            admin.remote_flag_enabled = True
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


DAY = date(2026, 8, 12)


def _admin_id() -> int:
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_user_by_username(db, "admin").id
    finally:
        db.close()


def _closed_entry(user_id, start, end, *, is_remote=False):
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        return crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=user_id, company_id=None, work_date=DAY,
                start_time=start, end_time=end, break_minutes=0,
                break_started_at=None, is_open=False, notes="Büro",
                status=models.TimeEntryStatus.APPROVED, is_manual=False,
                is_remote=is_remote,
            ),
        ).id
    finally:
        db.close()


# --- version -------------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.19.0"
    assert client.get("/health").json()["version"] == "0.19.0"


# --- Umschalter statt Checkbox --------------------------------------------------

@pytest.mark.parametrize("url", ["/dashboard", "/mobile"])
def test_toggle_replaces_checkbox(client, url):
    login(client)
    html = client.get(url).text
    assert "location-toggle" in html
    # Beide Beschriftungen liegen im Markup; die Umschaltung passiert per CSS.
    assert "Vor Ort" in html and "Remote" in html
    # Das Formularfeld bleibt eine Checkbox (Offline-Queue unverändert).
    assert 'type="checkbox" name="is_remote" value="1"' in html
    # Die alte, kleine Checkbox-Darstellung ist verschwunden.
    assert not re.search(r'class="[^"]*checkbox[^"]*"[^>]*>\s*<input[^>]*name="is_remote"', html)


def test_toggle_has_accessible_name(client):
    login(client)
    html = client.get("/mobile").text
    assert 'class="visually-hidden">Remote' in html
    assert 'class="location-toggle__face" aria-hidden="true"' in html


def test_admin_form_toggle_reflects_state(client):
    login(client)
    uid = _admin_id()
    on_site = _closed_entry(uid, time(8, 0), time(12, 0))
    remote = _closed_entry(uid, time(13, 0), time(15, 0), is_remote=True)

    html = client.get(f"/admin/time-entries/{on_site}/edit?next=/admin/reports/time&user={uid}").text
    assert "location-toggle" in html
    assert 'name="is_remote" value="1" checked' not in html

    html = client.get(f"/admin/time-entries/{remote}/edit?next=/admin/reports/time&user={uid}").text
    assert 'name="is_remote" value="1" checked' in html


def test_offline_shell_uses_toggle(client):
    """Die statische Offline-Shell zeigt denselben Umschalter."""
    body = client.get("/static/mobile-offline-shell.html").text
    assert body.count("location-toggle") >= 3
    assert not re.search(r'class="[^"]*checkbox[^"]*"[^>]*>\s*<input[^>]*name="is_remote"', body)


def test_hidden_attribute_wins_over_layout(client):
    """Ausgeblendete Bereiche (`hidden`) dürfen nicht durch display:flex/grid
    wieder sichtbar werden – sonst zeigt die mobile App Start- und Aktiv-Bereich
    gleichzeitig."""
    css = client.get("/static/styles.css").text
    assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important", css)


def test_styles_cover_both_states(client):
    css = client.get("/static/styles.css").text
    assert ".location-toggle__face" in css
    assert "input:checked + .visually-hidden + .location-toggle__face" in css
    assert ".location-toggle__text--on" in css


# --- Verhalten unverändert ------------------------------------------------------

def test_toggle_still_submits_the_flag(client):
    """Der Umschalter sendet weiterhin dasselbe Feld wie zuvor."""
    from app import database, models

    login(client)
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/punch",
        data={"csrf_token": token, "action": "start_work", "is_remote": "1",
              "next_url": "/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db = database.SessionLocal()
    try:
        entry = db.query(models.TimeEntry).filter(models.TimeEntry.user_id == _admin_id()).one()
        assert entry.is_remote is True
    finally:
        db.close()


def test_toggle_hidden_without_permission(client):
    from app import crud, database

    db = database.SessionLocal()
    try:
        crud.get_user_by_username(db, "admin").remote_flag_enabled = False
        db.commit()
    finally:
        db.close()

    login(client)
    for url in ("/dashboard", "/mobile"):
        html = client.get(url).text
        assert "location-toggle" not in html
