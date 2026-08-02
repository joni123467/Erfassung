"""Tests für 0.20.2 – Grenzfälle der Jahresprüfung Sonn- und Nachtarbeit.

Was diese Fassung an 0.20.0/0.20.1 korrigiert:

* **Die Nachtarbeitsgrenze war um eine Minute zu großzügig.** § 2 Abs. 4 ArbZG
  verlangt Arbeit, die **mehr als** zwei Stunden der Nachtzeit umfasst. Der
  Vergleich stand auf ``>=``; eine punktgenaue Zweistundenschicht galt damit
  fälschlich als Nachtarbeit.
* **Die Sonntagsprüfung kannte den Beschäftigungszeitraum nicht.** Sie rechnete
  über das ganze Kalenderjahr. Wer im September eintrat, bekam die Sonntage von
  Januar bis August als „beschäftigungsfrei" gutgeschrieben – Sonntage, an
  denen es gar kein Beschäftigungsverhältnis gab.
* **Der Jahreswechsel fiel durch.** Eine am 31. Dezember begonnene Schicht
  reicht in den 1. Januar. War das ein Sonntag, wurde er im neuen Jahr nicht
  als gearbeitet erkannt, weil nur über ``work_date`` geladen wurde.
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import licensed_env


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

BERLIN = ZoneInfo("Europe/Berlin")


def _csrf(client, url: str) -> str:
    match = _CSRF_RE.search(client.get(url).text)
    assert match, f"kein CSRF-Token auf {url}"
    return match.group(1)


def _login(client, username: str = "admin", password: str = "Admin!0000") -> None:
    response = client.post(
        "/login",
        data={"username": username, "password": password,
              "csrf_token": _csrf(client, "/login")},
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


def _entry(day: date, start: time, end: time, *, breaks: int = 0,
           user_id: int | None = None):
    """Buchung mit gepflegten UTC-Stempeln; das Ende darf am Folgetag liegen."""
    from app import database, models

    started = datetime.combine(day, start).replace(tzinfo=BERLIN)
    ended = datetime.combine(day, end).replace(tzinfo=BERLIN)
    if ended <= started:
        ended += timedelta(days=1)
    with database.SessionLocal() as db:
        row = models.TimeEntry(
            user_id=user_id or _admin_id(), work_date=day,
            start_time=start, end_time=end,
            status=models.TimeEntryStatus.APPROVED, break_minutes=breaks,
            break_rule=models.BreakRule.ACTUAL, tz_name="Europe/Berlin",
            started_at_utc=started.astimezone(timezone.utc).replace(tzinfo=None),
            ended_at_utc=ended.astimezone(timezone.utc).replace(tzinfo=None),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def _set_employment(start: date | None, end: date | None = None,
                    user_id: int | None = None) -> None:
    from app import database, models

    with database.SessionLocal() as db:
        person = db.query(models.User).filter(
            models.User.id == (user_id or _admin_id())
        ).first()
        person.employment_start_date = start
        person.employment_end_date = end
        db.commit()


def _report(year: int, reference: date, user_id: int | None = None) -> dict:
    from app import compliance

    with _db() as db:
        return compliance.annual_compliance_report(
            db, user_id or _admin_id(), year, reference_date=reference
        )


# ── Version ───────────────────────────────────────────────────────────────


def test_version_is_0202(client):
    assert client.app.version == "0.20.2"
    assert client.get("/health").json()["version"] == "0.20.2"


def test_service_worker_carries_the_version(client):
    assert "0.20.2" in client.get("/sw.js").text


# ── 1. Nachtarbeitsgrenze: mehr als zwei Stunden ──────────────────────────


def test_exactly_120_night_minutes_are_not_night_work(main):
    """§ 2 Abs. 4 ArbZG verlangt **mehr als** zwei Stunden."""
    from app import compliance

    entry = _entry(date(2026, 2, 3), time(23, 0), time(1, 0))
    assert compliance.night_minutes([entry]) == 120
    assert compliance.is_night_work(120) is False


def test_121_night_minutes_are_night_work(main):
    from app import compliance

    entry = _entry(date(2026, 2, 5), time(23, 0), time(1, 1))
    assert compliance.night_minutes([entry]) == 121
    assert compliance.is_night_work(121) is True


def test_threshold_is_evaluated_in_exactly_one_place(main):
    """Tagesfeststellung und Jahreszählung dürfen nie auseinanderlaufen.

    Genau **ein** Vergleich gegen die Schwelle – ein zweiter, womöglich mit
    ``>=`` statt ``>``, wäre genau der Fehler aus 0.20.0.
    """
    import pathlib
    import re

    from app import compliance

    source = pathlib.Path("app/compliance.py").read_text(encoding="utf-8")
    # Vergleichsoperatoren, aber ausdrücklich **nicht** die Zuweisung: ein
    # einzelnes ``=`` gehört zur Definition der Konstanten.
    operator = r"(?:[<>]=?|[=!]=)"
    comparisons = re.findall(
        rf"{operator}\s*NIGHT_WORK_THRESHOLD_MINUTES"
        rf"|NIGHT_WORK_THRESHOLD_MINUTES\s*{operator}",
        source,
    )
    assert len(comparisons) == 1, f"mehr als ein Vergleich: {comparisons}"
    assert compliance.is_night_work(compliance.NIGHT_WORK_THRESHOLD_MINUTES) is False
    assert compliance.is_night_work(compliance.NIGHT_WORK_THRESHOLD_MINUTES + 1) is True


def test_breaks_inside_the_night_window_are_subtracted(main):
    """Eine gebuchte Pause ist keine Nachtarbeit."""
    from app import compliance, database, models

    entry = _entry(date(2026, 2, 9), time(22, 0), time(2, 0))
    with database.SessionLocal() as db:
        row = db.query(models.TimeEntry).filter(
            models.TimeEntry.id == entry.id
        ).first()
        start = datetime(2026, 2, 10, 0, 0, tzinfo=BERLIN)
        # ``minutes`` ist eine abgeleitete Eigenschaft – gesetzt werden nur
        # Beginn und Ende.
        db.add(models.BreakInterval(
            entry_id=row.id,
            started_at_utc=start.astimezone(timezone.utc).replace(tzinfo=None),
            ended_at_utc=(start + timedelta(minutes=45)).astimezone(
                timezone.utc).replace(tzinfo=None),
            tz_name="Europe/Berlin",
        ))
        db.commit()
        row = db.query(models.TimeEntry).filter(
            models.TimeEntry.id == entry.id
        ).first()
        # 23:00–02:00 wären 180 Nachtminuten, abzüglich 45 Pausenminuten.
        assert compliance.night_minutes([row]) == 135


def test_evening_work_until_2230_is_no_night_work(main):
    """Die Nachtzeit beginnt um 23:00 Uhr."""
    from app import compliance

    entry = _entry(date(2026, 2, 11), time(14, 0), time(22, 30))
    assert compliance.night_minutes([entry]) == 0
    assert compliance.is_night_work(0) is False


def test_night_shift_over_eight_hours_is_flagged(main):
    """21:00–06:00 mit mehr als acht Stunden wird gekennzeichnet (§ 6 Abs. 2)."""
    from app import compliance

    day = date(2026, 2, 16)
    _entry(day, time(21, 0), time(6, 0))
    with _db() as db:
        codes = {f["code"] for f in compliance.evaluate_day(db, _admin_id(), day)}
    assert compliance.NIGHT_WORK_OVER_8H in codes


def test_dst_change_is_handled_over_utc(main):
    """Zeitumstellung: gerechnet wird über UTC, nicht über naive Ortszeiten."""
    from app import compliance

    # In der Nacht zum 29.03.2026 springt die Uhr von 02:00 auf 03:00.
    # 23:00–06:00 Ortszeit sind damit real nur sechs Stunden.
    entry = _entry(date(2026, 3, 28), time(23, 0), time(6, 0))
    assert compliance.night_minutes([entry]) == 360


def test_47_night_days_do_not_trigger_the_indication(main):
    from app import compliance

    _set_employment(date(2026, 1, 1))
    day = date(2026, 1, 1)
    added = 0
    while added < 47:
        _entry(day, time(23, 0), time(3, 0))
        day += timedelta(days=2)
        added += 1
    report = _report(2026, date(2026, 12, 31))
    assert report["night_work_days"] == 47
    assert report["night_worker_by_days"] is False


def test_48_night_days_trigger_the_indication(main):
    from app import compliance

    _set_employment(date(2026, 1, 1))
    day = date(2026, 1, 1)
    for _ in range(48):
        _entry(day, time(23, 0), time(3, 0))
        day += timedelta(days=2)
    report = _report(2026, date(2026, 12, 31))
    assert report["night_work_days"] == 48
    assert report["night_worker_by_days"] is True


# ── 2. Beschäftigungszeitraum ─────────────────────────────────────────────


def test_worked_sunday_is_counted(main):
    _set_employment(date(2026, 1, 1))
    _entry(date(2026, 1, 4), time(8, 0), time(16, 0))   # Sonntag
    report = _report(2026, date(2026, 1, 31))
    assert report["worked_sundays"] == 1


def test_free_sunday_is_counted(main):
    _set_employment(date(2026, 1, 1))
    report = _report(2026, date(2026, 1, 31))
    assert report["worked_sundays"] == 0
    assert report["free_sundays"] > 0


def test_saturday_night_shift_into_sunday_counts_as_sunday_work(main):
    """Eine Samstagnachtschicht reicht in den Sonntag."""
    _set_employment(date(2026, 1, 1))
    _entry(date(2026, 1, 3), time(22, 0), time(6, 0))   # Sa → So
    report = _report(2026, date(2026, 1, 31))
    assert report["worked_sundays"] == 1


def test_sundays_before_employment_start_do_not_count(main):
    """Vor dem Eintritt gab es kein Beschäftigungsverhältnis."""
    _set_employment(date(2026, 11, 1))
    report = _report(2026, date(2026, 12, 31))
    assert report["period_start"] == date(2026, 11, 1)
    # November und Dezember 2026 haben zusammen neun Sonntage.
    assert report["required_free_sundays"] == 9
    assert report["free_sundays"] == 9


def test_sundays_after_employment_end_do_not_count(main):
    _set_employment(date(2026, 1, 1), date(2026, 6, 30))
    report = _report(2026, date(2026, 12, 31))
    assert report["period_end"] == date(2026, 6, 30)
    assert report["free_sundays"] == 26      # Sonntage im ersten Halbjahr 2026
    assert report["required_free_sundays"] == 15


def test_unknown_start_never_yields_a_positive_verdict(main):
    """Ohne Eintrittsdatum kein „Sonntagsminimum erfüllt"."""
    _set_employment(None)
    report = _report(2026, date(2026, 12, 31))
    assert report["employment_period_known"] is False
    assert report["sunday_rule_met"] is False
    assert report["sunday_rule_impossible"] is False


