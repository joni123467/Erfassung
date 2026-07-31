"""Tests für 0.11.1 – Freigaben, halbe Urlaubstage, Lizenzanfrage.

**Freigaben (Regression).** Beim Umstieg auf Rollen (0.10.0) blieben an drei
Stellen die alten Gruppenrechte-Namen stehen
(``can_edit_time_entries``, ``can_approve_manual_entries``,
``can_manage_vacations``). Ein unbekannter Schlüssel ergibt Geltungsbereich
``none`` – und damit wurde *jede* Freigabe verweigert, auch die des
Superadministrators.

**Halbe Urlaubstage.** Erster und letzter Tag eines Antrags lassen sich
halbieren; ein eintägiger Antrag braucht nur ein Kennzeichen.

**Lizenzanfrage.** Ein Knopf führt zum Lizenzserver und nimmt die Angaben mit,
die der Herausgeber braucht – ohne Geheimnisse.
"""

from __future__ import annotations

import re
import sys
from datetime import date, time, timedelta
from urllib.parse import parse_qs, urlparse

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
            db.commit()
        finally:
            db.close()
        yield test_client


_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _csrf(client, url: str) -> str:
    match = _CSRF_RE.search(client.get(url).text)
    assert match, f"kein CSRF-Token auf {url}"
    return match.group(1)


def _login(client, username: str = "admin", password: str = "Admin!0000") -> None:
    token = _csrf(client, "/login")
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303), response.text


def _employee(db, username: str = "mitarbeiter"):
    from app import crud, schemas, security

    person = crud.create_user(
        db,
        schemas.UserCreate(
            username=username,
            full_name="Mit Arbeiter",
            email=f"{username}@example.org",
            password="Sicher!0000",
        ),
    )
    person.password_hash = security.hash_password("Sicher!0000")
    person.must_change_password = False
    db.commit()
    return person


