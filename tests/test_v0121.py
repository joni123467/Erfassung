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
from datetime import datetime, timedelta, timezone

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
