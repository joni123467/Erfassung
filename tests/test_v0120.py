"""Tests für 0.12.0 – Funktionsbausteine, Nachfrage, Übergangsfrist.

Drei zusammengehörige Dinge:

* **Funktionsbausteine.** Eine Lizenz schaltet ``orders``, ``vacation``,
  ``reports`` und ``terminals`` frei. Stempeln und die eigene Zeitübersicht
  gehören zur Basis und bleiben immer offen.
* **Regelmäßige Nachfrage.** Einmal täglich fragt die Installation beim
  Lizenzserver nach und bekommt ein frisches Dokument – Änderungen wirken
  damit ohne Zutun des Kunden.
* **Übergangsfrist.** Ein *unerreichbarer* Server sperrt nie. Nur eine
  ausdrückliche Sperrmeldung startet die Frist; erst nach deren Ablauf gehen
  die zubuchbaren Bereiche zu. Stempeln bleibt in jedem Fall möglich.
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


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


# --- Funktionsbausteine ----------------------------------------------------

GATED = [
    ("/admin/companies", "orders"),
    ("/admin/reports/time", "reports"),
    ("/admin/reports/users", "reports"),
    ("/admin/terminals", "terminals"),
    ("/records/vacations", "vacation"),
]


def test_without_a_license_everything_stays_open(client):
    """Ein Update darf einen laufenden Betrieb nicht beschneiden."""
    _login(client)
    for path, _ in GATED:
        assert client.get(path, follow_redirects=False).status_code == 200, path


@pytest.mark.parametrize(("path", "feature"), GATED)
def test_licensed_module_opens_its_area(client, licensing, keypair, path, feature):
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=[feature]))
    _login(client)
    assert client.get(path, follow_redirects=False).status_code == 200


@pytest.mark.parametrize(("path", "feature"), GATED)
def test_missing_module_closes_its_area(client, licensing, keypair, path, feature):
    """Eine reine Stempel-Lizenz sperrt alles Zubuchbare."""
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=[]))
    _login(client)
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/dashboard")
    assert "nicht+enthalten" in response.headers["location"]


def test_clocking_always_works(client, licensing, keypair):
    """Auch mit der kleinsten Lizenz – sonst ginge Arbeitszeit verloren."""
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=[]))
    _login(client)
    for path in ("/dashboard", "/records", "/admin/users", "/admin/system/backups"):
        assert client.get(path, follow_redirects=False).status_code == 200, path


def test_navigation_hides_unlicensed_areas(client, licensing, keypair):
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["vacation"]))
    _login(client)
    page = client.get("/admin/users").text
    assert "/admin/reports/time" not in page
    assert "/admin/terminals" not in page
    assert "/admin/companies" not in page
    # Basis bleibt sichtbar.
    assert "/admin/users" in page


def test_api_answers_402_for_a_missing_module(client, licensing, keypair):
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=[]))
    _login(client)
    response = client.get("/api/vacations")
    assert response.status_code == 402
    assert response.json()["feature"] == "vacation"


def test_unknown_paths_are_never_gated(main):
    assert main.LicenseFeatureMiddleware.required_feature("/dashboard") is None
    assert main.LicenseFeatureMiddleware.required_feature("/records") is None
    # Aber Unterseiten eines Bereichs schon – das ist der Sinn der Middleware.
    assert main.LicenseFeatureMiddleware.required_feature("/admin/reports/users/pdf") == "reports"
    assert main.LicenseFeatureMiddleware.required_feature("/admin/companies/7") == "orders"


def test_similar_prefixes_are_not_confused(main):
    """``/admin/reportsxyz`` ist kein Unterpfad von ``/admin/reports``."""
    assert main.LicenseFeatureMiddleware.required_feature("/admin/reportsxyz") is None


# --- Nachfrage beim Lizenzserver -------------------------------------------

def test_unreachable_server_never_blocks(client, licensing, keypair, monkeypatch):
    """Der wichtigste Fall: Ausfall darf niemals sperren."""
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["vacation"]))

    def boom(url, payload):
        raise licensing.LicenseError("Der Lizenzserver ist nicht erreichbar: timeout")

    monkeypatch.setattr(licensing, "_post", boom)
    reached, message = licensing.refresh_from_server()

    assert reached is False
    assert "nicht erreichbar" in message
    state = licensing.current_status()
    assert state.is_valid
    assert not state.is_blocked
    _login(client)
    assert client.get("/records/vacations", follow_redirects=False).status_code == 200


def test_an_old_server_without_the_endpoint_is_harmless(licensing, keypair, monkeypatch):
    _store(licensing, _document(keypair[0], licensing.deployment_id()))
    monkeypatch.setattr(licensing, "_post", lambda url, payload: _Response(404))
    reached, _ = licensing.refresh_from_server()
    assert reached is False
    assert licensing.current_status().is_valid


def test_active_answer_refreshes_the_document(licensing, keypair):
    """Genau dafür wird nachgefragt: Änderungen wirken ohne Zutun des Kunden."""
    private_key, _ = keypair
    deployment = licensing.deployment_id()
    _store(licensing, _document(private_key, deployment, features=[], max_users=10))

    fresh = _document(private_key, deployment, features=["vacation", "reports"], max_users=99)
    import app.licensing as module

    module._post = lambda url, payload: _Response(200, {"status": "active", "license": fresh})

    reached, _ = licensing.refresh_from_server()
    assert reached is True
    state = licensing.current_status()
    assert state.max_users == 99
    assert state.features == ["reports", "vacation"]


def test_a_forged_fresh_document_is_refused(licensing, keypair, monkeypatch):
    """Auch bei der Nachfrage wird die Signatur geprüft."""
    deployment = licensing.deployment_id()
    _store(licensing, _document(keypair[0], deployment, max_users=10))

    other_key, _ = _keypair()
    forged = _document(other_key, deployment, max_users=9999)
    monkeypatch.setattr(
        licensing, "_post",
        lambda url, payload: _Response(200, {"status": "active", "license": forged}),
    )
    licensing.refresh_from_server()
    # Das alte Dokument gilt weiter.
    assert licensing.current_status().max_users == 10


@pytest.mark.parametrize("state_value", ["suspended", "revoked", "expired"])
def test_a_block_starts_the_grace_period(licensing, keypair, monkeypatch, state_value):
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["vacation"]))
    monkeypatch.setattr(
        licensing, "_post",
        lambda url, payload: _Response(
            200, {"status": state_value, "reason": "Bitte den Support kontaktieren."}
        ),
    )
    reached, message = licensing.refresh_from_server()

    assert reached is True
    assert "Support" in message
    state = licensing.current_status()
    assert state.is_blocked
    assert state.blocked_status == state_value
    assert state.grace_days_left == licensing.GRACE_PERIOD_DAYS
    assert not state.grace_expired


def test_during_the_grace_period_everything_still_works(client, licensing, keypair, monkeypatch):
    _store(licensing, _document(keypair[0], licensing.deployment_id(), features=["vacation"]))
    monkeypatch.setattr(
        licensing, "_post",
        lambda url, payload: _Response(200, {"status": "suspended", "reason": "gesperrt"}),
    )
    licensing.refresh_from_server()

    _login(client)
    assert client.get("/records/vacations", follow_redirects=False).status_code == 200


def test_after_the_grace_period_modules_are_closed(client, licensing, keypair):
    """Rückdatiert: die Frist ist abgelaufen."""
    long_ago = datetime.now(tz=timezone.utc) - timedelta(
        days=licensing.GRACE_PERIOD_DAYS + 1
    )
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id(), features=["vacation", "reports"]),
        blocked_status="suspended",
        blocked_since=long_ago.isoformat(),
        blocked_reason="Die Lizenz wurde vorübergehend gesperrt.",
    )
    state = licensing.current_status()
    assert state.grace_expired
    assert state.grace_days_left == 0

    _login(client)
    assert client.get("/records/vacations", follow_redirects=False).status_code == 303
    assert client.get("/admin/reports/time", follow_redirects=False).status_code == 303
    # Stempeln bleibt.
    assert client.get("/dashboard", follow_redirects=False).status_code == 200
    assert client.get("/records", follow_redirects=False).status_code == 200


def test_a_lifted_block_ends_the_grace_period(licensing, keypair, monkeypatch):
    deployment = licensing.deployment_id()
    _store(
        licensing,
        _document(keypair[0], deployment, features=["vacation"]),
        blocked_status="suspended",
        blocked_since=(datetime.now(tz=timezone.utc) - timedelta(days=3)).isoformat(),
        blocked_reason="gesperrt",
    )
    assert licensing.current_status().is_blocked

    fresh = _document(keypair[0], deployment, features=["vacation"])
    monkeypatch.setattr(
        licensing, "_post",
        lambda url, payload: _Response(200, {"status": "active", "license": fresh}),
    )
    licensing.refresh_from_server()

    state = licensing.current_status()
    assert not state.is_blocked
    assert state.grace_days_left is None


def test_banner_warns_during_the_grace_period(client, licensing, keypair):
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id()),
        blocked_status="suspended",
        blocked_since=(datetime.now(tz=timezone.utc) - timedelta(days=2)).isoformat(),
        blocked_reason="Die Lizenz wurde vorübergehend gesperrt.",
    )
    _login(client)
    page = client.get("/admin/users").text
    assert "Lizenz gesperrt" in page
    assert "vorübergehend gesperrt" in page
    assert "Stempeln bleibt" in page


# --- Fälligkeit und Scheduler ----------------------------------------------

def test_check_is_due_only_after_the_interval(licensing, keypair):
    _store(licensing, _document(keypair[0], licensing.deployment_id()),
           last_contact_at=datetime.now(tz=timezone.utc).isoformat())
    assert licensing.due_for_check() is False

    stale = datetime.now(tz=timezone.utc) - timedelta(
        hours=licensing.CHECK_INTERVAL_HOURS + 1
    )
    _store(licensing, _document(keypair[0], licensing.deployment_id()),
           last_contact_at=stale.isoformat())
    assert licensing.due_for_check() is True


def test_no_license_means_nothing_to_check(licensing):
    assert licensing.due_for_check() is False


def test_scheduler_skips_when_not_due(main, licensing, keypair, monkeypatch):
    from app import license_scheduler

    _store(licensing, _document(keypair[0], licensing.deployment_id()),
           last_contact_at=datetime.now(tz=timezone.utc).isoformat())
    called = []
    monkeypatch.setattr(
        licensing, "refresh_from_server", lambda: called.append(1) or (True, "ok")
    )
    reached, message = license_scheduler.check_now()
    assert reached is False
    assert "fällig" in message
    assert called == []


def test_scheduler_can_be_forced(main, licensing, keypair, monkeypatch):
    from app import license_scheduler

    _store(licensing, _document(keypair[0], licensing.deployment_id()),
           last_contact_at=datetime.now(tz=timezone.utc).isoformat())
    monkeypatch.setattr(licensing, "refresh_from_server", lambda: (True, "bestätigt"))
    reached, message = license_scheduler.check_now(force=True)
    assert reached is True
    assert message == "bestätigt"


def test_scheduler_survives_a_failing_check(main, licensing, monkeypatch):
    """Der Thread darf an keinem Fehler sterben."""
    from app import license_scheduler

    def boom():
        raise RuntimeError("kaputt")

    monkeypatch.setattr(licensing, "refresh_from_server", boom)
    monkeypatch.setattr(licensing, "due_for_check", lambda: True)
    reached, message = license_scheduler.check_now()
    assert reached is False
    assert "kaputt" in message


# --- Anzeige ---------------------------------------------------------------

def test_license_page_lists_the_modules(client, licensing, keypair):
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id(), features=["vacation", "reports"]),
    )
    _login(client)
    page = client.get("/admin/system/license").text
    assert "Urlaubsplanung" in page
    assert "Auswertungen" in page


def test_api_status_reports_block_and_grace(client, licensing, keypair):
    _store(
        licensing,
        _document(keypair[0], licensing.deployment_id()),
        blocked_status="suspended",
        blocked_since=(datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat(),
        blocked_reason="gesperrt",
    )
    _login(client)
    body = client.get("/api/license").json()
    assert body["blocked_status"] == "suspended"
    assert body["blocked_reason"] == "gesperrt"
    assert body["grace_days_left"] == licensing.GRACE_PERIOD_DAYS - 1
    assert body["grace_expired"] is False
