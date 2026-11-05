"""Persönliche Kontoseite, eigene QR-Codes und persistierte Startansichten."""
from __future__ import annotations

import base64
from datetime import date, datetime, time, timedelta
from io import BytesIO
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from PIL import Image
from sqlalchemy import create_engine, inspect, text

from test_v0209 import client, main, _csrf, _login


def _members():
    from app import database, models, security

    with database.SessionLocal() as db:
        users = [models.User(
            username=f"member{n}", full_name=f"Mitarbeiter {n}",
            email=f"member{n}@example.invalid", pin_code=f"773{n}",
            password_hash=security.hash_password("Member!0000"),
            must_change_password=False,
        ) for n in (1, 2)]
        db.add_all(users)
        db.commit()
        return [user.id for user in users]


def _api_token(client):
    return client.get("/api/csrf").json()["csrf_token"]


def test_account_and_qr_require_a_current_active_session(client):
    assert client.get("/account", follow_redirects=False).status_code == 303
    assert client.get("/account/mobile-qr.png").status_code == 401
    assert client.get("/api/account/preferences").status_code == 401
    _login(client)
    from app import database, models

    with database.SessionLocal() as db:
        db.get(models.User, 1).is_active = False
        db.commit()
    assert client.get("/account/mobile-qr.png").status_code == 401
    assert client.get("/api/account/preferences").status_code == 401


def test_member_gets_only_own_qr_with_original_ttl_and_download(client, main, monkeypatch):
    own_id, other_id = _members()
    _login(client, "member1", "Member!0000")
    response = client.get("/account")
    assert response.status_code == 200
    assert "Mein Konto" in response.text and 'id="account-qr"' in response.text
    assert "Mitarbeiter 1" in response.text and "Mitarbeiter 2" not in response.text
    assert "no-store" in response.headers["cache-control"]
    assert "token=" not in response.text
    assert "/account/password" in response.text
    assert 'data-theme-toggle' in response.text
    assert client.get(f"/admin/users/{other_id}/mobile-qr.png").status_code == 403

    captured = []
    original = main.qrcode.QRCode.add_data

    def capture(self, data, *args, **kwargs):
        captured.append(data)
        return original(self, data, *args, **kwargs)

    monkeypatch.setattr(main.qrcode.QRCode, "add_data", capture)
    image = client.get(f"/account/mobile-qr.png?user_id={other_id}&download=true&size=400")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "no-store"
    assert image.headers["pragma"] == "no-cache"
    assert f"erfassung-login-{own_id}.png" in image.headers["content-disposition"]
    assert Image.open(BytesIO(image.content)).size == (400, 400)
    token = parse_qs(urlparse(captured[-1]).query)["token"][0]
    assert main._verify_mobile_autologin_token(token) == own_id
    decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    _, expiry, _ = decoded.split(":")
    assert abs(int(expiry) - int(datetime.utcnow().timestamp()) - 30 * 86400) < 5

    assert client.post("/account/mobile-qr/regenerate").status_code == 403
    refresh = client.post("/account/mobile-qr/regenerate", data={"csrf_token": _csrf(client, "/account")}, follow_redirects=False)
    assert refresh.status_code == 303 and refresh.headers["location"].endswith("#mobile-login")
    # Neuerzeugen darf die vorhandene Token-/Widerrufssemantik nicht ändern.
    assert main._verify_mobile_autologin_token(token) == own_id
    client.get("/logout")
    result = client.get("/mobile/quick-login", params={"token": token}, follow_redirects=False)
    assert result.status_code == 303
    assert client.get("/api/account/preferences").json()["user_id"] == own_id


