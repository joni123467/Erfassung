"""Tests für 0.13.0 – Standorte je Firma als Einsatzort.

Der Einsatzort war bis 0.12.x ein Boolean: Remote oder vor Ort. Wer bei drei
Kundenstandorten arbeitet, sah in der Auswertung dreimal dasselbe. Jetzt hat
jede Firma beliebig viele Standorte mit Anschrift, und eine Buchung zeigt auf
genau einen davon.

Drei Dinge, die dabei nicht kaputtgehen dürfen:

* **Bestandsdaten.** ``location_id = NULL`` verhält sich exakt wie bisher –
  ``is_remote`` entscheidet, die Anzeige liest sich unverändert.
* **Der gewohnte Umschalter.** Ohne gepflegte Standorte bleibt es beim
  Schalter „Remote / Vor Ort", nicht bei einer Liste mit zwei Einträgen.
* **Die Historie.** Ein gelöschter Standort nimmt seinen Namen nicht mit ins
  Grab – sonst verlöre eine zwei Jahre alte Buchung ihre Aussage.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

import pytest

import licensed_env


def _fresh_app(tmp_path, monkeypatch):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
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
    return _fresh_app(tmp_path, monkeypatch)


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
            admin.remote_flag_enabled = True
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
    token = _csrf(client, "/login")
    response = client.post(
        "/login",
        data={"username": "admin", "password": "Admin!0000", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _db():
    from app import database

    return database.SessionLocal()


def _company(name: str, *, internal: bool = False) -> int:
    from app import crud, schemas

    db = _db()
    try:
        company = crud.create_company(
            db, schemas.CompanyCreate(name=name, description="", is_internal=internal)
        )
        return int(company.id)
    finally:
        db.close()


def _location(company_id: int, name: str, **fields) -> int:
    from app import crud, schemas

    db = _db()
    try:
        location = crud.create_company_location(
            db, company_id, schemas.CompanyLocationCreate(name=name, **fields)
        )
        return int(location.id)
    finally:
        db.close()


def _clear_entries() -> None:
    """Alle Buchungen entfernen.

    Zwei Stempelungen im selben Test würden sonst in derselben Minute liegen
    und sich überschneiden – unter Last schlägt das zu, allein laufend nicht.
    """
    from app import models

    db = _db()
    try:
        db.query(models.TimeEntry).delete()
        db.commit()
    finally:
        db.close()


def _open_entry():
    from app import crud

    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        entry = crud.get_open_time_entry(db, admin.id)
        if entry is None:
            return None
        return {
            "location_id": entry.location_id,
            "label": entry.location_label,
            "address": entry.location_address,
            "is_remote": bool(entry.is_remote),
            "deleted_location_name": entry.deleted_location_name,
        }
    finally:
        db.close()


# --- Stammdaten ------------------------------------------------------------

def test_a_company_can_hold_several_locations(main):
    from app import crud

    company_id = _company("Müller GmbH")
    _location(company_id, "Werk Nord", city="Kiel")
    _location(company_id, "Werk Süd", city="Ulm")

    db = _db()
    try:
        locations = crud.get_company_locations(db, company_id)
        assert [item.name for item in locations] == ["Werk Nord", "Werk Süd"]
    finally:
        db.close()


def test_the_first_location_becomes_the_primary_one(main):
    """Sonst kostet jedes Einstempeln einen zusätzlichen Griff."""
    from app import crud

    company_id = _company("Müller GmbH")
    first = _location(company_id, "Werk Nord")
    second = _location(company_id, "Werk Süd")

    db = _db()
    try:
        company = crud.get_company(db, company_id)
        assert company.primary_location.id == first
        assert [item.id for item in company.active_locations][0] == first
        assert crud.get_company_location(db, second).is_primary is False
    finally:
        db.close()


def test_only_one_primary_location_per_company(main):
    from app import crud, schemas

    company_id = _company("Müller GmbH")
    first = _location(company_id, "Werk Nord")
    second = _location(company_id, "Werk Süd")

    db = _db()
    try:
        crud.update_company_location(
            db, second, schemas.CompanyLocationUpdate(name="Werk Süd", is_primary=True)
        )
        assert crud.get_company_location(db, first).is_primary is False
        assert crud.get_company_location(db, second).is_primary is True
    finally:
        db.close()


def test_a_closed_location_leaves_the_selection(main):
    """Deaktivieren statt löschen – Auswertungen bleiben vollständig."""
    from app import crud, schemas

    company_id = _company("Müller GmbH")
    location_id = _location(company_id, "Werk Nord")

    db = _db()
    try:
        crud.update_company_location(
            db, location_id, schemas.CompanyLocationUpdate(name="Werk Nord", is_active=False)
        )
        company = crud.get_company(db, company_id)
        assert company.active_locations == []
        assert len(company.locations) == 1
    finally:
        db.close()


def test_the_address_reads_as_one_line(main):
    from app import crud

    company_id = _company("Müller GmbH")
    location_id = _location(
        company_id, "Werk Nord", street="Hafenstr. 1", postal_code="24103", city="Kiel"
    )
    db = _db()
    try:
        location = crud.get_company_location(db, location_id)
        assert location.address_line == "Hafenstr. 1, 24103 Kiel"
        assert location.display_name == "Müller GmbH – Werk Nord"
    finally:
        db.close()

    leer = _location(company_id, "Ohne Anschrift")
    db = _db()
    try:
        assert crud.get_company_location(db, leer).address_line == ""
    finally:
        db.close()


# --- Auswahl beim Stempeln -------------------------------------------------

def test_without_locations_the_toggle_stays(client):
    """Der gewohnte Umschalter bleibt, solange nichts gepflegt ist."""
    _login(client)
    page = client.get("/dashboard").text
    assert 'name="is_remote"' in page
    assert 'name="work_location"' not in page


def test_quick_clocking_offers_only_remote_and_on_site(client):
    """Schnell stempeln kennt keine Standorte.

    Standorte gehören zu einer Firma. Ohne Auftrag gibt es keine Firma – und
    damit nichts auszuwählen. Dort bleibt es beim Umschalter.
    """
    company_id = _company("Müller GmbH")
    _location(company_id, "Werk Nord", city="Kiel")
    _login(client)
    page = client.get("/dashboard").text

    schnell = page[page.index("Schnell stempeln"):page.index("order-modal")]
    assert 'name="is_remote"' in schnell
    assert 'name="work_location"' not in schnell


def test_the_order_dialog_offers_the_list_in_the_same_shell(client):
    company_id = _company("Müller GmbH")
    _location(company_id, "Werk Nord", city="Kiel")
    _login(client)
    page = client.get("/dashboard").text

    assert 'name="work_location"' in page
    # Gleiche Pille, gleiche Beschriftung wie beim Umschalter.
    assert "location-toggle__face" in page
    assert "Einsatzort" in page
    assert ">Vor Ort<" in page and ">Remote<" in page
    # Ohne gewählte Firma steht noch kein Standort in der Liste; er kommt aus
    # dem Katalog, sobald die Firma feststeht.
    assert 'id="location-catalogue"' in page
    assert "Werk Nord" in page


def test_the_catalogue_is_grouped_by_company(client):
    """Grundlage für den Wechsel: je Firma genau ihre Standorte."""
    import json

    eins = _company("Müller GmbH")
    werk = _location(eins, "Werk Nord", city="Kiel")
    zwei = _company("Schmitz KG")
    lager = _location(zwei, "Lager Süd")

    _login(client)
    page = client.get("/dashboard").text
    raw = page.split('id="location-catalogue">')[1].split("</script>")[0]
    catalogue = json.loads(raw)

    assert [item["id"] for item in catalogue[str(eins)]] == [werk]
    assert [item["id"] for item in catalogue[str(zwei)]] == [lager]
    assert catalogue[str(eins)][0]["is_primary"] is True


def test_clocking_on_a_location_of_the_booked_company(client):
    company_id = _company("Müller GmbH")
    location_id = _location(company_id, "Werk Nord", city="Kiel", street="Hafenstr. 1",
                            postal_code="24103")
    _login(client)
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/punch",
        data={"action": "start_company", "company_id": str(company_id),
              "csrf_token": token, "work_location": str(location_id),
              "next_url": "/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    entry = _open_entry()
    assert entry["location_id"] == location_id
    assert entry["label"] == "Werk Nord"
    assert entry["address"] == "Hafenstr. 1, 24103 Kiel"
    assert entry["is_remote"] is False


def test_a_location_of_another_company_is_discarded(client):
    """Ein manipuliertes Formular darf keinen fremden Standort unterschieben."""
    kunde = _company("Müller GmbH")
    fremd = _company("Schmitz KG")
    fremder_standort = _location(fremd, "Lager Süd")

    _login(client)
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/punch",
        data={"action": "start_company", "company_id": str(kunde),
              "csrf_token": token, "work_location": str(fremder_standort),
              "next_url": "/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    entry = _open_entry()
    assert entry["location_id"] is None
    assert entry["label"] == "Vor Ort"


def test_quick_clocking_ignores_a_location(client):
    """Ohne Firma kein Standort – auch wenn das Feld mitgeschickt wird."""
    company_id = _company("Müller GmbH")
    location_id = _location(company_id, "Werk Nord")
    _login(client)
    token = _csrf(client, "/dashboard")
    client.post(
        "/punch",
        data={"action": "start_work", "csrf_token": token,
              "work_location": str(location_id), "next_url": "/dashboard"},
        follow_redirects=False,
    )
    entry = _open_entry()
    assert entry["location_id"] is None
    assert entry["is_remote"] is False


def test_remote_and_onsite_still_work(client):
    company_id = _company("Müller GmbH")
    _location(company_id, "Werk Nord")
    _login(client)

    token = _csrf(client, "/dashboard")
    client.post("/punch", data={"action": "start_work", "csrf_token": token,
                                "work_location": "remote", "next_url": "/dashboard"},
                follow_redirects=False)
    entry = _open_entry()
    assert entry["is_remote"] is True and entry["location_id"] is None
    assert entry["label"] == "Remote"

    _clear_entries()
    client.post("/punch", data={"action": "start_work", "csrf_token": token,
                                "work_location": "onsite", "next_url": "/dashboard"},
                follow_redirects=False)
    entry = _open_entry()
    assert entry["is_remote"] is False and entry["location_id"] is None
    assert entry["label"] == "Vor Ort"


def test_an_old_offline_action_without_the_field_still_counts(client):
    """Aus der Warteschlange vor dem Update kommt nur ``is_remote``."""
    company_id = _company("Müller GmbH")
    _location(company_id, "Werk Nord")
    _login(client)
    token = _csrf(client, "/dashboard")
    client.post(
        "/punch",
        data={"action": "start_work", "csrf_token": token, "is_remote": "1",
              "next_url": "/dashboard"},
        follow_redirects=False,
    )
    entry = _open_entry()
    assert entry["is_remote"] is True
    assert entry["location_id"] is None


def test_an_unknown_or_closed_location_falls_back_to_onsite(client):
    """Verworfen statt abgewiesen – eine Stempelung darf nie scheitern."""
    from app import crud, schemas

    company_id = _company("Müller GmbH")
    location_id = _location(company_id, "Werk Nord")
    db = _db()
    try:
        crud.update_company_location(
            db, location_id, schemas.CompanyLocationUpdate(name="Werk Nord", is_active=False)
        )
    finally:
        db.close()

    _login(client)
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/punch",
        data={"action": "start_company", "company_id": str(company_id),
              "csrf_token": token, "work_location": str(location_id),
              "next_url": "/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "error=" not in response.headers["location"]
    entry = _open_entry()
    assert entry["location_id"] is None and entry["is_remote"] is False

    _clear_entries()
    client.post("/punch",
                data={"action": "start_company", "company_id": str(company_id),
                      "csrf_token": token, "work_location": "99999",
                      "next_url": "/dashboard"},
                follow_redirects=False)
    assert _open_entry()["location_id"] is None


def test_the_own_locations_need_their_own_order(client):
    """Auch die eigenen Büros hängen an ihrer Firma.

    Vor 0.13.1 stand der eigene Betrieb überall zur Wahl. Das war bequem, aber
    falsch: Ein Standort gehört zu genau einer Firma, sonst landet er an einer
    Buchung, zu der er nicht passt.
    """
    kunde = _company("Müller GmbH")
    eigen = _company("Wir GmbH", internal=True)
    buero = _location(eigen, "Büro Hamburg")

    _login(client)
    token = _csrf(client, "/dashboard")
    client.post(
        "/punch",
        data={"action": "start_company", "company_id": str(kunde), "csrf_token": token,
              "work_location": str(buero), "next_url": "/dashboard"},
        follow_redirects=False,
    )
    assert _open_entry()["location_id"] is None

    _clear_entries()
    client.post(
        "/punch",
        data={"action": "start_company", "company_id": str(eigen), "csrf_token": token,
              "work_location": str(buero), "next_url": "/dashboard"},
        follow_redirects=False,
    )
    assert _open_entry()["location_id"] == buero


# --- Historie --------------------------------------------------------------

def test_a_deleted_location_keeps_its_name_on_the_booking(client):
    from app import crud

    company_id = _company("Müller GmbH")
    location_id = _location(company_id, "Werk Nord")
    _login(client)
    token = _csrf(client, "/dashboard")
    client.post("/punch",
                data={"action": "start_company", "company_id": str(company_id),
                      "csrf_token": token, "work_location": str(location_id),
                      "next_url": "/dashboard"},
                follow_redirects=False)

    db = _db()
    try:
        crud.delete_company_location(db, location_id)
    finally:
        db.close()

    entry = _open_entry()
    assert entry["location_id"] is None
    assert entry["deleted_location_name"] == "Werk Nord"
    assert entry["label"] == "Gelöscht (Werk Nord)"


def test_deleting_the_company_also_preserves_the_location_name(client):
    from app import crud

    company_id = _company("Müller GmbH")
    location_id = _location(company_id, "Werk Nord")
    _login(client)
    token = _csrf(client, "/dashboard")
    client.post("/punch",
                data={"action": "start_company", "company_id": str(company_id),
                      "csrf_token": token, "work_location": str(location_id),
                      "next_url": "/dashboard"},
                follow_redirects=False)

    db = _db()
    try:
        crud.delete_company(db, company_id)
    finally:
        db.close()

    entry = _open_entry()
    assert entry["deleted_location_name"] == "Werk Nord"


def test_the_primary_flag_moves_on_when_the_primary_is_deleted(main):
    from app import crud

    company_id = _company("Müller GmbH")
    first = _location(company_id, "Werk Nord")
    second = _location(company_id, "Werk Süd")

    db = _db()
    try:
        crud.delete_company_location(db, first)
        assert crud.get_company_location(db, second).is_primary is True
    finally:
        db.close()


# --- Stammdatenpflege über die Oberfläche ----------------------------------

def test_locations_can_be_managed_in_the_company_form(client):
    company_id = _company("Müller GmbH")
    _login(client)

    token = _csrf(client, f"/admin/companies/{company_id}")
    response = client.post(
        f"/admin/companies/{company_id}/locations/create",
        data={"name": "Werk Nord", "street": "Hafenstr. 1", "postal_code": "24103",
              "city": "Kiel", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get(f"/admin/companies/{company_id}").text
    assert "Werk Nord" in page and "Hafenstr. 1" in page


def test_a_location_without_a_name_is_refused(client):
    company_id = _company("Müller GmbH")
    _login(client)
    token = _csrf(client, f"/admin/companies/{company_id}")
    response = client.post(
        f"/admin/companies/{company_id}/locations/create",
        data={"name": "   ", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_a_location_of_another_company_is_not_editable(client):
    eins = _company("Müller GmbH")
    zwei = _company("Schmitz KG")
    location_id = _location(zwei, "Werk Süd")
    _login(client)
    token = _csrf(client, f"/admin/companies/{eins}")
    response = client.post(
        f"/admin/companies/{eins}/locations/{location_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    from app import crud

    db = _db()
    try:
        assert crud.get_company_location(db, location_id) is not None
    finally:
        db.close()


def test_the_own_company_is_marked_in_the_list(client):
    _company("Wir GmbH", internal=True)
    _login(client)
    page = client.get("/admin/companies").text
    assert "eigener Betrieb" in page


# --- Auswertungen, Exporte, Offline ----------------------------------------

def test_the_sync_payload_carries_locations(client):
    company_id = _company("Müller GmbH")
    location_id = _location(company_id, "Werk Nord", city="Kiel")
    _login(client)
    payload = client.get("/mobile/sync-data").json()
    entry = [item for item in payload["locations"] if item["id"] == location_id]
    assert entry and entry[0]["name"] == "Werk Nord"
    assert entry[0]["company_name"] == "Müller GmbH"
    assert entry[0]["is_primary"] is True


def test_the_export_column_appears_for_a_location(main):
    """Die Spalte „Ort" erschien bisher nur für Remote-Buchungen."""
    from app import pdf_export

    class _Entry:
        is_remote = False
        location_id = None
        deleted_location_name = None

    ohne = _Entry()
    assert pdf_export.any_remote([ohne]) is False

    mit = _Entry()
    mit.location_id = 7
    assert pdf_export.any_remote([mit]) is True

    geloescht = _Entry()
    geloescht.deleted_location_name = "Werk Nord"
    assert pdf_export.any_remote([geloescht]) is True


