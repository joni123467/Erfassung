"""Tests für 0.20.3 – „Remote" verschwand, sobald eine Firma gewählt war.

**Der Fehler.** 0.20.1 machte „Remote" zu einem Arbeitsort für alle und entfernte
dafür das Attribut ``data-allow-remote`` aus der Vorlage. In ``static/app.js``
blieb aber die Abfrage ``picker.hasAttribute('data-allow-remote')`` stehen. Sie
lieferte ab da **immer** ``false``, und sobald eine Firma gewählt wurde, baute
das Skript die Einsatzortliste ohne „Remote" neu auf.

Betroffen war jeder Weg mit einer Firmenauswahl: „Auftrag starten" auf dem
Dashboard und in der Mobilansicht sowie „Zeitbuchung bearbeiten" in der
Administration.

**Warum die Tests aus 0.20.1 das nicht gefunden haben.** Sie prüften die
servergerenderte Antwort – und die war die ganze Zeit korrekt. Verloren ging die
Option erst im Browser, nachdem das Skript die Liste ersetzt hatte. Diese Datei
prüft deshalb **beide** Hälften des Vertrags: was der Server liefert und was das
Skript daraus baut.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from datetime import date, time

import pytest

import licensed_env

APP_JS = pathlib.Path("static/app.js")
COMPONENTS = pathlib.Path("templates/_components.html")


def _fresh_app(tmp_path, monkeypatch):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("ERFASSUNG_TIMEZONE", "Europe/Berlin")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    for key in ("DB_TYPE", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
                "DB_SSL", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]
    import app.main as main

    licensed_env.activate()
    return main


@pytest.fixture()
def main(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    module = _fresh_app(tmp_path, monkeypatch)
    with TestClient(module.app):
        pass
    return module


@pytest.fixture()
def client(main):
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
        yield test_client


_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _csrf(client, url: str) -> str:
    match = _CSRF_RE.search(client.get(url).text)
    assert match, f"kein CSRF-Token auf {url}"
    return match.group(1)


def _login(client) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "Admin!0000",
              "csrf_token": _csrf(client, "/login")},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _company_with_locations(name: str = "Müller GmbH") -> int:
    from app import crud, database, schemas

    with database.SessionLocal() as db:
        company = crud.create_company(
            db, schemas.CompanyCreate(name=name, description="", is_internal=False))
        crud.create_company_location(db, company.id, schemas.CompanyLocationCreate(
            name="Werk Nord", city="Kiel", is_primary=True))
        crud.create_company_location(db, company.id, schemas.CompanyLocationCreate(
            name="Werk Süd", city="Ulm"))
        return int(company.id)


def _pickers(html: str) -> list[str]:
    """Alle servergerenderten Einsatzort-Auswahlkästen einer Seite."""
    return re.findall(r'<select[^>]*name="work_location".*?</select>', html, re.S)


# ── 1. Das Skript darf „Remote" niemals wegoptimieren ─────────────────────


def test_script_has_no_attribute_gate_for_remote():
    """Genau der Fehler: eine Abfrage auf ein Attribut, das es nicht mehr gibt."""
    source = APP_JS.read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", source)      # Kommentare erklären den Fehler
    assert "data-allow-remote" not in code, (
        "static/app.js fragt noch ein Attribut ab, das die Vorlage seit 0.20.1 "
        "nicht mehr setzt – die Abfrage ist damit immer falsch"
    )
    assert "allowRemote" not in code


def test_script_always_offers_onsite_and_remote():
    """Die feste Liste, die ``fillPicker`` aufbaut, enthält beide Einträge."""
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"const fixed\s*=\s*(\[.*?\]\])", source, re.S)
    assert match, "die feste Optionsliste in fillPicker wurde nicht gefunden"
    # Aus dem JS-Literal eine Python-Liste machen: einfache zu doppelte
    # Anführungszeichen, dann als JSON lesen.
    fixed = json.loads(match.group(1).replace("'", '"'))
    values = {value for value, _label in fixed}
    labels = {label for _value, label in fixed}
    assert values == {"onsite", "remote"}, f"unerwartete Werte: {values}"
    assert labels == {"Vor Ort", "Remote"}, f"unerwartete Beschriftungen: {labels}"


def test_template_and_script_agree():
    """Server und Skript müssen dieselben festen Einträge liefern.

    Liefe das auseinander, sähe man die Option bis zur ersten Firmenwahl – und
    danach nicht mehr. Genau so hat sich der Fehler gezeigt.
    """
    template = COMPONENTS.read_text(encoding="utf-8")
    assert '<option value="onsite"' in template
    assert '<option value="remote"' in template
    assert "allow_remote" not in template, (
        "die Vorlage kennt kein Remote-Kennzeichen mehr (seit 0.20.1)"
    )


# ── 2. Servergerenderte Auswahl auf allen betroffenen Wegen ───────────────


def test_dashboard_pickers_offer_remote(client):
    _company_with_locations()
    _login(client)
    pickers = _pickers(client.get("/dashboard").text)
    assert pickers, "auf dem Dashboard steht keine Einsatzortauswahl"
    for index, picker in enumerate(pickers):
        assert ">Remote<" in picker, f"Auswahl #{index} ohne „Remote“"
        assert ">Vor Ort<" in picker, f"Auswahl #{index} ohne „Vor Ort“"


def test_order_modal_offers_remote(client):
    """„Auftrag starten" – der Weg aus der Fehlermeldung."""
    _company_with_locations()
    _login(client)
    html = client.get("/dashboard").text
    modal = html[html.index('id="order-modal"'):]
    modal = modal[: modal.index("</section>") if "</section>" in modal else len(modal)]
    pickers = _pickers(modal)
    assert pickers, "im Auftragsdialog steht keine Einsatzortauswahl"
    assert ">Remote<" in pickers[0]