def test_preferences_are_persisted_for_the_session_user_only(client):
    own_id, other_id = _members()
    _login(client, "member1", "Member!0000")
    assert client.get("/api/account/preferences").json() == {"user_id": own_id, "overview_preference": "day"}
    assert client.post("/api/account/preferences", json={"overview_preference": "week"}).status_code == 403
    headers = {"x-csrf-token": _api_token(client)}
    mismatch = client.post("/api/account/preferences", json={"overview_preference": "week", "user_id": other_id}, headers=headers)
    assert mismatch.status_code == 409
    for payload in ({"overview_preference": "month"}, {"overview_preference": "week", "target_user_id": other_id}, {"overview_preference": "week", "user_id": True}):
        assert client.post("/api/account/preferences", json=payload, headers=headers).status_code == 422
    response = client.post("/api/account/preferences", json={"overview_preference": "week", "user_id": own_id}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"user_id": own_id, "overview_preference": "week"}
    assert "no-store" in response.headers["cache-control"]
    from app import database, models

    with database.SessionLocal() as db:
        assert db.get(models.User, own_id).overview_preference == "week"
        assert db.get(models.User, other_id).overview_preference == "day"
    client.get("/logout")
    _login(client, "member2", "Member!0000")
    assert client.get("/api/account/preferences").json()["overview_preference"] == "day"
    client.get("/logout")
    _login(client, "member1", "Member!0000")
    assert client.get("/api/account/preferences").json()["overview_preference"] == "week"


def test_preference_form_validates_csrf_choice_and_account_binding(client):
    own_id, other_id = _members()
    _login(client, "member1", "Member!0000")
    token = _csrf(client, "/account")
    assert client.post("/account/preferences", data={"overview_preference": "week"}).status_code == 403
    for value, target, expected in (("month", own_id, 400), ("week", other_id, 409)):
        response = client.post("/account/preferences", data={"overview_preference": value, "user_id": target, "csrf_token": token})
        assert response.status_code == expected
        assert client.get("/api/account/preferences").json()["overview_preference"] == "day"
    response = client.post("/account/preferences", data={"overview_preference": "week", "user_id": own_id, "csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/account").context["overview_preference"] == "week"


def test_dashboard_navigation_is_temporary_and_does_not_move_the_active_day(client):
    _login(client)
    from app import database, models

    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    reference = today - timedelta(days=14)
    with database.SessionLocal() as db:
        user = db.get(models.User, 1)
        user.overview_preference = "week"
        db.add(models.TimeEntry(user_id=user.id, work_date=reference, start_time=time(8), end_time=time(9), break_minutes=0, is_open=False, status=models.TimeEntryStatus.APPROVED))
        db.add(models.TimeEntry(user_id=user.id, work_date=today, start_time=time(0), end_time=time(0), break_minutes=0, is_open=True, status=models.TimeEntryStatus.APPROVED))
        db.commit()
    baseline = client.get("/dashboard").context
    assert baseline["overview_mode"] == "week"
    response = client.get("/dashboard", params={"overview": "day", "date": reference.isoformat()})
    assert response.status_code == 200
    context = response.context
    assert context["overview_mode"] == "day"
    assert context["overview_reference"] == reference
    assert context["overview_previous"] == reference - timedelta(days=1)
    assert context["overview_next"] == reference + timedelta(days=1)
    assert context["overview_total_minutes"] == 60
    assert context["overview_entries"][0].work_date == reference
    assert context["today"] == today
    assert context["active_entry"].work_date == today
    assert context["daily_total_minutes"] == baseline["daily_total_minutes"]
    assert client.get("/dashboard").context["overview_mode"] == "week"
    assert client.get("/dashboard?date=invalid").context["overview_reference"] == today
    assert client.get("/dashboard?date=9999-12-31").context["overview_reference"] == today
    mobile = client.get("/mobile?tab=einstellungen")
    assert mobile.context["active_tab"] == "einstellungen"
    assert mobile.context["overview_mode"] == "week"


def test_mobile_snapshot_contains_preferences_and_permissions_but_no_qr(client):
    own_id, _ = _members()
    _login(client, "member1", "Member!0000")
    client.post("/api/account/preferences", json={"overview_preference": "week"}, headers={"x-csrf-token": _api_token(client)})
    snapshot = client.get("/mobile/sync-data").json()
    assert snapshot["user"]["id"] == own_id
    assert snapshot["user"]["overview_preference"] == "week"
    assert snapshot["permissions"]["account_access"] is True
    assert snapshot["permissions"]["admin_access"] is False
    assert "overtime_vacation_enabled" in snapshot["user"]
    assert "quick-login" not in str(snapshot)
    assert "mobile-qr" not in str(snapshot)


def test_migration_26_upgrades_an_existing_database_idempotently(main, tmp_path):
    from app import db_migrations, db_schema

    engine = create_engine(f"sqlite:///{tmp_path}/preference-upgrade.db")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, full_name VARCHAR(255), note VARCHAR(255))"))
            connection.execute(text("INSERT INTO users VALUES (1, 'Bestandskonto', 'Daten erhalten')"))
            connection.execute(text("PRAGMA user_version = 25"))
        db_migrations._apply_migrations(engine, db_migrations.MIGRATIONS)
        with engine.begin() as connection:
            row = connection.execute(text("SELECT * FROM users")).mappings().one()
            assert row["full_name"] == "Bestandskonto" and row["note"] == "Daten erhalten"
            assert row["overview_preference"] == "day"
            connection.execute(text("UPDATE users SET overview_preference='week' WHERE id=1"))
        db_migrations._apply_migrations(engine, db_migrations.MIGRATIONS)
        db_migrations._add_user_overview_preference(engine)
        assert db_schema.latest_applied_version(engine) == 26
        with engine.connect() as connection:
            assert connection.execute(text("SELECT overview_preference FROM users WHERE id=1")).scalar_one() == "week"
    finally:
        engine.dispose()