def test_the_booking_list_shows_the_location_name(client):
    company_id = _company("Müller GmbH")
    location_id = _location(company_id, "Werk Nord")
    _login(client)
    token = _csrf(client, "/dashboard")
    client.post("/punch",
                data={"action": "start_company", "company_id": str(company_id),
                      "csrf_token": token, "work_location": str(location_id),
                      "next_url": "/dashboard"},
                follow_redirects=False)
    client.post("/punch", data={"action": "end_work", "csrf_token": token,
                                "next_url": "/dashboard"}, follow_redirects=False)
    assert "Werk Nord" in client.get("/records").text


# --- Lizenz ----------------------------------------------------------------

def test_without_the_orders_module_there_are_no_locations(tmp_path, monkeypatch):
    """Standorte hängen an Firmen und damit am Baustein ``orders``."""
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]
    import app.main as main

    # Lizenz ohne „orders".
    licensed_env.activate(features=["vacation"])

    from fastapi.testclient import TestClient
    from app import crud, database, schemas, security

    with TestClient(main.app) as client:
        db = database.SessionLocal()
        admin = crud.get_user_by_username(db, "admin")
        admin.password_hash = security.hash_password("Admin!0000")
        admin.must_change_password = False
        admin.remote_flag_enabled = True
        company = crud.create_company(db, schemas.CompanyCreate(name="Müller GmbH"))
        company_id = int(company.id)
        crud.create_company_location(
            db, company_id, schemas.CompanyLocationCreate(name="Werk Nord")
        )
        db.commit()
        db.close()

        _login(client)
        page = client.get("/dashboard").text
        assert 'name="work_location"' not in page
        assert 'id="location-catalogue"' not in page
        assert 'name="is_remote"' in page
        assert main._location_catalogue(database.SessionLocal()) == {}
        assert main._locations_of(database.SessionLocal(), company_id) == []
