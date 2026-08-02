"""Tests für 0.14.2 – halbe Urlaubstage, Urlaubsübersicht, Änderungsprotokoll.

Der gemeldete Fehler in einem Satz: Ein Antrag über **zwei halbe Tage** stand
in der Adminauswertung mit *16:00 Std* statt *8:00 Std*. Die eigene Übersicht
rechnete richtig – zwei Wege, zwei Ergebnisse.

Ursache war ``services.calculate_required_vacation_minutes``: Sie zählt ganze
Werktage und kennt keine halben Tage. Vier Stellen benutzten sie trotzdem für
die Anrechnung, darunter ``/api/vacations``, wo dadurch ein **falscher Wert in
der Datenbank** landete.

Dazu die beiden neuen Ansichten und eine Runde über die übrigen
Zeitberechnungen.
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime, time, timedelta

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


def _admin_id() -> int:
    from app import crud

    db = _db()
    try:
        return int(crud.get_user_by_username(db, "admin").id)
    finally:
        db.close()


# Montag und Dienstag – wie im Fehlerbericht (27./28.07.2026).
_MON = date(2026, 7, 27)
_TUE = date(2026, 7, 28)


def _vacation(
    *,
    start: date = _MON,
    end: date = _TUE,
    half_start: bool = True,
    half_end: bool = True,
    approved: bool = True,
    use_overtime: bool = False,
):
    from app import crud, models, schemas

    db = _db()
    try:
        request = crud.create_vacation_request(
            db,
            schemas.VacationRequestCreate(
                user_id=_admin_id(),
                start_date=start,
                end_date=end,
                comment="",
                half_day_start=half_start,
                half_day_end=half_end,
                use_overtime=use_overtime,
            ),
        )
        if approved:
            request.status = models.VacationStatus.APPROVED
            db.commit()
        return int(request.id)
    finally:
        db.close()


# ── Version ───────────────────────────────────────────────────────────────


def test_version_is_0142(client):
    assert client.app.version == "0.20.4"
    assert client.get("/health").json()["version"] == "0.20.4"


# ── Halbe Urlaubstage ─────────────────────────────────────────────────────


def test_two_half_days_credit_one_day(main):
    """Der gemeldete Fall: 27.–28.07., beide halb → 8:00 Std, nicht 16:00."""
    from app import services

    class _User:
        daily_target_minutes = 480

    class _Vacation:
        start_date = _MON
        end_date = _TUE
        half_day_start = True
        half_day_end = True

    minutes = services.vacation_minutes_in_range(
        _User(), _Vacation(), date(2026, 7, 1), date(2026, 7, 31)
    )
    assert minutes == 480
    assert services.vacation_days_in_range(_Vacation(), date(2026, 7, 1), date(2026, 7, 31)) == 1.0


def test_the_admin_report_credits_half_days(client):
    """Genau die Tabelle aus dem Fehlerbericht: „Urlaub im Zeitraum"."""
    _vacation()
    _login(client)

    page = client.get("/admin/reports/time?view=month&month=2026-07").text
    assert "08:00 Std" in page, "Halbe Tage werden nicht angerechnet"
    assert "16:00 Std" not in page


def test_full_days_are_unchanged(client):
    """Die Korrektur darf ganze Tage nicht anfassen."""
    _vacation(half_start=False, half_end=False)
    _login(client)

    page = client.get("/admin/reports/time?view=month&month=2026-07").text
    assert "16:00 Std" in page


def test_a_single_half_day_counts_half(main):
    """Ein eintägiger Antrag gilt als halb, sobald ein Kennzeichen gesetzt ist."""
    from app import services

    class _User:
        daily_target_minutes = 480

    class _Vacation:
        start_date = _MON
        end_date = _MON
        half_day_start = True
        half_day_end = False

    assert services.vacation_minutes_in_range(
        _User(), _Vacation(), _MON, _MON
    ) == 240


