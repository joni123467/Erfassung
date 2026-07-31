"""Regression tests for 0.10.1 – „Auftrag starten" bei laufender Arbeitszeit.

In der mobilen App stand „Auftrag starten" ausschließlich im Idle-Block. Bis
0.9.21 blieb dieser Block trotz ``hidden`` sichtbar (``display: grid``
überstimmte das Attribut), sodass der Knopf zufällig auch bei laufender
Arbeitszeit erreichbar war. Mit der korrekten Ausblendung in 0.9.22 verschwand
er – und damit die einzige Möglichkeit, mobil einen Auftrag zu starten oder zu
wechseln, während die Arbeitszeit läuft.
"""

from __future__ import annotations

import re
import sys

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


def _start_work(client):
    return client.post(
        "/punch",
        data={"csrf_token": _csrf(client, "/mobile"), "action": "start_work", "next_url": "/mobile"},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def _first_company_id():
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_companies(db)[0].id
    finally:
        db.close()


def _open_entry():
    from app import crud, database

    db = database.SessionLocal()
    try:
        user = crud.get_user_by_username(db, "admin")
        entry = crud.get_open_time_entry(db, user.id)
        return (entry.company.name if entry and entry.company else None) if entry else None
    finally:
        db.close()


# --- version -------------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.14.1"
    assert client.get("/health").json()["version"] == "0.14.1"


# --- der eigentliche Fehler ------------------------------------------------------

def _active_block(html: str) -> str:
    """Markup des Aktiv-Bereichs der Stempelaktionen."""
    return html.split('class="mobile-action-grid" data-state="active"')[1].split("</div>")[0]


def test_order_button_available_while_working(client):
    login(client)
    assert 'id="mobile-order-launch"' in client.get("/mobile").text  # Idle
    assert _start_work(client).json()["ok"]
    assert 'data-open="mobile-order-modal"' in _active_block(client.get("/mobile").text)


def test_order_button_still_available_when_idle(client):
    login(client)
    html = client.get("/mobile").text
    idle = html.split('class="mobile-action-grid" data-state="idle"')[1].split("</div>")[0]
    assert 'data-open="mobile-order-modal"' in idle


def test_offline_shell_offers_order_in_both_states(client):
    body = client.get("/static/mobile-offline-shell.html").text
    idle = body.split('class="mobile-action-grid" data-state="idle"')[1].split("</div>")[0]
    active = body.split('class="mobile-action-grid" data-state="active"')[1].split("</div>")[0]
    assert 'data-open="mobile-order-modal"' in idle
    assert 'data-open="mobile-order-modal"' in active


def test_start_order_while_working_switches_entry(client):
    """Fachlich unverändert: Der laufende Eintrag wird beendet und der Auftrag
    läuft weiter."""
    login(client)
    assert _start_work(client).json()["ok"]
    assert _open_entry() is None  # allgemeine Arbeitszeit, keine Firma

    response = client.post(
        "/punch",
        data={
            "csrf_token": _csrf(client, "/mobile"), "action": "start_company",
            "company_id": str(_first_company_id()), "next_url": "/mobile",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.json()["ok"] is True
    assert _open_entry() is not None


def test_desktop_dashboard_offers_order_in_both_states(client):
    """Auf dem Desktop war der Knopf schon immer in beiden Zuständen vorhanden –
    das bleibt so."""
    login(client)
    assert 'data-open="order-modal"' in client.get("/dashboard").text
    assert _start_work(client).json()["ok"]
    assert 'data-open="order-modal"' in client.get("/dashboard").text
