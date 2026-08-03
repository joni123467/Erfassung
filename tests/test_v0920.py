"""Regression tests for 0.9.20 – optional stamp times in the admin user
evaluation PDF.

Covers: version bump, the ``entries`` flag reaching the report data, the
``include_entries`` parameter of ``export_user_summary_pdf`` (bigger PDF, both
variants valid), the checkbox in the admin view, the export route (filename
suffix and content), and that the permission scope still limits which users'
stamp times end up in the file.
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


def login(client, username: str = "admin", password: str = "Admin!0000"):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


DAY = date(2026, 6, 15)
PERIOD = {"start": "2026-06-01", "end": "2026-06-30"}


def _admin_id() -> int:
    from app import crud, database

    db = database.SessionLocal()
    try:
        return crud.get_user_by_username(db, "admin").id
    finally:
        db.close()


def _approved_entry(user_id, start, end, *, notes="Büro", company_id=None):
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        return crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=user_id, company_id=company_id, work_date=DAY,
                start_time=start, end_time=end, break_minutes=0,
                break_started_at=None, is_open=False, notes=notes,
                status=models.TimeEntryStatus.APPROVED, is_manual=False,
            ),
        ).id
    finally:
        db.close()


def _report_data(params: dict, allowed=None):
    from urllib.parse import urlencode

    from starlette.datastructures import QueryParams

    from app import database
    from app.main import _build_user_report_data

    db = database.SessionLocal()
    try:
        return _build_user_report_data(QueryParams(urlencode(params)), db, allowed)
    finally:
        db.close()


# --- version -------------------------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.20.6"
    assert client.get("/health").json()["version"] == "0.20.6"


# --- report data ----------------------------------------------------------------

def test_report_rows_carry_entries(client):
    uid = _admin_id()
    _approved_entry(uid, time(8, 0), time(12, 0))
    _approved_entry(uid, time(13, 0), time(16, 30), notes="Kundentermin")

    data = _report_data(PERIOD)
    row = next(item for item in data["report_rows"] if item["user"].id == uid)
    assert row["count"] == 2
    assert len(row["entries"]) == 2
    assert {entry.start_time for entry in row["entries"]} == {time(8, 0), time(13, 0)}


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("on", True), ("true", True), ("0", False), (None, False)],
)
def test_entries_flag_parsed(client, value, expected):
    params = dict(PERIOD)
    if value is not None:
        params["entries"] = value
    assert _report_data(params)["include_entries"] is expected


# --- PDF generation --------------------------------------------------------------

def test_pdf_includes_entries_only_when_requested(client):
    from app.pdf_export import export_user_summary_pdf

    uid = _admin_id()
    _approved_entry(uid, time(8, 0), time(12, 0))
    _approved_entry(uid, time(13, 0), time(16, 30), notes="Kundentermin")
    data = _report_data(PERIOD)

    plain = export_user_summary_pdf(
        period_range=data["period_range"],
        rows=data["report_rows"],
        totals=data["report_totals"],
    ).getvalue()
    detailed = export_user_summary_pdf(
        period_range=data["period_range"],
        rows=data["report_rows"],
        totals=data["report_totals"],
        include_entries=True,
    ).getvalue()

    assert plain.startswith(b"%PDF") and detailed.startswith(b"%PDF")
    # Die Stempelzeiten-Tabellen machen das PDF deutlich größer
    assert len(detailed) > len(plain)


def test_pdf_with_entries_handles_user_without_bookings(client):
    """Ein Benutzer ohne Buchungen darf den Export nicht sprengen."""
    from app.pdf_export import export_user_summary_pdf

    data = _report_data(PERIOD)
    assert data["report_rows"], "Testvoraussetzung: mindestens ein Benutzer"
    assert all(not row["entries"] for row in data["report_rows"])
    buffer = export_user_summary_pdf(
        period_range=data["period_range"],
        rows=data["report_rows"],
        totals=data["report_totals"],
        include_entries=True,
    )
    assert buffer.getvalue().startswith(b"%PDF")


# --- view + route ----------------------------------------------------------------

def test_view_offers_entries_checkbox(client):
    login(client)
    html = client.get("/admin/reports/users").text
    assert 'action="/admin/reports/users/pdf"' in html
    assert 'name="entries"' in html
    assert "Stempelzeiten" in html


def test_export_route_with_and_without_entries(client):
    login(client)
    uid = _admin_id()
    _approved_entry(uid, time(8, 0), time(12, 0))

    plain = client.get("/admin/reports/users/pdf", params=PERIOD)
    assert plain.status_code == 200
    assert plain.headers["content-type"] == "application/pdf"
    assert "_stempelzeiten" not in plain.headers["content-disposition"]

    detailed = client.get("/admin/reports/users/pdf", params={**PERIOD, "entries": "1"})
    assert detailed.status_code == 200
    assert "_stempelzeiten.pdf" in detailed.headers["content-disposition"]
    assert detailed.content.startswith(b"%PDF")
    assert len(detailed.content) > len(plain.content)


def test_entries_respect_permission_scope(client):
    """Eine Abteilungsleitung (Rolle mit Geltungsbereich „Eigene Gruppen")
    bekommt nur die Stempelzeiten ihrer Gruppen."""
    from app import crud, database, schemas, security

    db = database.SessionLocal()
    try:
        group = crud.create_group(db, schemas.GroupCreate(name="Abteilung"))
        role = crud.create_role(
            db, name="Abteilungsleitung", permissions={"Time.View": "groups"}
        )
        lead = crud.create_user(
            db,
            schemas.UserCreate(
                username="lead", full_name="Lead", email="lead@example.com",
                password="Lead!00000", group_ids=[group.id], role_ids=[role.id],
            ),
        )
        lead.must_change_password = False
        lead.password_hash = security.hash_password("Lead!00000")
        db.commit()
        lead_id = lead.id
    finally:
        db.close()

    _approved_entry(_admin_id(), time(8, 0), time(12, 0), notes="Adminbuchung")
    _approved_entry(lead_id, time(9, 0), time(11, 0), notes="Teambuchung")

    login(client, "lead", "Lead!00000")
    page = client.get("/admin/reports/users", params=PERIOD)
    assert page.status_code == 200
    assert "Lead" in page.text

    from starlette.datastructures import QueryParams
    from urllib.parse import urlencode

    from app.main import _build_user_report_data, _scoped_user_ids

    db = database.SessionLocal()
    try:
        lead_user = crud.get_user_by_username(db, "lead")
        data = _build_user_report_data(
            QueryParams(urlencode({**PERIOD, "entries": "1"})),
            db,
            _scoped_user_ids(db, lead_user, "Time.View"),
        )
        assert data["include_entries"] is True
        assert [row["user"].id for row in data["report_rows"]] == [lead_id]
        assert [entry.notes for entry in data["report_rows"][0]["entries"]] == ["Teambuchung"]
    finally:
        db.close()

    export = client.get("/admin/reports/users/pdf", params={**PERIOD, "entries": "1"})
    assert export.status_code == 200
    assert export.content.startswith(b"%PDF")