def test_mobile_picker_offers_remote(client):
    _company_with_locations()
    _login(client)
    pickers = _pickers(client.get("/mobile").text)
    assert pickers, "in der Mobilansicht steht keine Einsatzortauswahl"
    for picker in pickers:
        assert ">Remote<" in picker


def test_time_entry_edit_form_offers_remote(client):
    """„Zeitbuchung bearbeiten" – der zweite Weg aus der Fehlermeldung."""
    from app import crud, database, models, schemas

    company_id = _company_with_locations()
    _login(client)
    with database.SessionLocal() as db:
        admin = crud.get_user_by_username(db, "admin")
        entry = crud.create_time_entry(db, schemas.TimeEntryCreate(
            user_id=admin.id, work_date=date(2026, 3, 10),
            start_time=time(8, 0), end_time=time(16, 0),
            company_id=company_id, status=models.TimeEntryStatus.APPROVED,
        ))
        entry_id = entry.id

    html = client.get(f"/admin/time-entries/{entry_id}/edit").text
    pickers = _pickers(html)
    assert pickers, "die Bearbeitungsmaske zeigt keine Einsatzortauswahl"
    assert ">Remote<" in pickers[0]
    assert ">Vor Ort<" in pickers[0]


def test_catalogue_is_delivered_wherever_a_picker_stands(client):
    """Ohne den Katalog kann das Skript die Standorte nicht nachtragen."""
    _company_with_locations()
    _login(client)
    for url in ("/dashboard", "/mobile"):
        html = client.get(url).text
        if _pickers(html):
            assert 'id="location-catalogue"' in html, f"{url}: Katalog fehlt"


def test_catalogue_lists_the_locations_of_the_company(client):
    """Der Katalog trägt genau die Standorte, die das Skript einsetzt."""
    _company_with_locations()
    _login(client)
    html = client.get("/dashboard").text
    raw = html[html.index('id="location-catalogue"'):]
    raw = raw[raw.index(">") + 1: raw.index("</script>")]
    catalogue = json.loads(raw)
    names = {entry["name"] for group in catalogue.values() for entry in group}
    assert {"Werk Nord", "Werk Süd"} <= names


# ── 3. Der Server nimmt „Remote" auf allen Wegen an ───────────────────────


def test_punch_with_company_accepts_remote(client):
    """Firma **und** Remote zusammen – der gemeldete Fall."""
    from app import crud, database

    company_id = _company_with_locations()
    _login(client)
    client.post(
        "/punch",
        data={"action": "start_company", "company_id": str(company_id),
              "work_location": "remote", "location_field": "1",
              "csrf_token": _csrf(client, "/dashboard"), "next_url": "/dashboard"},
        follow_redirects=False,
    )
    with database.SessionLocal() as db:
        admin = crud.get_user_by_username(db, "admin")
        entry = crud.get_open_time_entry(db, admin.id)
        assert entry is not None
        assert entry.is_remote is True
        assert entry.company_id == company_id
        assert entry.location_id is None, "Remote ist kein Firmenstandort"


def test_admin_edit_accepts_remote_with_a_company(client):
    from app import crud, database, models, schemas

    company_id = _company_with_locations()
    _login(client)
    with database.SessionLocal() as db:
        admin = crud.get_user_by_username(db, "admin")
        admin_id = admin.id
        entry = crud.create_time_entry(db, schemas.TimeEntryCreate(
            user_id=admin_id, work_date=date(2026, 3, 10),
            start_time=time(8, 0), end_time=time(16, 0),
            company_id=company_id, status=models.TimeEntryStatus.APPROVED,
        ))
        entry_id = entry.id

    url = f"/admin/time-entries/{entry_id}/edit"
    response = client.post(
        f"/admin/time-entries/{entry_id}/update",
        data={"csrf_token": _csrf(client, url), "user_id": str(admin_id),
              "work_date": "2026-03-10", "start_time": "08:00", "end_time": "16:00",
              "break_minutes": "0", "notes": "", "company_id": str(company_id),
              "work_location": "remote", "location_field": "1",
              "change_reason": "Test: nachträglich als Remote erfasst",
              "next_url": "/admin/reports/time"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with database.SessionLocal() as db:
        updated = crud.get_time_entry(db, entry_id)
        assert updated.is_remote is True
        assert updated.location_id is None


def test_a_company_location_still_wins_over_remote(client):
    """Die Gegenprobe: Ein gewählter Standort ist keine Remote-Arbeit."""
    from app import crud, database

    company_id = _company_with_locations()
    _login(client)
    with database.SessionLocal() as db:
        location_id = crud.get_company_locations(db, company_id, only_active=True)[0].id

    client.post(
        "/punch",
        data={"action": "start_company", "company_id": str(company_id),
              "work_location": str(location_id), "location_field": "1",
              "csrf_token": _csrf(client, "/dashboard"), "next_url": "/dashboard"},
        follow_redirects=False,
    )
    with database.SessionLocal() as db:
        admin = crud.get_user_by_username(db, "admin")
        entry = crud.get_open_time_entry(db, admin.id)
        assert entry is not None
        assert entry.location_id == location_id
        assert entry.is_remote is False


# ── Version ───────────────────────────────────────────────────────────────


def test_version_is_0203(client):
    assert client.app.version == "0.20.3"
    assert client.get("/health").json()["version"] == "0.20.3"