def test_end_without_start_yields_no_positive_verdict(main):
    """Nur ein Austritt genügt nicht – der Beginn fehlt weiterhin."""
    _set_employment(None, date(2026, 6, 30))
    report = _report(2026, date(2026, 12, 31))
    assert report["employment_period_known"] is False
    assert report["sunday_rule_met"] is False


def test_required_never_exceeds_the_sundays_in_the_period(main):
    """Ein unerfüllbares Soll wäre keine brauchbare Aussage."""
    _set_employment(date(2026, 12, 1))
    report = _report(2026, date(2026, 12, 31))
    assert report["required_free_sundays"] == 4
    assert report["required_free_sundays"] <= 15


# ── 3. Jahreswechsel ──────────────────────────────────────────────────────


def test_new_years_eve_shift_counts_in_the_new_year(main):
    """31.12.2022 23:00–02:00; der 01.01.2023 ist ein Sonntag."""
    assert date(2023, 1, 1).weekday() == 6, "Testannahme: Neujahr 2023 ist Sonntag"
    _set_employment(date(2020, 1, 1))
    _entry(date(2022, 12, 31), time(23, 0), time(2, 0))
    report = _report(2023, date(2023, 1, 15))
    assert report["worked_sundays"] == 1


def test_the_carried_over_shift_is_no_night_day_of_the_new_year(main):
    """Der mitgeladene Vortag zählt nicht als Nachtarbeitstag des neuen Jahres."""
    _set_employment(date(2020, 1, 1))
    _entry(date(2022, 12, 31), time(23, 0), time(4, 0))
    report = _report(2023, date(2023, 1, 15))
    assert report["night_work_days"] == 0