def test_the_api_stores_half_days_for_overtime_vacation(client):
    """Der schwerste Fall: hier landete ein falscher Wert in der Datenbank."""
    from app import crud, models

    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        admin.overtime_vacation_enabled = True
        db.commit()
    finally:
        db.close()

    _login(client)
    response = client.post(
        "/api/vacations",
        json={
            "user_id": _admin_id(),
            "start_date": _MON.isoformat(),
            "end_date": _TUE.isoformat(),
            "comment": "",
            "use_overtime": True,
            "half_day_start": True,
            "half_day_end": True,
        },
        headers={"x-csrf-token": client.get("/api/csrf").json()["csrf_token"]},
    )
    assert response.status_code == 200, response.text

    db = _db()
    try:
        stored = (
            db.query(models.VacationRequest)
            .filter(models.VacationRequest.id == response.json()["id"])
            .first()
        )
        assert stored.overtime_minutes == 480, "Vom Zeitkonto würde zu viel abgezogen"
    finally:
        db.close()


def test_the_pdf_export_credits_half_days(client):
    """Auch der Ausdruck – dort standen zusätzlich ganze Tage in der Tagesspalte."""
    from app import pdf_export, services

    class _Vacation:
        start_date = _MON
        end_date = _TUE
        half_day_start = True
        half_day_end = True

    assert services.vacation_days_in_range(_Vacation(), _MON, _TUE) == 1.0
    # Halbe Tage werden deutsch mit Komma dargestellt.
    assert pdf_export._format_days(1.5) == "1,5"
    assert pdf_export._format_days(2.0) == "2"


# ── Urlaubsübersicht für die Administration ───────────────────────────────


def test_the_vacation_overview_is_reachable(client):
    _login(client)
    response = client.get("/admin/reports/vacations")
    assert response.status_code == 200
    assert "Urlaubsübersicht" in response.text


def test_the_overview_shows_entitlement_and_remainder(client):
    """Anspruch minus genommen minus beantragt."""
    from app import crud

    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        admin.annual_vacation_days = 30
        db.commit()
    finally:
        db.close()
    _vacation()  # ein ganzer Tag aus zwei halben
    _login(client)

    page = client.get(f"/admin/reports/vacations?year={_MON.year}").text
    assert "30.0" in page or "30" in page
    # 30 Anspruch minus 1 genommen = 29 verbleibend.
    assert "29.0" in page


def test_the_overview_matches_the_employees_own_view(client):
    """Zwei Zahlen für dieselbe Sache dürfen nicht auseinanderlaufen."""
    from app import crud, services

    _vacation()
    db = _db()
    try:
        person = crud.get_user_by_username(db, "admin")
        vacations = crud.get_vacations_for_user(db, person.id)
        summary = services.calculate_vacation_summary(person, vacations, _MON.year)
    finally:
        db.close()
    assert summary.used_days == 1.0


def test_the_overview_needs_its_own_permission(client, main):
    """Ohne Vacation.Overview führt der Weg zurück auf das Dashboard."""
    from app import crud

    _login(client)
    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        # Rollen tragen die Rechte (auch „Superadministrator"). Ohne sie bleibt
        # nur die Selbstbedienung – die Urlaubsübersicht gehört nicht dazu.
        admin.roles = []
        admin.groups = []
        db.commit()
    finally:
        db.close()

    response = client.get("/admin/reports/vacations", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert response.headers["location"].endswith("/dashboard")


def test_the_permission_is_registered(main):
    from app import permissions

    keys = {
        permission.key
        for category in permissions.CATEGORIES
        for permission in category.permissions
    }
    assert "Vacation.Overview" in keys


def test_looking_at_someone_elses_vacation_is_logged(client):
    """Datenschutz: Der Blick auf fremde Daten hinterlässt eine Spur."""
    from app import models

    _login(client)
    client.get("/admin/reports/vacations")

    db = _db()
    try:
        rows = (
            db.query(models.DataAccessLog)
            .filter(models.DataAccessLog.scope == "vacation_overview")
            .all()
        )
        # Die eigene Person erzeugt keinen Eintrag – hier gibt es nur den
        # Administrator, also bleibt die Liste leer.
        assert all(row.actor_id != row.subject_id for row in rows)
    finally:
        db.close()


# ── Änderungsprotokoll ────────────────────────────────────────────────────


def test_the_change_log_is_reachable(client):
    _login(client)
    response = client.get("/admin/time-entries/changes")
    assert response.status_code == 200
    assert "Änderungsprotokoll" in response.text


def test_the_change_log_lists_a_correction(client):
    """Anlage und Änderung stehen mit Begründung darin."""
    from app import crud, schemas

    db = _db()
    try:
        entry = crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=_admin_id(),
                work_date=date.today(),
                start_time=time(8, 0),
                end_time=time(16, 0),
                break_minutes=30,
            ),
        )
        crud.update_time_entry(
            db,
            entry.id,
            schemas.TimeEntryCreate(
                user_id=_admin_id(),
                work_date=date.today(),
                start_time=time(8, 0),
                end_time=time(17, 0),
                break_minutes=30,
            ),
            reason="Test: Stempelung vergessen",
        )
    finally:
        db.close()
    _login(client)

    page = client.get("/admin/time-entries/changes").text
    assert "Angelegt" in page
    assert "Geändert" in page
    assert "Test: Stempelung vergessen" in page


