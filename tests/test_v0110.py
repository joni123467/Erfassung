"""Tests für 0.11.0 – Lizenzierung gegen den Erfassung-Lizenzserver.

Abgedeckt sind die drei Bausteine der Integration:

* **Deployment-ID** – dauerhaft, zufällig, ohne Hardware- oder Personenbezug.
* **Offline-Prüfung** – Signatur, Produkt, Deployment-ID, Ablauf und
  Dokumentversion; ein manipuliertes Dokument wird nie akzeptiert.
* **Aktivierung** – Antworten des Lizenzservers werden in verständliche
  Meldungen übersetzt, und ein unbrauchbares Dokument landet nie auf der Platte.

Dazu die Durchsetzung (Benutzerobergrenze), die Oberfläche und die Zusage,
dass der Aktivierungsschlüssel weder in der Oberfläche noch im Protokoll noch
im Einstellungsexport im Klartext auftaucht.
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


# --- Hilfsmittel -----------------------------------------------------------

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
    """Signieren exakt wie der Lizenzserver – kanonisches JSON ohne ``signature``."""
    import base64

    payload = json.dumps(
        {k: v for k, v in document.items() if k != "signature"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    signature = private_key.sign(payload)
    signed = dict(document)
    signed["signature"] = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return signed


def _document(
    private_key: Ed25519PrivateKey,
    deployment_id: str,
    *,
    max_users: int = 5,
    expires_at: datetime | None = None,
    product_id: str = "erfassung",
    schema_version: int = 1,
    features: list[str] | None = None,
) -> dict:
    return _sign(
        {
            "schema_version": schema_version,
            "license_id": "ERF-TEST-0001",
            "customer_name": "Muster GmbH",
            "product_id": product_id,
            "deployment_id": deployment_id,
            "edition": "standard",
            "features": features if features is not None else ["reports"],
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
    _, public_pem = keypair
    return _fresh_app(tmp_path, monkeypatch, public_pem)


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
    assert response.status_code in (302, 303), response.text


class _Response:
    """Minimale Antwort für den nachgebildeten Lizenzserver."""

    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _stub_server(
    licensing,
    monkeypatch,
    response: _Response,
    calls: list | None = None,
    *,
    public_pem: str | None = None,
    key_id: str = KEY_ID,
):
    """Lizenzserver nachbilden: Prüfschlüssel-Abruf und Aktivierung."""

    def fake_post(url: str, payload: dict):
        if calls is not None:
            calls.append((url, payload))
        return response

    def fake_fetch(server_url: str) -> dict:
        if public_pem is None:
            raise AssertionError("Test muss public_pem angeben")
        return {key_id: public_pem}

    monkeypatch.setattr(licensing, "_post", fake_post)
    monkeypatch.setattr(licensing, "fetch_public_keys", fake_fetch)


# --- Deployment-ID ---------------------------------------------------------

def test_deployment_id_is_stable_and_random(licensing):
    first = licensing.deployment_id()
    second = licensing.deployment_id()
    assert first == second
    assert first.startswith("erfassung-")
    # Muster und Länge, die der Lizenzserver akzeptiert (16–128 Zeichen).
    assert re.fullmatch(r"[a-zA-Z0-9._:-]{16,128}", first)


def test_deployment_id_contains_no_host_information(licensing):
    import socket

    value = licensing.deployment_id().lower()
    for marker in (socket.gethostname().lower(), "mac", "serial"):
        if marker:
            assert marker not in value


def test_license_file_is_only_readable_by_owner(licensing):
    licensing.deployment_id()
    from app import paths

    mode = (paths.CONFIG_DIR / "license.json").stat().st_mode & 0o777
    assert mode == 0o600


# --- Offline-Prüfung -------------------------------------------------------

def _store(licensing, document: dict, *, key: str = "ERF-TEST-KEY-0001") -> None:
    config = licensing.load_config()
    licensing.save_config(
        licensing.LicenseConfig(
            deployment_id=config.deployment_id or licensing.deployment_id(),
            server_url="https://lizenz.example.org",
            activation_key=key,
            document=document,
            activated_at=datetime.now(tz=timezone.utc).isoformat(),
            last_checked_at=datetime.now(tz=timezone.utc).isoformat(),
        )
    )


def test_valid_document_is_accepted(licensing, keypair):
    private_key, _ = keypair
    _store(licensing, _document(private_key, licensing.deployment_id(), max_users=7))
    state = licensing.current_status()
    assert state.status == licensing.STATUS_VALID
    assert state.is_valid
    assert state.max_users == 7
    assert state.license_id == "ERF-TEST-0001"
    assert state.features == ["reports"]


def test_tampered_document_is_rejected(licensing, keypair):
    private_key, _ = keypair
    document = _document(private_key, licensing.deployment_id(), max_users=5)
    document["max_users"] = 500  # nachträglich erhöht, Signatur bleibt alt
    _store(licensing, document)
    state = licensing.current_status()
    assert state.status == licensing.STATUS_INVALID
    assert "Signatur" in state.reason


def test_document_signed_with_unknown_key_is_rejected(licensing):
    other_key, _ = _keypair()
    _store(licensing, _document(other_key, licensing.deployment_id()))
    assert licensing.current_status().status == licensing.STATUS_INVALID


def test_document_for_other_installation_is_rejected(licensing, keypair):
    private_key, _ = keypair
    _store(licensing, _document(private_key, "erfassung-" + "0" * 32))
    state = licensing.current_status()
    assert state.status == licensing.STATUS_INVALID
    assert "andere Installation" in state.reason


def test_document_for_other_product_is_rejected(licensing, keypair):
    private_key, _ = keypair
    _store(
        licensing,
        _document(private_key, licensing.deployment_id(), product_id="etwas-anderes"),
    )
    assert licensing.current_status().status == licensing.STATUS_INVALID


def test_unsupported_schema_version_is_rejected(licensing, keypair):
    private_key, _ = keypair
    _store(licensing, _document(private_key, licensing.deployment_id(), schema_version=99))
    state = licensing.current_status()
    assert state.status == licensing.STATUS_INVALID
    assert "aktualisieren" in state.reason


def test_expired_document_is_reported_as_expired(licensing, keypair):
    private_key, _ = keypair
    past = datetime.now(tz=timezone.utc) - timedelta(days=1)
    _store(licensing, _document(private_key, licensing.deployment_id(), expires_at=past))
    state = licensing.current_status()
    assert state.status == licensing.STATUS_EXPIRED
    assert state.days_until_expiry is not None and state.days_until_expiry < 0


def test_expiry_warning_window(licensing, keypair):
    private_key, _ = keypair
    soon = datetime.now(tz=timezone.utc) + timedelta(days=10)
    _store(licensing, _document(private_key, licensing.deployment_id(), expires_at=soon))
    state = licensing.current_status()
    assert state.is_valid
    assert state.expires_soon


def test_without_license_the_status_is_unlicensed(licensing):
    state = licensing.current_status()
    assert state.status == licensing.STATUS_UNLICENSED
    assert not state.is_configured


def test_canonical_json_matches_the_license_server_rules(licensing):
    # Sortierte Schlüssel, keine Leerzeichen, Umlaute unescaped.
    raw = licensing.canonical_json({"b": 1, "a": "Ü"})
    assert raw == '{"a":"Ü","b":1}'.encode("utf-8")
    # Die Signatur deckt das Dokument ohne das Feld ``signature`` ab.
    assert b"signature" not in licensing.signing_payload({"a": 1, "signature": "x"})


def test_has_feature_requires_a_valid_license(licensing, keypair):
    private_key, _ = keypair
    assert licensing.has_feature("reports") is False
    _store(licensing, _document(private_key, licensing.deployment_id(), features=["reports"]))
    assert licensing.has_feature("reports") is True
    assert licensing.has_feature("unbekannt") is False


# --- Aktivierung -----------------------------------------------------------

def test_activation_stores_the_signed_document(licensing, keypair, monkeypatch):
    private_key, _ = keypair
    deployment = licensing.deployment_id()
    document = _document(private_key, deployment, max_users=3)
    calls: list = []
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": document}), calls,
        public_pem=keypair[1],
    )

    state = licensing.activate("lizenz.example.org", " ERF-TEST-KEY-0001 ")

    assert state.status == licensing.STATUS_VALID
    url, payload = calls[0]
    assert url == "https://lizenz.example.org/v1/activations"  # https wird ergänzt
    assert payload["deployment_id"] == deployment
    assert payload["product_id"] == "erfassung"
    assert payload["activation_key"] == "ERF-TEST-KEY-0001"  # getrimmt
    stored = licensing.load_config()
    assert stored.document == document
    assert stored.server_url == "https://lizenz.example.org"


def test_activation_rejects_an_unusable_document_without_storing_it(
    licensing, keypair, monkeypatch
):
    private_key, _ = keypair
    # Dokument für eine fremde Installation – darf nie gespeichert werden.
    document = _document(private_key, "erfassung-" + "1" * 32)
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": document}),
        public_pem=keypair[1],
    )

    with pytest.raises(licensing.LicenseError):
        licensing.activate("https://lizenz.example.org", "ERF-TEST-KEY-0001")

    assert licensing.load_config().document == {}


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (403, "abgelehnt"),
        (429, "Zu viele"),
        (422, "ungültige Eingabe"),
        (500, "HTTP 500"),
    ],
)
def test_activation_errors_are_translated(
    licensing, keypair, monkeypatch, status_code, expected
):
    _stub_server(licensing, monkeypatch, _Response(status_code), public_pem=keypair[1])
    with pytest.raises(licensing.LicenseError) as excinfo:
        licensing.activate("https://lizenz.example.org", "ERF-TEST-KEY-0001")
    assert expected in str(excinfo.value)


def test_activation_requires_a_key(licensing):
    with pytest.raises(licensing.LicenseError):
        licensing.activate("https://lizenz.example.org", "   ")


def test_unreachable_server_yields_a_clear_message(licensing, monkeypatch):
    """Der echte HTTP-Pfad läuft mit; nur der Transport schlägt fehl."""
    import httpx

    def boom(self, url, **kwargs):
        raise httpx.ConnectError("Name or service not known")

    monkeypatch.setattr(httpx.Client, "post", boom)
    with pytest.raises(licensing.LicenseError) as excinfo:
        licensing.activate("https://lizenz.example.invalid", "ERF-TEST-KEY-0001")
    assert "nicht erreichbar" in str(excinfo.value)


def test_recheck_reuses_the_stored_credentials(licensing, keypair, monkeypatch):
    private_key, _ = keypair
    deployment = licensing.deployment_id()
    _store(licensing, _document(private_key, deployment))
    calls: list = []
    _stub_server(
        licensing,
        monkeypatch,
        _Response(200, {"license": _document(private_key, deployment, max_users=9)}),
        calls,
        public_pem=keypair[1],
    )

    state = licensing.recheck()

    assert state.max_users == 9
    assert calls[0][1]["activation_key"] == "ERF-TEST-KEY-0001"


def test_recheck_without_stored_credentials_fails_clearly(licensing):
    with pytest.raises(licensing.LicenseError) as excinfo:
        licensing.recheck()
    assert "erneut aktivieren" in str(excinfo.value)


def test_deactivate_keeps_the_deployment_id(licensing, keypair, monkeypatch):
    private_key, _ = keypair
    deployment = licensing.deployment_id()
    _store(licensing, _document(private_key, deployment))
    calls: list = []
    _stub_server(licensing, monkeypatch, _Response(204), calls)

    licensing.deactivate()

    assert calls[0][0].endswith("/v1/activations/deactivate")
    config = licensing.load_config()
    assert config.deployment_id == deployment
    assert config.document == {}
    assert config.activation_key == ""


def test_deactivate_works_even_if_the_server_is_down(licensing, keypair, monkeypatch):
    private_key, _ = keypair
    _store(licensing, _document(private_key, licensing.deployment_id()))

    def boom(url: str, payload: dict):
        raise licensing.LicenseError("nicht erreichbar")

    monkeypatch.setattr(licensing, "_post", boom)
    licensing.deactivate()
    assert licensing.load_config().document == {}


# --- Prüfschlüssel: Übernahme beim ersten Kontakt --------------------------

def test_activation_adopts_the_servers_public_key(licensing, keypair, monkeypatch):
    """Ohne eingebetteten Schlüssel übernimmt die Installation den des Servers."""
    private_key, public_pem = keypair
    monkeypatch.delenv("ERFASSUNG_LICENSE_PUBLIC_KEYS", raising=False)
    assert licensing.embedded_public_keys() == {}

    document = _document(private_key, licensing.deployment_id())
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": document}), public_pem=public_pem
    )
    state = licensing.activate("https://lizenz.example.org", "ERF-TEST-KEY-0001")

    assert state.is_valid
    assert licensing.load_config().trusted_keys == {KEY_ID: public_pem}
    # Und die Offline-Prüfung kommt danach ohne Server aus.
    assert licensing.current_status().is_valid


def test_adopted_key_is_never_silently_replaced(licensing, keypair, monkeypatch):
    """Ein Serverwechsel mit anderem Schlüssel wird abgewiesen, nicht übernommen."""
    private_key, public_pem = keypair
    monkeypatch.delenv("ERFASSUNG_LICENSE_PUBLIC_KEYS", raising=False)
    document = _document(private_key, licensing.deployment_id())
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": document}), public_pem=public_pem
    )
    licensing.activate("https://lizenz.example.org", "ERF-TEST-KEY-0001")

    # Ein Angreifer gibt sich unter derselben key_id mit eigenem Schlüssel aus.
    other_private, other_public = _keypair()
    forged = _document(other_private, licensing.deployment_id(), max_users=9999)
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": forged}), public_pem=other_public
    )
    with pytest.raises(licensing.LicenseError) as excinfo:
        licensing.activate("https://lizenz.example.org", "ERF-TEST-KEY-0001")
    assert "anderen" in str(excinfo.value)

    # Nichts wurde überschrieben: alte Lizenz, alter Schlüssel.
    assert licensing.load_config().trusted_keys == {KEY_ID: public_pem}
    assert licensing.current_status().max_users == 5


def test_key_rotation_via_a_new_key_id_is_accepted(licensing, keypair, monkeypatch):
    """Echte Rotation läuft über eine neue key_id – die wird ergänzt."""
    private_key, public_pem = keypair
    monkeypatch.delenv("ERFASSUNG_LICENSE_PUBLIC_KEYS", raising=False)
    document = _document(private_key, licensing.deployment_id())
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": document}), public_pem=public_pem
    )
    licensing.activate("https://lizenz.example.org", "ERF-TEST-KEY-0001")

    new_private, new_public = _keypair()
    rotated = _sign(
        {
            **{k: v for k, v in document.items() if k != "signature"},
            "key_id": "k2",
            "max_users": 50,
        },
        new_private,
    )
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": rotated}),
        public_pem=new_public, key_id="k2",
    )
    state = licensing.activate("https://lizenz.example.org", "ERF-TEST-KEY-0001")

    assert state.max_users == 50
    trusted = licensing.load_config().trusted_keys
    assert trusted == {KEY_ID: public_pem, "k2": new_public}


def test_embedded_key_wins_over_an_offered_one(licensing, keypair, monkeypatch):
    """Liefert der Herausgeber einen Schlüssel mit, ist er maßgeblich."""
    _, public_pem = keypair  # steckt via Fixture in ERFASSUNG_LICENSE_PUBLIC_KEYS
    other_private, other_public = _keypair()
    forged = _document(other_private, licensing.deployment_id())
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": forged}), public_pem=other_public
    )
    with pytest.raises(licensing.LicenseError):
        licensing.activate("https://lizenz.example.org", "ERF-TEST-KEY-0001")


def test_fingerprint_matches_the_license_server_format(licensing):
    pem = "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n"
    value = licensing.fingerprint(pem)
    assert re.fullmatch(r"SHA256:[0-9A-F]{4}(:[0-9A-F]{4}){3}", value)
    assert licensing.fingerprint(pem + "\n") == value


def test_status_reports_the_fingerprint(licensing, keypair):
    private_key, public_pem = keypair
    _store(licensing, _document(private_key, licensing.deployment_id()))
    state = licensing.current_status()
    assert state.key_fingerprint == licensing.fingerprint(public_pem)


def test_license_page_shows_the_fingerprint(client, licensing, keypair):
    private_key, public_pem = keypair
    _store(licensing, _document(private_key, licensing.deployment_id()))
    _login(client)
    page = client.get("/admin/system/license")
    assert licensing.fingerprint(public_pem) in page.text


def test_unreachable_key_endpoint_aborts_before_storing(licensing, monkeypatch):
    import httpx

    def boom(self, url, **kwargs):
        raise httpx.ConnectError("Name or service not known")

    monkeypatch.setattr(httpx.Client, "get", boom)
    with pytest.raises(licensing.LicenseError) as excinfo:
        licensing.activate("https://lizenz.example.invalid", "ERF-TEST-KEY-0001")
    assert "nicht erreichbar" in str(excinfo.value)
    assert licensing.load_config().document == {}


def test_deactivate_keeps_the_trusted_keys(licensing, keypair, monkeypatch):
    """Der Prüfschlüssel ist kein Geheimnis – aber sein Wechsel muss auffallen."""
    private_key, public_pem = keypair
    monkeypatch.delenv("ERFASSUNG_LICENSE_PUBLIC_KEYS", raising=False)
    document = _document(private_key, licensing.deployment_id())
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": document}), public_pem=public_pem
    )
    licensing.activate("https://lizenz.example.org", "ERF-TEST-KEY-0001")

    _stub_server(licensing, monkeypatch, _Response(204), public_pem=public_pem)
    licensing.deactivate()

    config = licensing.load_config()
    assert config.document == {}
    assert config.trusted_keys == {KEY_ID: public_pem}


# --- Durchsetzung ----------------------------------------------------------

def _db():
    from app import database

    return database.SessionLocal()


def test_no_license_does_not_block_anything(licensing, main):
    db = _db()
    try:
        assert licensing.user_limit_error(db) is None
    finally:
        db.close()


def test_user_limit_is_enforced(licensing, client, keypair):
    """``client`` sorgt für den gesäten Admin – ohne Benutzer gäbe es nichts zu begrenzen."""
    private_key, _ = keypair
    db = _db()
    try:
        existing = licensing.count_users(db)
        assert existing >= 1
        _store(licensing, _document(private_key, licensing.deployment_id(), max_users=existing))
        message = licensing.user_limit_error(db)
        assert message and "erlaubt" in message
        # Ein Platz mehr genügt wieder.
        _store(
            licensing,
            _document(private_key, licensing.deployment_id(), max_users=existing + 1),
        )
        assert licensing.user_limit_error(db) is None
    finally:
        db.close()


def test_max_users_zero_means_unlimited(licensing, main, keypair):
    private_key, _ = keypair
    db = _db()
    try:
        _store(licensing, _document(private_key, licensing.deployment_id(), max_users=0))
        state = licensing.current_status(db)
        assert state.unlimited_users
        assert state.users_remaining is None
        assert licensing.user_limit_error(db) is None
    finally:
        db.close()


def test_expired_license_blocks_new_users(licensing, main, keypair):
    private_key, _ = keypair
    past = datetime.now(tz=timezone.utc) - timedelta(days=1)
    _store(licensing, _document(private_key, licensing.deployment_id(), expires_at=past))
    db = _db()
    try:
        message = licensing.user_limit_error(db)
        assert message and "abgelaufen" in message
    finally:
        db.close()


def test_html_user_creation_is_blocked_at_the_limit(client, licensing, keypair):
    private_key, _ = keypair
    db = _db()
    try:
        _store(
            licensing,
            _document(private_key, licensing.deployment_id(), max_users=licensing.count_users(db)),
        )
    finally:
        db.close()
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
    assert "erlaubt" in response.headers["location"]

    from app import crud, database

    db = database.SessionLocal()
    try:
        assert crud.get_user_by_username(db, "neu") is None
    finally:
        db.close()


def test_api_user_creation_is_blocked_at_the_limit(client, licensing, keypair):
    private_key, _ = keypair
    db = _db()
    try:
        _store(
            licensing,
            _document(private_key, licensing.deployment_id(), max_users=licensing.count_users(db)),
        )
    finally:
        db.close()
    _login(client)
    response = client.post(
        "/api/users",
        json={
            "username": "neu2",
            "full_name": "Noch Jemand",
            "email": "neu2@example.org",
            "password": "Sicher!0000",
        },
        headers={"x-csrf-token": _csrf(client, "/dashboard")},
    )
    assert response.status_code == 402
    assert "erlaubt" in response.json()["detail"]


# --- Oberfläche und API ----------------------------------------------------

def test_license_page_shows_status_and_deployment_id(client, licensing, keypair):
    private_key, _ = keypair
    _store(licensing, _document(private_key, licensing.deployment_id()))
    _login(client)
    page = client.get("/admin/system/license")
    assert page.status_code == 200
    assert "ERF-TEST-0001" in page.text
    assert licensing.deployment_id() in page.text
    assert "Lizenziert" in page.text


def test_license_page_never_shows_the_activation_key(client, licensing, keypair):
    private_key, _ = keypair
    _store(licensing, _document(private_key, licensing.deployment_id()), key="GEHEIM-1234")
    _login(client)
    page = client.get("/admin/system/license")
    assert "GEHEIM-1234" not in page.text
    assert "••••-1234" in page.text


def test_license_navigation_entry_exists(client):
    _login(client)
    page = client.get("/admin/system/status")
    assert '/admin/system/license' in page.text


def test_banner_warns_while_unlicensed(client):
    _login(client)
    page = client.get("/admin/system/status")
    assert "license-banner" in page.text
    assert "Nicht lizenziert" in page.text


def test_banner_disappears_with_a_valid_license(client, licensing, keypair):
    private_key, _ = keypair
    _store(licensing, _document(private_key, licensing.deployment_id()))
    _login(client)
    page = client.get("/admin/system/status")
    assert "license-banner" not in page.text


def test_activation_via_the_admin_form(client, licensing, keypair, monkeypatch):
    private_key, _ = keypair
    document = _document(private_key, licensing.deployment_id(), max_users=42)
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": document}),
        public_pem=keypair[1],
    )
    _login(client)
    token = _csrf(client, "/admin/system/license")
    response = client.post(
        "/admin/system/license/activate",
        data={
            "server_url": "https://lizenz.example.org",
            "activation_key": "ERF-TEST-KEY-0001",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Lizenz+aktiviert" in response.headers["location"]
    assert licensing.current_status().max_users == 42


def test_failed_activation_reports_the_reason(client, licensing, keypair, monkeypatch):
    _stub_server(licensing, monkeypatch, _Response(403), public_pem=keypair[1])
    _login(client)
    token = _csrf(client, "/admin/system/license")
    response = client.post(
        "/admin/system/license/activate",
        data={
            "server_url": "https://lizenz.example.org",
            "activation_key": "FALSCH",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert licensing.current_status().status == licensing.STATUS_UNLICENSED


def test_api_license_status_hides_secrets(client, licensing, keypair):
    private_key, _ = keypair
    _store(licensing, _document(private_key, licensing.deployment_id()), key="GEHEIM-1234")
    _login(client)
    response = client.get("/api/license")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "valid"
    assert body["license_id"] == "ERF-TEST-0001"
    serialised = json.dumps(body)
    assert "GEHEIM-1234" not in serialised
    assert "signature" not in body
    assert "activation_key" not in body


def test_api_license_status_requires_login(client):
    assert client.get("/api/license").status_code == 401


def test_license_page_requires_system_permission(client, main):
    """Ein Benutzer ohne Systemrechte landet wieder auf dem Dashboard."""
    from app import crud, database, schemas, security

    db = database.SessionLocal()
    try:
        crud.create_user(
            db,
            schemas.UserCreate(
                username="ohnerechte",
                full_name="Ohne Rechte",
                email="ohne@example.org",
                password="Sicher!0000",
            ),
        )
        person = crud.get_user_by_username(db, "ohnerechte")
        person.password_hash = security.hash_password("Sicher!0000")
        person.must_change_password = False
        db.commit()
    finally:
        db.close()

    token = _csrf(client, "/login")
    client.post(
        "/login",
        data={"username": "ohnerechte", "password": "Sicher!0000", "csrf_token": token},
        follow_redirects=False,
    )
    response = client.get("/admin/system/license", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
    assert client.get("/api/license").status_code == 403


# --- Protokoll und Export --------------------------------------------------

def test_license_channel_is_registered(main):
    from app import logging_setup

    assert "license" in logging_setup.CHANNELS
    assert logging_setup.CHANNELS["license"] == "license.log"


def test_startup_writes_the_license_status_to_its_own_log(client):
    from app import logging_setup

    content = logging_setup.channel_path("license").read_text(encoding="utf-8")
    assert "Lizenzstatus" in content


def test_activation_key_never_reaches_the_log(client, licensing, keypair, monkeypatch):
    private_key, _ = keypair
    document = _document(private_key, licensing.deployment_id())
    _stub_server(
        licensing, monkeypatch, _Response(200, {"license": document}),
        public_pem=keypair[1],
    )
    _login(client)
    token = _csrf(client, "/admin/system/license")
    client.post(
        "/admin/system/license/activate",
        data={
            "server_url": "https://lizenz.example.org",
            "activation_key": "GEHEIM-9999",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    from app import logging_setup, paths

    for path in (logging_setup.channel_path("license"), *paths.LOGS_DIR.glob("*.log")):
        if path.exists():
            assert "GEHEIM-9999" not in path.read_text(encoding="utf-8")


def test_settings_export_contains_no_license_data(main):
    from app import app_config

    payload = json.dumps(app_config.export_all())
    assert "activation_key" not in payload
    assert "deployment_id" not in payload


def test_restore_re_tightens_the_license_file_permissions(licensing, keypair):
    """Nach dem Auspacken eines Archivs stehen die Rechte auf dem Standard."""
    private_key, _ = keypair
    _store(licensing, _document(private_key, licensing.deployment_id()))
    from app import paths

    path = paths.CONFIG_DIR / "license.json"
    path.chmod(0o644)
    licensing.harden_config_permissions()
    assert (path.stat().st_mode & 0o777) == 0o600


def test_masked_activation_key():
    from app.licensing import masked_activation_key

    assert masked_activation_key("") == ""
    assert masked_activation_key("ab") == "••"
    assert masked_activation_key("ERF-ABCD-1234") == "••••-1234"