def _pending_entry(db, user_id: int):
    from app import models

    entry = models.TimeEntry(
        user_id=user_id,
        work_date=date.today(),
        start_time=time(9, 0),
        end_time=time(17, 0),
        status=models.TimeEntryStatus.PENDING,
        is_manual=True,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _pending_vacation(db, user_id: int, **kwargs):
    from app import models

    vacation = models.VacationRequest(
        user_id=user_id,
        start_date=kwargs.pop("start_date", date.today()),
        end_date=kwargs.pop("end_date", date.today()),
        status=models.VacationStatus.PENDING,
        **kwargs,
    )
    db.add(vacation)
    db.commit()
    db.refresh(vacation)
    return vacation


# --- Regression: Freigaben waren komplett gesperrt -------------------------

def test_superadmin_can_approve_a_time_entry(client):
    from app import database, models

    db = database.SessionLocal()
    try:
        entry_id = _pending_entry(db, _employee(db).id).id
    finally:
        db.close()

    _login(client)
    response = client.post(
        f"/admin/time-entries/{entry_id}/status",
        data={"action": "approve", "csrf_token": _csrf(client, "/admin/approvals")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error" not in response.headers["location"]

    db = database.SessionLocal()
    try:
        assert db.get(models.TimeEntry, entry_id).status == models.TimeEntryStatus.APPROVED
    finally:
        db.close()


def test_superadmin_can_reject_a_time_entry(client):
    from app import database, models

    db = database.SessionLocal()
    try:
        entry_id = _pending_entry(db, _employee(db).id).id
    finally:
        db.close()

    _login(client)
    client.post(
        f"/admin/time-entries/{entry_id}/status",
        data={"action": "reject", "csrf_token": _csrf(client, "/admin/approvals")},
    )
    db = database.SessionLocal()
    try:
        assert db.get(models.TimeEntry, entry_id).status == models.TimeEntryStatus.REJECTED
    finally:
        db.close()


def test_superadmin_can_approve_a_vacation(client):
    from app import database, models

    db = database.SessionLocal()
    try:
        vacation_id = _pending_vacation(db, _employee(db).id).id
    finally:
        db.close()

    _login(client)
    response = client.post(
        f"/admin/vacations/{vacation_id}/status",
        data={"action": "approve", "csrf_token": _csrf(client, "/admin/approvals")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error" not in response.headers["location"]

    db = database.SessionLocal()
    try:
        assert db.get(models.VacationRequest, vacation_id).status == (
            models.VacationStatus.APPROVED
        )
    finally:
        db.close()


def test_superadmin_can_reject_a_vacation(client):
    from app import database, models

    db = database.SessionLocal()
    try:
        vacation_id = _pending_vacation(db, _employee(db).id).id
    finally:
        db.close()

    _login(client)
    client.post(
        f"/admin/vacations/{vacation_id}/status",
        data={"action": "reject", "csrf_token": _csrf(client, "/admin/approvals")},
    )
    db = database.SessionLocal()
    try:
        assert db.get(models.VacationRequest, vacation_id).status == (
            models.VacationStatus.REJECTED
        )
    finally:
        db.close()


def test_unknown_permission_key_fails_loudly(client, main):
    """Ein Tippfehler darf nicht stumm alles verbieten – das war die Ursache."""
    from app import database

    db = database.SessionLocal()
    try:
        from app import crud

        admin = crud.get_user_by_username(db, "admin")
        with pytest.raises(KeyError):
            main._user_in_permission_scope(db, admin, "can_approve_manual_entries", admin.id)
        # Der richtige Schlüssel funktioniert weiterhin.
        assert main._user_in_permission_scope(db, admin, "Time.Approve", admin.id)
    finally:
        db.close()


@pytest.mark.parametrize(
    "key",
    ["Time.Approve", "Time.Edit", "Vacation.Manage", "User.View", "User.Edit", "User.Delete"],
)
def test_permission_keys_used_by_routes_exist(main, key):
    from app import permissions

    assert key in permissions.PERMISSIONS_BY_KEY


# --- Halbe Urlaubstage -----------------------------------------------------

def _weekday_in_current_year() -> date:
    """Ein Werktag im laufenden Jahr – Wochenenden zählen nie als Urlaub."""
    day = date(date.today().year, 3, 1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _summary_used_days(db, user):
    from app import crud, services

    return services.calculate_vacation_summary(
        user, crud.get_vacations_for_user(db, user.id), date.today().year
    ).used_days


def test_half_day_factor_rules(main):
    from app import models, services

    single = models.VacationRequest(
        start_date=date(2027, 3, 1), end_date=date(2027, 3, 1), half_day_start=True
    )
    assert services.half_day_factor(single, date(2027, 3, 1)) == 0.5

    # Eintägig: auch das Ende-Kennzeichen allein genügt.
    single_end = models.VacationRequest(
        start_date=date(2027, 3, 1), end_date=date(2027, 3, 1), half_day_end=True
    )
    assert services.half_day_factor(single_end, date(2027, 3, 1)) == 0.5

    span = models.VacationRequest(
        start_date=date(2027, 3, 1), end_date=date(2027, 3, 3),
        half_day_start=True, half_day_end=True,
    )
    assert services.half_day_factor(span, date(2027, 3, 1)) == 0.5
    assert services.half_day_factor(span, date(2027, 3, 2)) == 1.0
    assert services.half_day_factor(span, date(2027, 3, 3)) == 0.5


def test_vacation_days_counts_halves(main):
    from app import models, services

    # Mo–Mi, beide Ränder halb: 0,5 + 1 + 0,5 = 2 Tage
    span = models.VacationRequest(
        start_date=date(2027, 3, 1), end_date=date(2027, 3, 3),
        half_day_start=True, half_day_end=True,
    )
    assert services.vacation_days(span) == 2.0

    whole = models.VacationRequest(start_date=date(2027, 3, 1), end_date=date(2027, 3, 3))
    assert services.vacation_days(whole) == 3.0

    half_single = models.VacationRequest(
        start_date=date(2027, 3, 1), end_date=date(2027, 3, 1), half_day_start=True
    )
    assert services.vacation_days(half_single) == 0.5


def test_weekend_stays_uncounted_with_halves(main):
    from app import models, services

    # Fr–Mo mit halbem Anfang und Ende: Fr 0,5 + Mo 0,5 = 1 Tag
    span = models.VacationRequest(
        start_date=date(2027, 3, 5), end_date=date(2027, 3, 8),
        half_day_start=True, half_day_end=True,
    )
    assert span.start_date.weekday() == 4 and span.end_date.weekday() == 0
    assert services.vacation_days(span) == 1.0


def test_half_day_costs_half_the_target_minutes(main):
    from app import crud, database, models, services

    db = database.SessionLocal()
    try:
        person = _employee(db)
        daily = int(round(person.daily_target_minutes))
        half = models.VacationRequest(
            user_id=person.id, start_date=date(2027, 3, 1), end_date=date(2027, 3, 1),
            status=models.VacationStatus.APPROVED, half_day_start=True,
        )
        assert services.vacation_minutes_in_range(
            person, half, date(2027, 3, 1), date(2027, 3, 1)
        ) == daily // 2
        whole = models.VacationRequest(
            user_id=person.id, start_date=date(2027, 3, 1), end_date=date(2027, 3, 1),
            status=models.VacationStatus.APPROVED,
        )
        assert services.vacation_minutes_in_range(
            person, whole, date(2027, 3, 1), date(2027, 3, 1)
        ) == daily
        assert crud is not None
    finally:
        db.close()


def test_summary_counts_half_days(client):
    from app import database, models

    db = database.SessionLocal()
    try:
        person = _employee(db)
        day = _weekday_in_current_year()
        vacation = _pending_vacation(
            db, person.id, start_date=day, end_date=day, half_day_start=True,
        )
        vacation.status = models.VacationStatus.APPROVED
        db.commit()
        db.refresh(person)
        assert _summary_used_days(db, person) == 0.5
    finally:
        db.close()


def test_daily_credit_is_halved(client):
    from app import database, models, services

    db = database.SessionLocal()
    try:
        person = _employee(db)
        day = date(date.today().year, 3, 1)
        while day.weekday() >= 5:  # auf einen Werktag schieben
            day += timedelta(days=1)
        vacation = _pending_vacation(
            db, person.id, start_date=day, end_date=day, half_day_start=True
        )
        vacation.status = models.VacationStatus.APPROVED
        db.commit()
        db.refresh(person)
        by_day = services.calculate_vacation_minutes_by_day(person, [vacation], day, day)
        assert by_day[day] == int(round(person.daily_target_minutes)) // 2
        assert models is not None
    finally:
        db.close()


def test_vacation_form_offers_half_days(client):
    _login(client)
    page = client.get("/records/vacations")
    assert page.status_code == 200
    assert 'name="half_day_start"' in page.text
    assert 'name="half_day_end"' in page.text


def test_submitting_a_half_day_stores_the_flag(client):
    from app import crud, database

    _login(client)
    day = date.today() + timedelta(days=7)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    response = client.post(
        "/vacations",
        data={
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "half_day_start": "on",
            "comment": "halber Tag",
            "csrf_token": _csrf(client, "/records/vacations"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    db = database.SessionLocal()
    try:
        admin = crud.get_user_by_username(db, "admin")
        vacation = crud.get_vacations_for_user(db, admin.id)[0]
        assert vacation.half_day_start is True
        # Eintägig: das zweite Kennzeichen bleibt aus, sonst wäre es doppelt.
        assert vacation.half_day_end is False
    finally:
        db.close()


def test_single_day_accepts_the_end_flag_alone(client):
    from app import crud, database

    _login(client)
    day = date.today() + timedelta(days=14)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    client.post(
        "/vacations",
        data={
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "half_day_end": "on",
            "csrf_token": _csrf(client, "/records/vacations"),
        },
    )
    db = database.SessionLocal()
    try:
        admin = crud.get_user_by_username(db, "admin")
        vacation = crud.get_vacations_for_user(db, admin.id)[0]
        assert vacation.half_day_start is True
        assert vacation.half_day_end is False
    finally:
        db.close()


def test_existing_requests_stay_whole_days(client):
    """Bestandsanträge ohne Kennzeichen zählen unverändert als ganze Tage."""
    from app import database, models, services

    db = database.SessionLocal()
    try:
        person = _employee(db)
        vacation = _pending_vacation(
            db, person.id, start_date=date(2027, 3, 1), end_date=date(2027, 3, 3)
        )
        assert vacation.half_day_start is False
        assert vacation.half_day_end is False
        assert services.vacation_days(vacation) == 3.0
        assert models is not None
    finally:
        db.close()


def test_half_days_appear_in_the_list(client):
    from app import database, models

    db = database.SessionLocal()
    try:
        from app import crud

        admin = crud.get_user_by_username(db, "admin")
        day = _weekday_in_current_year()
        vacation = _pending_vacation(
            db, admin.id, start_date=day, end_date=day, half_day_start=True
        )
        vacation.status = models.VacationStatus.APPROVED
        db.commit()
    finally:
        db.close()

    _login(client)
    assert "½" in client.get("/records/vacations").text


# --- Lizenz beantragen -----------------------------------------------------

def test_license_page_offers_a_request_link(client):
    _login(client)
    page = client.get("/admin/system/license")
    assert page.status_code == 200
    assert "Lizenz beantragen" in page.text
    assert "lic.dh-cloud.de" in page.text


def test_request_url_carries_context_but_no_secrets(client, main):
    from app import database, licensing

    db = database.SessionLocal()
    try:
        url = licensing.license_request_url(db)
    finally:
        db.close()

    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "lic.dh-cloud.de"
    assert parsed.path == "/request"

    query = parse_qs(parsed.query)
    assert query["product_id"] == ["erfassung"]
    assert query["deployment_id"][0].startswith("erfassung-")
    assert query["users_in_use"][0].isdigit()
    assert query["app_version"] == [main.APP_VERSION]
    # Nichts Geheimes und nichts Personenbezogenes.
    for forbidden in ("activation_key", "signature", "username", "email"):
        assert forbidden not in parsed.query


def test_request_url_uses_the_configured_server(client):
    from app import database, licensing

    config = licensing.load_config()
    config.server_url = "https://lizenz.intern.example"
    licensing.save_config(config)

    db = database.SessionLocal()
    try:
        url = licensing.license_request_url(db)
    finally:
        db.close()
    assert url.startswith("https://lizenz.intern.example/request?")


def test_activation_form_is_prefilled_with_the_default_server(client):
    _login(client)
    page = client.get("/admin/system/license")
    assert 'value="https://lic.dh-cloud.de"' in page.text