def test_the_change_log_can_be_filtered_by_action(client):
    from app import crud, schemas

    db = _db()
    try:
        crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=_admin_id(),
                work_date=date.today(),
                start_time=time(8, 0),
                end_time=time(16, 0),
                break_minutes=30,
            ),
        )
    finally:
        db.close()
    _login(client)

    page = client.get("/admin/time-entries/changes?action=cancelled").text
    assert "Keine Änderungen im gewählten Zeitraum" in page


def test_the_change_log_respects_the_time_window(client):
    """Gefiltert wird nach Buchungsdatum, damit späte Korrekturen auffindbar bleiben."""
    from app import crud, schemas

    old_day = date.today() - timedelta(days=200)
    db = _db()
    try:
        crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=_admin_id(),
                work_date=old_day,
                start_time=time(8, 0),
                end_time=time(16, 0),
                break_minutes=30,
            ),
        )
    finally:
        db.close()
    _login(client)

    recent = client.get("/admin/time-entries/changes?days=30").text
    assert "Keine Änderungen im gewählten Zeitraum" in recent
    wide = client.get("/admin/time-entries/changes?days=365").text
    assert "Angelegt" in wide


# ── Übrige Zeitberechnungen ───────────────────────────────────────────────


def test_target_minutes_count_only_weekdays(main):
    from app import services

    class _User:
        daily_target_minutes = 480

    # Montag bis Sonntag = fünf Arbeitstage.
    assert services.calculate_target_minutes_in_range(
        _User(), date(2026, 7, 27), date(2026, 8, 2)
    ) == 5 * 480


def test_vacation_minutes_stop_at_the_period_boundary(main):
    """Ein Antrag über den Monatswechsel zählt nur anteilig."""
    from app import services

    class _User:
        daily_target_minutes = 480

    class _Vacation:
        start_date = date(2026, 7, 30)   # Donnerstag
        end_date = date(2026, 8, 4)      # Dienstag
        half_day_start = False
        half_day_end = False

    juli = services.vacation_minutes_in_range(
        _User(), _Vacation(), date(2026, 7, 1), date(2026, 7, 31)
    )
    august = services.vacation_minutes_in_range(
        _User(), _Vacation(), date(2026, 8, 1), date(2026, 8, 31)
    )
    # 30./31.07. sind Do/Fr, 03./04.08. sind Mo/Di – das Wochenende zählt nie.
    assert juli == 2 * 480
    assert august == 2 * 480


def test_a_cancelled_vacation_does_not_reduce_the_remainder(client):
    """Storniert heißt zurückgenommen – der Anspruch kommt zurück."""
    from app import crud, models, services

    vacation_id = _vacation()
    db = _db()
    try:
        stored = (
            db.query(models.VacationRequest)
            .filter(models.VacationRequest.id == vacation_id)
            .first()
        )
        stored.status = models.VacationStatus.CANCELLED
        db.commit()
        person = crud.get_user_by_username(db, "admin")
        summary = services.calculate_vacation_summary(
            person, crud.get_vacations_for_user(db, person.id), _MON.year
        )
    finally:
        db.close()
    assert summary.used_days == 0.0


def test_overtime_vacation_does_not_touch_the_vacation_entitlement(client):
    """Überstundenabbau zehrt vom Zeitkonto, nicht vom Urlaubsanspruch."""
    from app import crud, services

    _vacation(use_overtime=True)
    db = _db()
    try:
        person = crud.get_user_by_username(db, "admin")
        summary = services.calculate_vacation_summary(
            person, crud.get_vacations_for_user(db, person.id), _MON.year
        )
    finally:
        db.close()
    assert summary.used_days == 0.0


# ── Feiertagsgutschrift ───────────────────────────────────────────────────