# ── 4. Validierung des Beschäftigungszeitraums ────────────────────────────


def test_end_before_start_is_refused(main):
    from app import schemas

    with pytest.raises(ValueError):
        schemas.UserUpdate(
            username="a", full_name="A", email="a@example.org",
            employment_start_date=date(2026, 5, 1),
            employment_end_date=date(2026, 1, 1),
        )


def test_same_start_and_end_is_allowed(main):
    from app import schemas

    payload = schemas.UserUpdate(
        username="a", full_name="A", email="a@example.org",
        employment_start_date=date(2026, 5, 1),
        employment_end_date=date(2026, 5, 1),
    )
    assert payload.employment_end_date == payload.employment_start_date


def test_start_only_is_allowed(main):
    from app import schemas

    payload = schemas.UserUpdate(
        username="a", full_name="A", email="a@example.org",
        employment_start_date=date(2026, 5, 1),
    )
    assert payload.employment_end_date is None


def test_server_refuses_a_reversed_period_in_the_form(client):
    """Nicht nur HTML-Validierung: Der Server weist es ebenfalls ab."""
    from app import crud, database

    _login(client)
    response = client.post(
        f"/admin/users/{_admin_id()}/update",
        data={
            "csrf_token": _csrf(client, f"/admin/users/{_admin_id()}"),
            "username": "admin", "full_name": "Administrator",
            "email": "admin@example.org", "standard_weekly_hours": "40",
            "annual_vacation_days": "30", "vacation_carryover_days": "0",
            "employment_start_date": "2026-05-01",
            "employment_end_date": "2026-01-01",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "error=" in response.headers["location"]
    with database.SessionLocal() as db:
        person = crud.get_user_by_username(db, "admin")
        assert person.employment_end_date is None, "ungültiger Zeitraum wurde gespeichert"


# ── 5. Migration 22 ───────────────────────────────────────────────────────


def test_migration_22_is_the_last_entry(main):
    from app import db_migrations

    version, function = db_migrations.MIGRATIONS[-1]
    assert version == 22
    assert function is db_migrations._add_employment_period


def test_columns_exist_after_startup(main):
    from sqlalchemy import inspect

    from app import database

    columns = {c["name"] for c in inspect(database.engine).get_columns("users")}
    assert {"employment_start_date", "employment_end_date"} <= columns


def test_existing_accounts_keep_null(main):
    from app import crud, database

    with database.SessionLocal() as db:
        person = crud.get_user_by_username(db, "admin")
        assert person.employment_start_date is None
        assert person.employment_end_date is None


def test_migration_is_idempotent(main):
    from sqlalchemy import inspect, text

    from app import database, db_migrations

    with database.engine.begin() as connection:
        before = connection.execute(text("SELECT COUNT(*) FROM users")).scalar()

    for _ in range(3):
        db_migrations._add_employment_period(database.engine)

    columns = {c["name"] for c in inspect(database.engine).get_columns("users")}
    assert {"employment_start_date", "employment_end_date"} <= columns
    with database.engine.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar() == before


# ── 6. Revisionssichere Jahresfeststellung ────────────────────────────────


def _work_every_sunday(year: int, limit: int) -> None:
    """Die ersten ``limit`` Sonntage eines Jahres bearbeiten."""
    day = date(year, 1, 1)
    day += timedelta(days=(6 - day.weekday()) % 7)
    for _ in range(limit):
        _entry(day, time(8, 0), time(16, 0))
        day += timedelta(days=7)


def _annual_flag(user_id: int | None = None):
    from app import compliance, models

    with _db() as db:
        return (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.user_id == (user_id or _admin_id()))
            .filter(models.ComplianceFlag.code == compliance.FREE_SUNDAYS_UNDER_15)
            .first()
        )


def test_unreachable_minimum_creates_a_critical_finding(main):
    from app import compliance

    _set_employment(date(2026, 1, 1))
    # 2026 hat 52 Sonntage; 38 gearbeitete lassen höchstens 14 freie zu.
    _work_every_sunday(2026, 38)
    with _db() as db:
        compliance.refresh_annual_compliance(db, reference_date=date(2026, 12, 31))

    flag = _annual_flag()
    assert flag is not None
    assert flag.severity == compliance.SEVERITY_CRITICAL
    assert flag.state == "detected"


def test_corrected_data_resolves_the_finding(main):
    from app import compliance, database, models

    _set_employment(date(2026, 1, 1))
    _work_every_sunday(2026, 38)
    with _db() as db:
        compliance.refresh_annual_compliance(db, reference_date=date(2026, 12, 31))
    assert _annual_flag() is not None

    # Korrektur: Die Sonntagsbuchungen werden storniert.
    with database.SessionLocal() as db:
        for row in db.query(models.TimeEntry).all():
            row.status = models.TimeEntryStatus.CANCELLED
        db.commit()
    with _db() as db:
        compliance.refresh_annual_compliance(db, reference_date=date(2026, 12, 31))

    flag = _annual_flag()
    assert flag is not None, "die Feststellung darf nicht gelöscht werden"
    assert flag.state == models.ComplianceState.RESOLVED


def test_acknowledged_finding_reopens_on_changed_data(main):
    from app import compliance, crud, database, models

    _set_employment(date(2026, 1, 1))
    _work_every_sunday(2026, 38)
    with _db() as db:
        compliance.refresh_annual_compliance(db, reference_date=date(2026, 12, 31))
    flag_id = _annual_flag().id

    with database.SessionLocal() as db:
        admin = crud.get_user_by_username(db, "admin")
        compliance.acknowledge(db, flag_id, user=admin, note="Wird geprüft")
    with _db() as db:
        assert compliance.get_flag(db, flag_id).state == models.ComplianceState.ACKNOWLEDGED

    # Weitere Sonntagsarbeit ändert den Datenstand.
    day = date(2026, 1, 1)
    day += timedelta(days=(6 - day.weekday()) % 7) + timedelta(days=7 * 38)
    _entry(day, time(8, 0), time(16, 0))
    with _db() as db:
        compliance.refresh_annual_compliance(db, reference_date=date(2026, 12, 31))
        assert compliance.get_flag(db, flag_id).state == models.ComplianceState.REOPENED


def test_history_stays_append_only(main):
    from app import compliance

    _set_employment(date(2026, 1, 1))
    _work_every_sunday(2026, 38)
    with _db() as db:
        compliance.refresh_annual_compliance(db, reference_date=date(2026, 12, 31))
    flag_id = _annual_flag().id
    with _db() as db:
        first = len(compliance.history(db, flag_id))
        compliance.refresh_annual_compliance(db, reference_date=date(2026, 12, 31))
        assert len(compliance.history(db, flag_id)) >= first


def test_no_finding_without_employment_start(main):
    """Ohne Eintritt wird auch kein Verstoß behauptet."""
    from app import compliance

    _set_employment(None)
    _work_every_sunday(2026, 38)
    with _db() as db:
        compliance.refresh_annual_compliance(db, reference_date=date(2026, 12, 31))
    assert _annual_flag() is None


# ── 7. Rechte und Oberfläche ──────────────────────────────────────────────


def _grant_only(*keys: str, scope: str = "all") -> None:
    from app import crud, database

    with database.SessionLocal() as db:
        role = crud.create_role(db, name="Testrolle", description="", is_active=True,
                                permissions={key: scope for key in keys})
        admin = crud.get_user_by_username(db, "admin")
        admin.roles = [role]
        admin.groups = []
        db.commit()


def test_compliance_page_shows_the_annual_overview(client):
    _login(client)
    html = client.get("/admin/compliance").text
    assert "Jahresprüfung Sonn- und Nachtarbeit" in html
    assert "Freie Sonntage" in html
    assert "Nachtarbeitstage" in html


def test_missing_employment_start_is_shown(client):
    """Bestandskonten haben kein Eintrittsdatum – das muss sichtbar sein."""
    _login(client)
    assert "Beschäftigungsbeginn fehlt" in client.get("/admin/compliance").text


def test_time_view_scope_still_filters_people(client):
    """Der Geltungsbereich bestimmt weiterhin die sichtbaren Personen."""
    from app import crud, database, schemas, security

    with database.SessionLocal() as db:
        person = crud.create_user(db, schemas.UserCreate(
            username="fremd", full_name="Fremde Person",
            email="fremd@example.org", password="Fremd!00000",
        ))
        person.password_hash = security.hash_password("Fremd!00000")
        person.must_change_password = False
        db.commit()

    _grant_only("Time.View", scope="self")
    _login(client)
    html = client.get("/admin/compliance").text
    assert "Fremde Person" not in html


def test_no_management_forms_without_the_right(client):
    _login(client)
    _grant_only("Time.View")
    html = client.get("/admin/compliance").text
    assert "/acknowledge" not in html


def test_user_form_offers_both_dates(client):
    _login(client)
    html = client.get("/admin/users/new").text
    assert 'name="employment_start_date"' in html
    assert 'name="employment_end_date"' in html
    assert "Beschäftigungsbeginn" in html


def test_create_stores_both_dates(client):
    from app import crud, database

    _login(client)
    response = client.post(
        "/admin/users/create",
        data={
            "csrf_token": _csrf(client, "/admin/users/new"),
            "username": "neue", "full_name": "Neue Person",
            "email": "neue@example.org", "password": "Passwort!01",
            "password_confirm": "Passwort!01",
            "standard_weekly_hours": "40", "annual_vacation_days": "30",
            "vacation_carryover_days": "0",
            "employment_start_date": "2026-03-01",
            "employment_end_date": "2026-09-30",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with database.SessionLocal() as db:
        person = crud.get_user_by_username(db, "neue")
        assert person.employment_start_date == date(2026, 3, 1)
        assert person.employment_end_date == date(2026, 9, 30)


def test_update_stores_both_dates_and_writes_an_audit_entry(client):
    from app import crud, database, paths

    _login(client)
    response = client.post(
        f"/admin/users/{_admin_id()}/update",
        data={
            "csrf_token": _csrf(client, f"/admin/users/{_admin_id()}"),
            "username": "admin", "full_name": "Administrator",
            "email": "admin@example.org", "standard_weekly_hours": "40",
            "annual_vacation_days": "30", "vacation_carryover_days": "0",
            "employment_start_date": "2024-02-01",
            "employment_end_date": "",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with database.SessionLocal() as db:
        person = crud.get_user_by_username(db, "admin")
        assert person.employment_start_date == date(2024, 2, 1)
        assert person.employment_end_date is None
    audit = (paths.LOGS_DIR / "audit.log").read_text(encoding="utf-8")
    assert "Benutzer geändert" in audit


# ── 8. Bestehendes Verhalten bleibt ───────────────────────────────────────


def test_actual_time_is_never_shortened(main):
    """Eine Kennzeichnung ändert die gebuchte Zeit nicht."""
    from app import compliance, crud

    _set_employment(date(2026, 1, 1))
    entry = _entry(date(2026, 2, 16), time(21, 0), time(8, 0))
    before = entry.worked_minutes
    with _db() as db:
        compliance.refresh_day(db, _admin_id(), date(2026, 2, 16))
        after = crud.get_time_entry(db, entry.id)
        assert after.worked_minutes == before
        assert after.status == "approved"


def test_deactivated_accounts_stay_in_the_annual_check(main):
    """Die aufbewahrungssichere Deaktivierung darf niemanden verschwinden lassen."""
    from app import compliance, crud, database, schemas

    with database.SessionLocal() as db:
        person = crud.create_user(db, schemas.UserCreate(
            username="ausgeschieden", full_name="Ausgeschiedene Person",
            email="aus@example.org", password="Passwort!01",
        ))
        person.is_active = False
        person.employment_start_date = date(2026, 1, 1)
        db.commit()

    with _db() as db:
        reports = compliance.refresh_annual_compliance(
            db, reference_date=date(2026, 12, 31)
        )
        # Namen noch **innerhalb** der Sitzung lesen; danach ist das Objekt
        # abgelöst und ein Attributzugriff schlüge fehl.
        names = {report["user"].full_name for report in reports}
    assert "Ausgeschiedene Person" in names


def test_all_migrations_are_applied(main):
    from app import database, db_schema

    assert set(range(1, 23)) <= set(db_schema.applied_versions(database.engine))
