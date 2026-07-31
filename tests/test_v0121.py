"""Tests für 0.12.1 – ohne Lizenz keine zubuchbare Funktion.

0.12.0 hat die Funktionsbausteine eingeführt, eine unlizenzierte Installation
aber bewusst offen gelassen. Das war widersprüchlich: Wer **keine** Lizenz
hatte, konnte mehr als wer eine ohne Bausteine hatte – die Lizenz war damit
folgenlos. Seit 0.12.1 entscheidet ausschließlich das Lizenzdokument.

Was sich **nicht** ändert: Die Basis bleibt in jedem Fall offen – Stempeln,
die eigene Zeitübersicht, die bereits angelegten Benutzer und die Sicherungen.
Eine Lizenzfrage darf keine Arbeitszeit kosten und keine Daten einsperren.

Die Tests decken beide Richtungen ab: Zubuchbares ist ohne gültige Lizenz zu
(auch bei abgelaufener und ungültiger), die Basis ist es nie.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote_plus

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_ID = "test-k1"


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private_key, public_pem


def _stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _sign(document: dict, private_key: Ed25519PrivateKey) -> dict:
    import base64

    payload = json.dumps(
        {k: v for k, v in document.items() if k != "signature"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    signed = dict(document)
    signed["signature"] = (
        base64.urlsafe_b64encode(private_key.sign(payload)).decode("ascii").rstrip("=")
    )
    return signed


def _document(private_key, deployment_id: str, *, features=None, max_users=25,
              expires_at=None) -> dict:
    return _sign(
        {
            "schema_version": 1,
            "license_id": "ERF-TEST-0001",
            "customer_name": "Muster GmbH",
            "product_id": "erfassung",
            "deployment_id": deployment_id,
            "edition": "standard",
            "features": sorted(features if features is not None else []),
            "max_users": max_users,
            "issued_at": _stamp(datetime.now(tz=timezone.utc)),
            "expires_at": _stamp(expires_at),
            "key_id": KEY_ID,
        },
        private_key,
    )


def _fresh_app(tmp_path, monkeypatch, public_pem: str):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    monkeypatch.setenv("ERFASSUNG_LICENSE_PUBLIC_KEYS", json.dumps({KEY_ID: public_pem}))
    for key in ("DB_TYPE", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
                "DB_SSL", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]
    import app.main as main

    return main


@pytest.fixture()
def keypair():
    return _keypair()


@pytest.fixture()
def main(tmp_path, monkeypatch, keypair):
    return _fresh_app(tmp_path, monkeypatch, keypair[1])


@pytest.fixture()
def licensing(main):
    from app import licensing as module

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
    token = _csrf(client, "/login")
    response = client.post(
        "/login",
        data={"username": "admin", "password": "Admin!0000", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _store(licensing, document: dict, **extra) -> None:
    config = licensing.load_config()
    values = {
        "deployment_id": config.deployment_id or licensing.deployment_id(),
        "server_url": "https://lizenz.example.org",
        "activation_key": "ERF-TEST-KEY-0001",
        "document": document,
        "activated_at": datetime.now(tz=timezone.utc).isoformat(),
        "last_checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "trusted_keys": config.trusted_keys,
    }
    values.update(extra)
    licensing.save_config(licensing.LicenseConfig(**values))


class _Response:
    """Minimale Antwort für die Zustandsabfrage."""

    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


GATED = [
    ("/admin/companies", "orders"),
    ("/admin/reports/time", "reports"),
    ("/admin/reports/users", "reports"),
    ("/admin/terminals", "terminals"),
    ("/records/vacations", "vacation"),
]

BASE = ["/dashboard", "/records", "/admin/users", "/admin/system/backups",
        "/admin/system/license"]


# --- Ohne Lizenz -----------------------------------------------------------

@pytest.mark.parametrize(("path", "feature"), GATED)
def test_unlicensed_closes_every_module(client, path, feature):
    _login(client)
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/dashboard")
    assert "nicht+enthalten" in response.headers["location"]


@pytest.mark.parametrize("path", BASE)
def test_unlicensed_keeps_the_base_open(client, path):
    """Die Basis hängt an keiner Lizenz – sonst ginge Arbeitszeit verloren."""
    _login(client)
    assert client.get(path, follow_redirects=False).status_code == 200


def test_unlicensed_api_answers_402(client):
    _login(client)
    response = client.get("/api/vacations")
    assert response.status_code == 402
    assert response.json()["feature"] == "vacation"


def test_the_user_excel_export_belongs_to_the_reports_module(main, client):
    """``/api/users`` ist Basis, der Excel-Export daraus aber eine Auswertung.

    Am Präfix ist das nicht zu erkennen – dafür gibt es ``PATTERNS``.
    """
    required = main.LicenseFeatureMiddleware.required_feature
    assert required("/api/users") is None
    assert required("/api/users/7") is None
    assert required("/api/users/7/excel") == "reports"

    _login(client)
    assert client.get("/api/users/1/excel").status_code == 402


def test_unlicensed_navigation_hides_the_modules(client):
    _login(client)
    page = client.get("/admin/users").text
    for path, _ in GATED:
        assert path not in page, path
    # Basis bleibt sichtbar, inklusive Weg zur Lizenz.
    assert "/admin/users" in page
    assert "/admin/system/license" in page


def test_unlicensed_hides_vacation_outside_the_admin_area(client):
    """Auch Buchungen, Dashboard und Mobilansicht führen nicht ins Leere.

    Diese Vorlagen haben keinen gemeinsamen Kontextaufbau; sie fragen über
    ``has_license_feature`` einzeln nach.
    """
    _login(client)
    assert "/records/vacations" not in client.get("/records").text
    assert "Urlaubsübersicht" not in client.get("/dashboard").text
    mobile = client.get("/mobile").text
    assert "mobile-panel-urlaub" not in mobile
    assert 'action="/vacations"' not in mobile


def test_licensed_vacation_appears_everywhere_again(client, licensing, keypair):
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["vacation"]))
    _login(client)
    assert "/records/vacations" in client.get("/records").text
    assert "Urlaubsübersicht" in client.get("/dashboard").text
    assert "mobile-panel-urlaub" in client.get("/mobile").text


def test_unlicensed_sync_payload_omits_vacations(client):
    """Die Offline-Shell soll gar nicht erst anbieten, was gesperrt ist."""
    _login(client)
    payload = client.get("/mobile/sync-data").json()
    assert payload["vacations"] == []
    assert payload["permissions"]["request_vacations"] is False
    assert payload["metrics"]["vacation_summary"] is None


def test_licensed_sync_payload_carries_vacations(client, licensing, keypair):
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["vacation"]))
    _login(client)
    payload = client.get("/mobile/sync-data").json()
    assert payload["permissions"]["request_vacations"] is True
    assert payload["metrics"]["vacation_summary"] is not None


def test_unlicensed_banner_names_the_consequence(client):
    _login(client)
    page = client.get("/admin/users").text
    assert "Nicht lizenziert" in page
    assert "gesperrt" in page
    assert "Stempeln" in page


def test_unlicensed_blocks_new_users(client):
    """Die Benutzerverwaltung bleibt offen, das Anlegen nicht."""
    _login(client)
    token = _csrf(client, "/admin/users/new")
    response = client.post(
        "/admin/users/create",
        data={
            "username": "neu",
            "full_name": "Neue Person",
            "email": "neu@example.org",
            "password": "Sicher!0000",
            "password_confirm": "Sicher!0000",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/admin/users/new" in response.headers["location"]
    assert "keine+Lizenz" in response.headers["location"]

    from app import crud, database

    db = database.SessionLocal()
    try:
        assert crud.get_user_by_username(db, "neu") is None
    finally:
        db.close()


def test_unlicensed_existing_users_keep_working(client):
    """Niemand wird ausgesperrt: Anmelden und Stempeln bleiben möglich."""
    _login(client)
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/punch",
        data={"action": "start_work", "csrf_token": token, "next_url": "/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "error=" not in response.headers["location"]

    from app import crud, database

    db = database.SessionLocal()
    try:
        admin = crud.get_user_by_username(db, "admin")
        assert crud.get_open_time_entry(db, admin.id) is not None
    finally:
        db.close()


# --- Auftragsbezogenes Stempeln --------------------------------------------

def _company(name: str = "Muster AG") -> int:
    from app import crud, database, schemas

    db = database.SessionLocal()
    try:
        company = crud.create_company(db, schemas.CompanyCreate(name=name, description=""))
        return int(company.id)
    finally:
        db.close()


def _open_entry_company(username: str = "admin"):
    from app import crud, database

    db = database.SessionLocal()
    try:
        user = crud.get_user_by_username(db, username)
        entry = crud.get_open_time_entry(db, user.id)
        return None if entry is None else entry.company_id
    finally:
        db.close()


def test_unlicensed_hides_order_clocking(client):
    """Stempeln ja, auf einen Auftrag stempeln nein."""
    _company()
    _login(client)
    for path in ("/dashboard", "/mobile"):
        page = client.get(path).text
        assert "Auftrag starten" not in page, path
        assert 'value="start_company"' not in page, path
        # Das reine Stempeln bleibt.
        assert 'value="start_work"' in page, path


def test_unlicensed_refuses_a_company_punch(client):
    """Auch der direkte Aufruf – die Oberfläche ist nur die halbe Miete."""
    company_id = _company()
    _login(client)
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/punch",
        data={
            "action": "start_company",
            "company_id": str(company_id),
            "csrf_token": token,
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "nicht+enthalten" in response.headers["location"]
    assert _open_entry_company() is None


def test_unlicensed_refuses_a_manual_entry_with_a_company(client):
    company_id = _company()
    _login(client)
    token = _csrf(client, "/dashboard")
    response = client.post(
        "/time",
        data={
            "work_date": "2026-07-01",
            "start_time": "08:00",
            "end_time": "16:00",
            "break_minutes": "30",
            "company_id": str(company_id),
            "csrf_token": token,
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "nicht+enthalten" in response.headers["location"]


def test_unlicensed_sync_payload_omits_companies(client):
    _company()
    _login(client)
    payload = client.get("/mobile/sync-data").json()
    assert payload["companies"] == []
    assert payload["permissions"]["create_companies"] is False


def test_a_running_order_can_still_be_ended(client, licensing, keypair):
    """Läuft die Lizenz mitten im Auftrag aus, bleibt „Auftrag beenden" offen.

    Sonst hinge die Buchung fest und es ginge Arbeitszeit verloren.
    """
    company_id = _company()
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["orders"]))
    _login(client)
    token = _csrf(client, "/dashboard")
    client.post(
        "/punch",
        data={
            "action": "start_company",
            "company_id": str(company_id),
            "csrf_token": token,
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert _open_entry_company() == company_id

    # Lizenz weg – der laufende Auftrag muss sich beenden lassen.
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=[]))
    response = client.post(
        "/punch",
        data={"action": "end_company", "csrf_token": token, "next_url": "/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "error=" not in response.headers["location"]
    assert _open_entry_company() is None


def test_licensed_orders_allow_clocking_on_a_company(client, licensing, keypair):
    company_id = _company()
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["orders"]))
    _login(client)
    assert "Auftrag starten" in client.get("/dashboard").text
    payload = client.get("/mobile/sync-data").json()
    assert company_id in [company["id"] for company in payload["companies"]]

    token = _csrf(client, "/dashboard")
    response = client.post(
        "/punch",
        data={
            "action": "start_company",
            "company_id": str(company_id),
            "csrf_token": token,
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "error=" not in response.headers["location"]
    assert _open_entry_company() == company_id


# --- Ungültig, abgelaufen, gesperrt ----------------------------------------

def test_an_expired_license_closes_the_modules(client, licensing, keypair):
    past = datetime.now(tz=timezone.utc) - timedelta(days=1)
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id(),
                  features=["vacation", "reports"], expires_at=past),
    )
    assert licensing.current_status().status == licensing.STATUS_EXPIRED

    _login(client)
    assert client.get("/records/vacations", follow_redirects=False).status_code == 303
    assert client.get("/dashboard", follow_redirects=False).status_code == 200


def test_an_invalid_license_closes_the_modules(client, licensing, keypair):
    """Ein Dokument für eine andere Installation schaltet nichts frei."""
    _store(
        licensing,
        _document(keypair[0], "fremde-installation", features=["vacation", "reports"]),
    )
    assert licensing.current_status().status == licensing.STATUS_INVALID

    _login(client)
    assert client.get("/records/vacations", follow_redirects=False).status_code == 303
    assert client.get("/dashboard", follow_redirects=False).status_code == 200


def test_a_valid_license_still_opens_what_it_names(client, licensing, keypair):
    """Gegenprobe – die Sperre trifft nur, was nicht lizenziert ist."""
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id(), features=["vacation"]),
    )
    _login(client)
    assert client.get("/records/vacations", follow_redirects=False).status_code == 200
    assert client.get("/admin/reports/time", follow_redirects=False).status_code == 303


# --- Einheiten -------------------------------------------------------------

def test_add_ons_are_available_only_with_a_valid_license(licensing, keypair):
    assert licensing.current_status().add_ons_available is False

    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["orders"]))
    state = licensing.current_status()
    assert state.add_ons_available is True
    assert state.has_feature("orders") is True
    assert state.has_feature("reports") is False


def test_a_block_past_its_grace_period_takes_the_modules_away(licensing, keypair):
    long_ago = datetime.now(tz=timezone.utc) - timedelta(
        days=licensing.GRACE_PERIOD_DAYS + 1
    )
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id(), features=["orders"]),
        blocked_status="suspended",
        blocked_since=long_ago.isoformat(),
        blocked_reason="gesperrt",
    )
    state = licensing.current_status()
    assert state.is_valid  # das Dokument selbst ist unverändert gültig
    assert state.add_ons_available is False
    assert state.has_feature("orders") is False


# --- Anzeige ---------------------------------------------------------------

def test_api_reports_what_is_actually_usable(client, licensing, keypair):
    """``features`` nennt das Dokument, ``feature_access`` die Wirklichkeit."""
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id(), features=["orders"]),
        blocked_status="revoked",
        blocked_since=(
            datetime.now(tz=timezone.utc) - timedelta(days=licensing.GRACE_PERIOD_DAYS + 1)
        ).isoformat(),
        blocked_reason="gesperrt",
    )
    _login(client)
    payload = client.get("/api/license").json()
    assert payload["features"] == ["orders"]
    assert payload["feature_access"] == {key: False for key in licensing.FEATURES}


def test_license_page_explains_the_lock(client):
    _login(client)
    page = client.get("/admin/system/license").text
    assert "Ohne gültige Lizenz ist kein zubuchbarer Bereich nutzbar" in page
    assert "nicht enthalten" in page


# --- Schneller nachfragen --------------------------------------------------

def test_the_default_interval_is_hourly(licensing):
    assert licensing.check_interval_minutes() == 60
    assert licensing.check_interval_label() == "1 Stunde"


def test_the_interval_is_configurable_but_bounded(licensing, monkeypatch):
    """Verstellbar für Betreiber – aber nie so eng, dass es zum Fluten wird."""
    monkeypatch.setenv(licensing.CHECK_INTERVAL_ENV, "15")
    assert licensing.check_interval_minutes() == 15
    assert licensing.check_interval_label() == "15 Minuten"

    monkeypatch.setenv(licensing.CHECK_INTERVAL_ENV, "180")
    assert licensing.check_interval_label() == "3 Stunden"

    # Untergrenze und Unsinn führen nie zu einem Fehler.
    monkeypatch.setenv(licensing.CHECK_INTERVAL_ENV, "0")
    assert licensing.check_interval_minutes() == licensing.MIN_CHECK_INTERVAL_MINUTES
    monkeypatch.setenv(licensing.CHECK_INTERVAL_ENV, "bald")
    assert licensing.check_interval_minutes() == licensing.DEFAULT_CHECK_INTERVAL_MINUTES


def test_a_check_is_due_again_after_an_hour(licensing, keypair):
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id()),
        last_contact_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    assert licensing.due_for_check() is False

    stale = datetime.now(tz=timezone.utc) - timedelta(minutes=61)
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id()),
        last_contact_at=stale.isoformat(),
    )
    assert licensing.due_for_check() is True


def test_the_scheduler_checks_once_on_startup(main, licensing, keypair, monkeypatch):
    """Ein Neustart fragt ungefragt nach – unabhängig vom Intervall."""
    from app import license_scheduler

    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id()),
        last_contact_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    assert licensing.due_for_check() is False  # regulär wäre nichts zu tun

    calls: list[int] = []
    monkeypatch.setattr(
        licensing, "refresh_from_server", lambda: (calls.append(1), (True, "ok"))[1]
    )
    monkeypatch.setattr(license_scheduler, "INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(license_scheduler, "WAKE_INTERVAL_SECONDS", 30)

    license_scheduler.start()
    try:
        deadline = time.monotonic() + 5
        while not calls and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        license_scheduler.stop()
    assert calls, "beim Start wurde nicht nachgefragt"


# --- Lizenz aktualisieren --------------------------------------------------

def test_refresh_button_applies_changes_at_once(client, licensing, keypair, monkeypatch):
    """Der Knopf holt das frische Dokument und nennt, was sich geändert hat."""
    deployment = licensing.deployment_id()
    _store(licensing, _document(keypair[0], deployment, features=[], max_users=5))
    assert licensing.has_feature("vacation") is False

    erweitert = _document(keypair[0], deployment, features=["vacation"], max_users=25)
    monkeypatch.setattr(
        licensing, "_post",
        lambda url, payload: _Response(200, {"status": "active", "license": erweitert}),
    )

    _login(client)
    token = _csrf(client, "/admin/system/license")
    response = client.post(
        "/admin/system/license/refresh",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "error=" not in location
    assert "Urlaubsplanung" in unquote_plus(location)
    assert "5" in unquote_plus(location) and "25" in unquote_plus(location)

    # Sofort wirksam, ohne Neustart und ohne Warten auf das Intervall.
    assert licensing.has_feature("vacation") is True
    assert client.get("/records/vacations", follow_redirects=False).status_code == 200


def test_refresh_button_keeps_the_license_when_the_server_is_down(
    client, licensing, keypair, monkeypatch
):
    """Der wichtigste Fall: Ausfall darf nie etwas wegnehmen."""
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["vacation"]))

    def boom(url, payload):
        raise licensing.LicenseError("Der Lizenzserver ist nicht erreichbar: timeout")

    monkeypatch.setattr(licensing, "_post", boom)

    _login(client)
    token = _csrf(client, "/admin/system/license")
    response = client.post(
        "/admin/system/license/refresh",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert "unver" in unquote_plus(response.headers["location"])  # „unverändert weiter“

    state = licensing.current_status()
    assert state.is_valid
    assert state.has_feature("vacation") is True


def test_refresh_reports_a_lifted_block(licensing, keypair, monkeypatch):
    deployment = licensing.deployment_id()
    _store(
        licensing,
        _document(keypair[0], deployment, features=["orders"]),
        blocked_status="suspended",
        blocked_since=(datetime.now(tz=timezone.utc) - timedelta(days=2)).isoformat(),
        blocked_reason="gesperrt",
    )
    fresh = _document(keypair[0], deployment, features=["orders"])
    monkeypatch.setattr(
        licensing, "_post",
        lambda url, payload: _Response(200, {"status": "active", "license": fresh}),
    )

    reached, message = licensing.refresh_now()
    assert reached is True
    assert "Sperre aufgehoben" in message
    assert licensing.current_status().is_blocked is False


def test_license_page_offers_the_refresh_button(client, licensing, keypair):
    _store(licensing, _document(keypair[0], licensing.deployment_id()))
    _login(client)
    page = client.get("/admin/system/license").text
    assert "Lizenz aktualisieren" in page
    assert "/admin/system/license/refresh" in page
    assert "bei jedem Start" in page