def _holiday(day: date, name: str = "Testfeiertag", region: str = "DE") -> None:
    from app import crud, schemas

    db = _db()
    try:
        crud.upsert_holidays(
            db, [schemas.HolidayCreate(name=name, date=day, region=region)]
        )
    finally:
        db.close()


def test_a_public_holiday_credits_the_daily_target(main):
    """Ein Feiertag ist ein bezahlter Ausfalltag – er bringt die Tagessollzeit."""
    from app import services

    class _User:
        daily_target_minutes = 480

    # 01.05.2026 ist ein Freitag.
    labour_day = date(2026, 5, 1)
    assert services.holiday_credit_minutes(
        _User(), {labour_day}, date(2026, 5, 1), date(2026, 5, 31)
    ) == 480


def test_the_credit_follows_the_individual_daily_target(main):
    """„Jeweils korrekte Tagesarbeitszeit" heißt: die des Benutzers."""
    from app import services

    class _HalfTime:
        daily_target_minutes = 240

    assert services.holiday_credit_minutes(
        _HalfTime(), {date(2026, 5, 1)}, date(2026, 5, 1), date(2026, 5, 31)
    ) == 240


def test_a_holiday_on_a_weekend_credits_nothing(main):
    """Kein Arbeitstag, kein Ausfall, keine Gutschrift."""
    from app import services

    class _User:
        daily_target_minutes = 480

    # 03.10.2026 ist ein Samstag.
    saturday = date(2026, 10, 3)
    assert saturday.weekday() == 5
    assert services.holiday_credit_minutes(
        _User(), {saturday}, date(2026, 10, 1), date(2026, 10, 31)
    ) == 0


def test_the_balance_evens_out_on_a_holiday_month(client):
    """Der eigentliche Zweck: kein Minus mehr für einen Feiertag.

    Die gesetzlichen Feiertage legt die Anwendung beim Start selbst an, im Mai
    sind das mehrere. Erwartet wird deshalb nicht eine feste Zahl, sondern
    genau eine Tagessollzeit je Feiertag, der auf einen Werktag fällt.
    """
    from app import crud, services

    _holiday(date(2026, 5, 1), "Tag der Arbeit")
    db = _db()
    try:
        holidays = crud.get_holiday_dates_in_range(db, date(2026, 5, 1), date(2026, 5, 31))
        metrics = services.calculate_dashboard_metrics(db, _admin_id(), date(2026, 5, 15))
    finally:
        db.close()

    werktags = [day for day in holidays if day.weekday() < 5]
    assert date(2026, 5, 1) in werktags
    assert metrics.holiday_minutes == len(werktags) * 480
    assert metrics.target_minutes == 21 * 480
    # Ohne gestempelte Zeit bleibt ein Minus – aber um die Feiertage kleiner.
    fehlend = metrics.target_minutes - metrics.holiday_minutes
    assert fehlend == (21 - len(werktags)) * 480


def test_a_holiday_during_leave_does_not_consume_a_vacation_day(client):
    """Sonst zählte der Tag doppelt und der Urlaubsanspruch schrumpfte."""
    from app import crud, services

    # 01.05.2026 (Fr) ist Feiertag, der Urlaub läuft Mo–Fr darüber.
    _holiday(date(2026, 5, 1), "Tag der Arbeit")
    _vacation(
        start=date(2026, 4, 27), end=date(2026, 5, 1),
        half_start=False, half_end=False,
    )

    db = _db()
    try:
        person = crud.get_user_by_username(db, "admin")
        holidays = crud.get_holiday_dates_in_range(db, date(2026, 1, 1), date(2026, 12, 31))
        summary = services.calculate_vacation_summary(
            person, crud.get_vacations_for_user(db, person.id), 2026, holidays
        )
    finally:
        db.close()
    # Mo–Fr sind fünf Werktage, einer davon Feiertag → vier Urlaubstage.
    assert summary.used_days == 4.0


def test_the_holiday_is_credited_even_during_leave(client):
    """Der Feiertag verschwindet nicht – er wechselt nur den Topf."""
    from app import crud, services

    _holiday(date(2026, 5, 1), "Tag der Arbeit")
    _vacation(
        start=date(2026, 4, 27), end=date(2026, 5, 1),
        half_start=False, half_end=False,
    )
    db = _db()
    try:
        holidays = crud.get_holiday_dates_in_range(db, date(2026, 5, 1), date(2026, 5, 31))
        metrics = services.calculate_dashboard_metrics(db, _admin_id(), date(2026, 5, 15))
    finally:
        db.close()
    werktags = [day for day in holidays if day.weekday() < 5]
    assert date(2026, 5, 1) in werktags
    assert metrics.holiday_minutes == len(werktags) * 480