def test_ensure_schema_repairs_missing_column_without_losing_users(client, main):
    from app import database, models

    with database.engine.begin() as connection:
        before = connection.execute(text("SELECT id, username, password_hash FROM users")).all()
        connection.execute(text("ALTER TABLE users DROP COLUMN overview_preference"))
    main.ensure_schema()
    main.ensure_schema()
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT id, username, password_hash FROM users")).all() == before
        assert set(connection.execute(text("SELECT overview_preference FROM users")).scalars()) == {"day"}
    assert str(inspect(database.engine).get_columns("users")[-1]["type"]) == "VARCHAR(8)"


def test_schema_helper_repairs_null_and_uses_portable_ddl(main, tmp_path, monkeypatch):
    from app import account_ui, db_schema, models
    from sqlalchemy.dialects import mysql, postgresql, sqlite
    from sqlalchemy.schema import CreateTable

    engine = create_engine(f"sqlite:///{tmp_path}/nullable-preference.db")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, overview_preference VARCHAR(8))"))
            connection.execute(text("INSERT INTO users VALUES (1,NULL),(2,'week')"))
        account_ui.ensure_overview_preference(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT overview_preference FROM users ORDER BY id")).scalars().all() == ["day", "week"]
    finally:
        engine.dispose()
    for dialect in (sqlite.dialect(), mysql.dialect(), postgresql.dialect()):
        ddl = str(CreateTable(models.User.__table__).compile(dialect=dialect))
        assert "overview_preference VARCHAR(8)" in ddl
        assert "DEFAULT 'day'" in ddl


@pytest.mark.parametrize("legacy", [False, True])
def test_logical_backup_restore_preserves_or_defaults_preferences(client, tmp_path, legacy):
    from app import data_transfer, database, db_migrations, models

    with database.SessionLocal() as db:
        db.get(models.User, 1).overview_preference = "week"
        db.commit()
    payload = data_transfer.export_database(database.engine)
    if legacy:
        for row in payload["tables"]["users"]:
            row.pop("overview_preference", None)
    restored = create_engine(f"sqlite:///{tmp_path}/restored.db")
    try:
        models.Base.metadata.create_all(restored)
        data_transfer.import_database(restored, payload)
        db_migrations._apply_migrations(restored, db_migrations.MIGRATIONS)
        with restored.connect() as connection:
            row = connection.execute(text("SELECT username,overview_preference FROM users WHERE id=1")).one()
            assert row == ("admin", "day" if legacy else "week")
        assert data_transfer.current_row_counts(restored) == data_transfer.current_row_counts(database.engine)
    finally:
        restored.dispose()