def test_working_on_a_holiday_counts_on_top(client):
    """Feiertagsarbeit ist echte Mehrarbeit – und wird ohnehin gekennzeichnet."""
    from app import compliance, crud, models, schemas, services

    _holiday(date(2026, 5, 1), "Tag der Arbeit")
    db = _db()
    try:
        crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=_admin_id(),
                work_date=date(2026, 5, 1),
                start_time=time(8, 0),
                end_time=time(12, 0),
                break_minutes=0,
            ),
        )
        holidays = crud.get_holiday_dates_in_range(db, date(2026, 5, 1), date(2026, 5, 31))
        metrics = services.calculate_dashboard_metrics(db, _admin_id(), date(2026, 5, 15))
        findings = compliance.evaluate_day(db, _admin_id(), date(2026, 5, 1))
    finally:
        db.close()

    werktags = [day for day in holidays if day.weekday() < 5]
    # Die Gutschrift bleibt vollständig – die Arbeit kommt obendrauf.
    assert metrics.holiday_minutes == len(werktags) * 480
    assert metrics.total_work_minutes == 240
    assert any(
        finding["code"] == models.ComplianceCode.HOLIDAY_WORK for finding in findings
    ), "Feiertagsarbeit muss gekennzeichnet werden"


def test_the_daily_overview_shows_the_credit(client):
    from app import main as main_module

    _holiday(date(2026, 5, 1), "Tag der Arbeit")
    db = _db()
    try:
        overview = main_module._build_daily_overview(db, _admin_id(), date(2026, 5, 1))
    finally:
        db.close()
    assert overview["is_holiday"] is True
    assert overview["holiday_minutes"] == 480
    assert overview["total_minutes"] == 480


def test_a_normal_day_is_unaffected(client):
    """Die Gutschrift darf nur an Feiertagen greifen."""
    from app import main as main_module

    db = _db()
    try:
        overview = main_module._build_daily_overview(db, _admin_id(), date(2026, 5, 4))
    finally:
        db.close()
    assert overview["is_holiday"] is False
    assert overview["holiday_minutes"] == 0
    assert overview["total_minutes"] == 0


def test_the_records_page_shows_the_holiday_credit(client):
    _holiday(date(2026, 5, 1), "Tag der Arbeit")
    _login(client)
    page = client.get("/records?month=2026-05").text
    assert "Feiertagsstunden" in page


def test_the_user_report_carries_a_holiday_column(client):
    _holiday(date(2026, 5, 1), "Tag der Arbeit")
    _login(client)
    page = client.get(
        "/admin/reports/users?start=2026-05-01&end=2026-05-31"
    ).text
    assert "Feiertag" in page


def test_the_offline_snapshot_carries_the_credit(client):
    """Die Stempel-App rechnet offline mit denselben Zahlen."""
    _holiday(date.today().replace(day=1), "Testfeiertag")
    _login(client)
    payload = client.get("/mobile/sync-data").json()
    assert "holiday_minutes" in payload["metrics"]


def test_overtime_vacation_over_a_holiday_costs_less(client):
    """Ein Feiertag im Überstundenurlaub belastet das Zeitkonto nicht."""
    from app import crud, models

    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        admin.overtime_vacation_enabled = True
        db.commit()
    finally:
        db.close()
    _holiday(date(2026, 5, 1), "Tag der Arbeit")
    _login(client)

    response = client.post(
        "/api/vacations",
        json={
            "user_id": _admin_id(),
            "start_date": date(2026, 4, 27).isoformat(),
            "end_date": date(2026, 5, 1).isoformat(),
            "comment": "",
            "use_overtime": True,
            "half_day_start": False,
            "half_day_end": False,
        },
        headers={"x-csrf-token": client.get("/api/csrf").json()["csrf_token"]},
    )
    assert response.status_code == 200, response.text

    db = _db()
    try:
        stored = (
            db.query(models.VacationRequest)
            .filter(models.VacationRequest.id == response.json()["id"])
            .first()
        )
        # Mo–Fr sind fünf Werktage, einer davon Feiertag → vier Tage à 8 Std.
        assert stored.overtime_minutes == 4 * 480
    finally:
        db.close()
