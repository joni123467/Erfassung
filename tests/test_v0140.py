"""Tests für 0.14.0 – revisionssichere Erfassung nach ArbZG, MiLoG und DSGVO.

Geprüft werden die Zusagen, die dieses Release macht:

* **Nichts verschwindet.** Änderungen, Freigaben, Ablehnungen und Stornos
  landen mit Vorher/Nachher in einer Historie; Löschen storniert.
* **Pausen stimmen.** Grenzen bei *mehr als* 6 bzw. 9 Stunden, Abschnitte ab
  15 Minuten, und eine nicht genommene Pause wird nicht als genommen verbucht.
* **Verstöße werden gekennzeichnet, nicht verhindert.** Die tatsächliche Zeit
  steht immer in der Datenbank.
* **Bestandsdaten rechnen unverändert weiter.**

Was diese Tests **nicht** behaupten: dass die Anwendung damit rechtssicher
oder zertifiziert wäre. Sie prüfen das technische Verhalten.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import date, datetime, time, timedelta

import pytest

import licensed_env


def _fresh_app(tmp_path, monkeypatch, env: dict | None = None):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    for key in ("DB_TYPE", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
                "DB_SSL", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]
    import app.main as main

    licensed_env.activate()
    return main


@pytest.fixture()
def main(tmp_path, monkeypatch):
    module = _fresh_app(tmp_path, monkeypatch)
    # Startvorgang einmal durchlaufen lassen, damit die Seed-Daten (u. a. der
    # Administrator) existieren – auch in Tests ohne HTTP-Client.
    from fastapi.testclient import TestClient

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
        test_client.main = main  # type: ignore[attr-defined]
        yield test_client


_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _csrf(client, url: str) -> str:
    match = _CSRF_RE.search(client.get(url).text)
    assert match, f"kein CSRF-Token auf {url}"
    return match.group(1)


def _login(client, username="admin", password="Admin!0000"):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _db():
    from app import database

    return database.SessionLocal()


def _admin_id() -> int:
    from app import crud

    db = _db()
    try:
        return crud.get_user_by_username(db, "admin").id
    finally:
        db.close()


DAY = date(2026, 4, 13)


def _entry(user_id, start, end, *, breaks=0, day=DAY, rule="actual", status="approved"):
    """Buchung über die reguläre Schicht anlegen.

    Bewusst über ``crud`` und nicht direkt über das Modell: Die
    Revisionssicherheit sitzt in dieser Schicht. Wer am Modell vorbei schreibt,
    umgeht sie – genau deshalb prüfen die Tests den regulären Weg.
    """
    from app import crud, database, models, schemas

    db = database.SessionLocal()
    try:
        item = crud.create_time_entry(db, schemas.TimeEntryCreate(
            user_id=user_id, work_date=day, start_time=start, end_time=end,
            break_minutes=breaks, is_open=False, notes="", is_manual=False,
            status=models.TimeEntryStatus.APPROVED,
        ))
        if rule != "actual" or status != "approved":
            item.break_rule = rule
            item.status = status
            db.commit()
        return item.id
    finally:
        db.close()


def _get(entry_id):
    from app import crud

    db = _db()
    try:
        return crud.get_time_entry(db, entry_id)
    finally:
        db.close()


# --- Version und Schema ----------------------------------------------------

def test_version(client):
    assert client.main.APP_VERSION == "0.20.8"
    assert client.get("/health").json()["version"] == "0.20.8"


def test_migration_registered(main):
    from app import db_migrations

    versions = [version for version, _ in db_migrations.MIGRATIONS]
    assert 17 in versions
    assert versions == sorted(versions)


def test_new_tables_and_columns_exist(client):
    from sqlalchemy import inspect

    from app import database

    inspector = inspect(database.engine)
    for table in ("break_intervals", "time_entry_revisions", "compliance_flags",
                  "payroll_periods", "period_confirmations", "data_access_log"):
        assert inspector.has_table(table), table
    columns = {c["name"] for c in inspector.get_columns("time_entries")}
    for column in ("started_at_utc", "ended_at_utc", "tz_name", "break_rule",
                   "cancelled_at", "cancel_reason", "replaced_by_id", "replaces_id"):
        assert column in columns, column


def test_migration_preserves_existing_data(tmp_path, monkeypatch):
    """Aufstieg von 0.13.x: Spalten ergänzt, Buchungen unverändert.

    Bestandsbuchungen bekommen ``legacy_auto`` und rechnen damit weiter wie
    bisher – ein abgerechneter Monat darf sich nicht rückwirkend ändern.
    """
    from app import db_migrations

    path = tmp_path / "alt.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE time_entries (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, company_id INTEGER,
          deleted_company_name VARCHAR, work_date DATE NOT NULL,
          start_time TIME NOT NULL, end_time TIME NOT NULL,
          break_minutes INTEGER DEFAULT 0, break_started_at TIME,
          is_open BOOLEAN DEFAULT 0, notes VARCHAR, status VARCHAR DEFAULT 'approved',
          is_manual BOOLEAN DEFAULT 0, is_remote BOOLEAN DEFAULT 0,
          source VARCHAR, external_id VARCHAR, created_at DATETIME, updated_at DATETIME);
        INSERT INTO time_entries (id, user_id, work_date, start_time, end_time, break_minutes)
        VALUES (1, 1, '2024-05-06', '08:00:00', '17:00:00', 0),
               (2, 1, '2024-05-07', '09:00:00', '13:00:00', 0);
        """
    )
    con.commit()
    con.close()

    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]
    import app.db_migrations as fresh_migrations

    fresh_migrations.run()

    con = sqlite3.connect(path)
    rows = list(con.execute("SELECT id, break_minutes, break_rule FROM time_entries ORDER BY id"))
    assert rows == [(1, 0, "legacy_auto"), (2, 0, "legacy_auto")]
    # Lückenlose Historie ab der Bestandsaufnahme.
    revisions = list(con.execute(
        "SELECT entry_id, action FROM time_entry_revisions ORDER BY entry_id"
    ))
    assert revisions == [(1, "created"), (2, "created")]
    con.close()


def test_legacy_entries_keep_their_calculation(main):
    """Der Kern der Verträglichkeit: 9 Stunden ohne Pause.

    Alt: 30 Minuten gesetzliche Pause wurden abgezogen (510 Minuten).
    Neu: nichts wird abgezogen (540 Minuten), der Fehlbetrag wird gekennzeichnet.
    """
    uid = _admin_id()
    alt = _get(_entry(uid, time(8, 0), time(17, 0), rule="legacy_auto"))
    neu = _get(_entry(uid, time(8, 0), time(17, 0), rule="actual", day=DAY + timedelta(days=1)))
    assert alt.worked_minutes == 510
    assert neu.worked_minutes == 540
    assert neu.break_shortfall_minutes == 30


# --- Pausen ----------------------------------------------------------------

@pytest.mark.parametrize(("minutes", "expected"), [
    (5 * 60, 0),
    (6 * 60, 0),            # genau sechs Stunden: noch keine Pflicht
    (6 * 60 + 1, 30),       # „mehr als sechs Stunden"
    (9 * 60, 30),           # genau neun Stunden: noch 30
    (9 * 60 + 1, 45),       # „mehr als neun Stunden"
])
def test_statutory_break_thresholds(main, minutes, expected):
    from app import models

    entry = models.TimeEntry(
        work_date=DAY, start_time=time(0, 0),
        end_time=time((minutes // 60) % 24, minutes % 60),
        break_minutes=0, is_open=False, status="approved", break_rule="actual",
    )
    assert entry.required_break_minutes == expected


def test_short_interruptions_are_no_rest_break(main):
    """Unter 15 Minuten ist keine Ruhepause – abgezogen wird sie trotzdem."""
    from app import models

    entry = models.TimeEntry(
        work_date=DAY, start_time=time(8, 0), end_time=time(17, 0),
        break_minutes=10, is_open=False, status="approved", break_rule="actual",
    )
    assert entry.countable_break_minutes == 0
    assert entry.applied_break_minutes == 10
    assert entry.break_shortfall_minutes == 30


def test_break_intervals_are_stored_individually(main):
    from app import crud, models

    db = _db()
    try:
        uid = crud.get_user_by_username(db, "admin").id
        entry = crud.start_running_entry(db, user_id=uid, started_at=datetime(2026, 4, 13, 8, 0))
        crud.start_break(db, entry, datetime(2026, 4, 13, 12, 0))
        crud.end_break(db, entry, datetime(2026, 4, 13, 12, 30))
        crud.start_break(db, entry, datetime(2026, 4, 13, 15, 0))
        crud.end_break(db, entry, datetime(2026, 4, 13, 15, 20))
        crud.finish_running_entry(db, entry, datetime(2026, 4, 13, 18, 0))
        db.refresh(entry)

        assert len(entry.breaks) == 2
        assert [interval.minutes for interval in entry.breaks] == [30, 20]
        assert entry.total_break_minutes == 50
        # Beide Abschnitte sind mindestens 15 Minuten → beide zählen.
        assert entry.countable_break_minutes == 50
        assert entry.break_shortfall_minutes == 0
        assert entry.breaks[0].started_at_utc is not None
        assert entry.breaks[0].ended_at_utc is not None
    finally:
        db.close()


def test_an_untaken_break_is_never_booked_as_taken(main):
    uid = _admin_id()
    entry = _get(_entry(uid, time(6, 0), time(16, 0)))
    assert entry.total_break_minutes == 0
    # 10 Stunden Anwesenheit, keine Pause: die Zeit steht voll in der Buchung.
    assert entry.worked_minutes == 600
    assert entry.break_shortfall_minutes == 45


# --- Nachtarbeit -----------------------------------------------------------

def test_night_shift_across_midnight(main):
    uid = _admin_id()
    entry = _get(_entry(uid, time(22, 0), time(6, 0)))
    assert entry.gross_minutes == 8 * 60
    assert entry.worked_minutes == 8 * 60


def test_utc_stamp_and_timezone_are_recorded(main):
    from app import crud

    db = _db()
    try:
        uid = crud.get_user_by_username(db, "admin").id
        entry = crud.start_running_entry(db, user_id=uid, started_at=datetime(2026, 4, 13, 8, 0))
        assert entry.tz_name == "Europe/Berlin"
        # Sommerzeit: 08:00 Ortszeit sind 06:00 UTC.
        assert entry.started_at_utc == datetime(2026, 4, 13, 6, 0)
        crud.finish_running_entry(db, entry, datetime(2026, 4, 13, 17, 0))
        db.refresh(entry)
        assert entry.ended_at_utc == datetime(2026, 4, 13, 15, 0)
    finally:
        db.close()


# --- Regelverstöße ---------------------------------------------------------

def test_more_than_ten_hours_is_flagged_but_stored(main):
    from app import compliance, models

    uid = _admin_id()
    _entry(uid, time(6, 0), time(17, 30), breaks=30)
    db = _db()
    try:
        findings = compliance.evaluate_day(db, uid, DAY)
        codes = {finding["code"] for finding in findings}
        assert models.ComplianceCode.OVER_10H in codes
        # Entscheidend: die Zeit selbst ist unverändert gespeichert.
        entry = db.query(models.TimeEntry).filter(models.TimeEntry.user_id == uid).first()
        assert entry.worked_minutes == 11 * 60 + 30 - 30  # 06:00–17:30 abzüglich 30 Min
    finally:
        db.close()


def test_more_than_eight_hours_is_only_a_warning(main):
    from app import compliance, models

    uid = _admin_id()
    _entry(uid, time(8, 0), time(17, 30), breaks=30)
    db = _db()
    try:
        findings = {f["code"]: f for f in compliance.evaluate_day(db, uid, DAY)}
        assert models.ComplianceCode.OVER_8H in findings
        assert findings[models.ComplianceCode.OVER_8H]["severity"] == compliance.SEVERITY_WARNING
        assert models.ComplianceCode.OVER_10H not in findings
    finally:
        db.close()


def test_rest_period_under_eleven_hours(main):
    from app import compliance, models

    uid = _admin_id()
    _entry(uid, time(8, 0), time(20, 0), breaks=45, day=DAY)
    _entry(uid, time(5, 0), time(13, 0), breaks=30, day=DAY + timedelta(days=1))
    db = _db()
    try:
        findings = {f["code"]: f for f in compliance.evaluate_day(db, uid, DAY + timedelta(days=1))}
        assert models.ComplianceCode.REST_UNDER_11H in findings
        assert findings[models.ComplianceCode.REST_UNDER_11H]["severity"] == "critical"
    finally:
        db.close()


def test_sunday_work_is_flagged(main):
    from app import compliance, models

    uid = _admin_id()
    sunday = date(2026, 4, 12)
    assert sunday.weekday() == 6
    _entry(uid, time(9, 0), time(13, 0), day=sunday)
    db = _db()
    try:
        codes = {f["code"] for f in compliance.evaluate_day(db, uid, sunday)}
        assert models.ComplianceCode.SUNDAY_WORK in codes
    finally:
        db.close()


def test_cancelled_entries_do_not_raise_violations(main):
    from app import compliance

    uid = _admin_id()
    _entry(uid, time(6, 0), time(20, 0), status="cancelled")
    db = _db()
    try:
        assert compliance.evaluate_day(db, uid, DAY) == []
    finally:
        db.close()


def test_flags_are_persisted_and_acknowledged_with_a_note(main):
    from app import compliance, crud

    uid = _admin_id()
    _entry(uid, time(6, 0), time(18, 0))
    db = _db()
    try:
        created = compliance.refresh_day(db, uid, DAY)
        assert created
        flag = created[0]
        with pytest.raises(ValueError):
            compliance.acknowledge(db, flag.id, user=crud.get_user(db, uid), note="  ")
        done = compliance.acknowledge(
            db, flag.id, user=crud.get_user(db, uid), note="Ausgleich in KW 17"
        )
        assert done.acknowledged_at is not None
        assert done.acknowledgement == "Ausgleich in KW 17"
        # Eine erneute Bewertung legt eingeordnete Kennzeichnungen nicht neu
        # an – sonst müsste man denselben Fall nach jeder Nachbuchung erneut
        # bewerten. Andere offene Kennzeichnungen bleiben davon unberührt.
        acknowledged_code = done.code
        compliance.refresh_day(db, uid, DAY)
        offen = {item.code for item in compliance.open_flags(db, user_ids=[uid])}
        assert acknowledged_code not in offen
        assert offen, "die übrigen Kennzeichnungen bleiben offen"
    finally:
        db.close()


# --- Revisionssicherheit ---------------------------------------------------

def test_creation_is_recorded(main):
    from app import revisions

    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    db = _db()
    try:
        history = revisions.history(db, entry_id)
        assert [item.action for item in history] == ["created"]
    finally:
        db.close()


def test_an_update_without_a_reason_is_refused(main):
    from app import crud, models, revisions, schemas

    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    db = _db()
    try:
        payload = schemas.TimeEntryCreate(
            user_id=uid, work_date=DAY, start_time=time(8, 0), end_time=time(15, 0),
            break_minutes=0, is_open=False, notes="", status=models.TimeEntryStatus.APPROVED,
        )
        with pytest.raises(revisions.ReasonRequired):
            crud.update_time_entry(db, entry_id, payload)
    finally:
        db.rollback()
        db.close()


def test_an_update_is_recorded_with_before_and_after(main):
    from app import crud, models, revisions, schemas

    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    db = _db()
    try:
        admin = crud.get_user(db, uid)
        payload = schemas.TimeEntryCreate(
            user_id=uid, work_date=DAY, start_time=time(8, 0), end_time=time(15, 0),
            break_minutes=0, is_open=False, notes="", status=models.TimeEntryStatus.APPROVED,
        )
        crud.update_time_entry(db, entry_id, payload, actor=admin, reason="Ende korrigiert")
        history = revisions.history(db, entry_id)
        assert [item.action for item in history] == ["created", "updated"]
        last = history[-1]
        assert last.reason == "Ende korrigiert"
        assert last.actor_id == uid
        changes = revisions.diff(
            revisions.parse(last.before_json), revisions.parse(last.after_json)
        )
        assert changes["end_time"] == {"vorher": "16:00:00", "nachher": "15:00:00"}
    finally:
        db.close()


def test_deleting_an_entry_cancels_it_instead(main):
    from app import crud, models, revisions

    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    db = _db()
    try:
        assert crud.delete_time_entry(db, entry_id) is True
        entry = crud.get_time_entry(db, entry_id)
        assert entry is not None, "Buchung darf nicht physisch verschwinden"
        assert entry.status == models.TimeEntryStatus.CANCELLED
        assert entry.worked_minutes == 0
        assert revisions.history(db, entry_id)[-1].action == "cancelled"
    finally:
        db.close()


def test_a_correction_is_a_cancellation_plus_replacement(main):
    from app import crud, models, revisions, schemas

    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    db = _db()
    try:
        admin = crud.get_user(db, uid)
        payload = schemas.TimeEntryCreate(
            user_id=uid, work_date=DAY, start_time=time(9, 0), end_time=time(17, 0),
            break_minutes=30, is_open=False, notes="korrigiert",
            status=models.TimeEntryStatus.APPROVED,
        )
        original, replacement = crud.replace_time_entry(
            db, entry_id, payload, actor=admin, reason="Falscher Beginn gestempelt"
        )
        assert original.status == models.TimeEntryStatus.CANCELLED
        assert original.replaced_by_id == replacement.id
        assert replacement.replaces_id == original.id
        assert original.cancel_reason == "Falscher Beginn gestempelt"
        actions = [item.action for item in revisions.history(db, original.id)]
        assert actions == ["created", "cancelled"]
        assert "replaced" in [item.action for item in revisions.history(db, replacement.id)]
    finally:
        db.close()


def test_a_cancellation_needs_a_reason(main):
    from app import crud, revisions

    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    db = _db()
    try:
        with pytest.raises(revisions.ReasonRequired):
            crud.cancel_time_entry(db, entry_id, actor=None, reason="   ")
    finally:
        db.rollback()
        db.close()


def test_history_page_shows_the_change(client):
    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    _login(client)
    url = f"/admin/time-entries/{entry_id}/edit?next=/admin/reports/time&user={uid}"
    client.post(
        f"/admin/time-entries/{entry_id}/update",
        data={
            "csrf_token": _csrf(client, url), "user_id": str(uid),
            "work_date": DAY.isoformat(), "start_time": "08:00", "end_time": "15:00",
            "break_minutes": "0", "notes": "", "change_reason": "Ende korrigiert",
            "next_url": "/admin/reports/time",
        },
        follow_redirects=False,
    )
    page = client.get(f"/admin/time-entries/{entry_id}/history")
    assert page.status_code == 200
    assert "Ende korrigiert" in page.text
    assert "Angelegt" in page.text and "Geändert" in page.text


def test_the_edit_route_refuses_without_a_reason(client):
    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    _login(client)
    url = f"/admin/time-entries/{entry_id}/edit?next=/admin/reports/time&user={uid}"
    response = client.post(
        f"/admin/time-entries/{entry_id}/update",
        data={
            "csrf_token": _csrf(client, url), "user_id": str(uid),
            "work_date": DAY.isoformat(), "start_time": "08:00", "end_time": "15:00",
            "break_minutes": "0", "notes": "", "change_reason": "   ",
            "next_url": "/admin/reports/time",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert _get(entry_id).end_time == time(16, 0), "Buchung wurde trotzdem geändert"


# --- Abschluss- und Korrekturworkflow --------------------------------------

def test_a_locked_period_refuses_changes(main):
    from app import crud, models, periods, schemas

    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    db = _db()
    try:
        admin = crud.get_user(db, uid)
        period = periods.create_period(
            db, period_start=DAY.replace(day=1), period_end=DAY.replace(day=28), label="04/2026"
        )
        periods.lock(db, period, actor=admin)

        payload = schemas.TimeEntryCreate(
            user_id=uid, work_date=DAY, start_time=time(8, 0), end_time=time(15, 0),
            break_minutes=0, is_open=False, notes="", status=models.TimeEntryStatus.APPROVED,
        )
        with pytest.raises(crud.PeriodLocked):
            crud.update_time_entry(db, entry_id, payload, actor=admin, reason="Test")
        with pytest.raises(crud.PeriodLocked):
            crud.cancel_time_entry(db, entry_id, actor=admin, reason="Test")
        # Und keine neue Buchung im gesperrten Zeitraum.
        with pytest.raises(crud.PeriodLocked):
            crud.create_time_entry(db, payload)
    finally:
        db.rollback()
        db.close()


def test_unlocking_requires_a_reason_and_is_noted(main):
    from app import crud, periods

    db = _db()
    try:
        admin = crud.get_user(db, _admin_id())
        period = periods.create_period(
            db, period_start=DAY.replace(day=1), period_end=DAY.replace(day=28)
        )
        periods.lock(db, period, actor=admin)
        with pytest.raises(ValueError):
            periods.reopen(db, period, actor=admin, reason="")
        periods.reopen(db, period, actor=admin, reason="Nachträgliche Korrektur nötig")
        assert period.status == "approved"
        assert "Sperre aufgehoben" in period.note
    finally:
        db.close()


def test_employee_confirmation_and_objection(main):
    from app import crud, models, periods

    db = _db()
    try:
        admin = crud.get_user(db, _admin_id())
        period = periods.create_period(
            db, period_start=DAY.replace(day=1), period_end=DAY.replace(day=28)
        )
        periods.start_review(db, period, user_ids=[admin.id])
        assert len(periods.open_confirmations(db, admin.id)) == 1

        with pytest.raises(ValueError):
            periods.submit_confirmation(db, period, admin, confirmed=False, note="")

        record = periods.submit_confirmation(
            db, period, admin, confirmed=False, note="Dienstag fehlt eine Stunde"
        )
        assert record.status == models.ConfirmationStatus.OBJECTED
        periods.respond_to_objection(
            db, record, actor=admin, response="Nachgetragen, bitte erneut prüfen"
        )
        assert record.responded_at is not None

        record = periods.submit_confirmation(db, period, admin, confirmed=True)
        assert record.status == models.ConfirmationStatus.CONFIRMED
    finally:
        db.close()


# --- Datenschutz -----------------------------------------------------------

def test_access_to_foreign_data_is_logged(client):
    from app import crud, models, schemas, security

    db = _db()
    try:
        other = crud.create_user(db, schemas.UserCreate(
            username="kollege", full_name="Kollege K", email="k@example.org",
            password="Kollege!0000",
        ))
        other.password_hash = security.hash_password("Kollege!0000")
        other.must_change_password = False
        db.commit()
        other_id = other.id
    finally:
        db.close()

    entry_id = _entry(other_id, time(8, 0), time(16, 0))
    _login(client)
    assert client.get(f"/admin/time-entries/{entry_id}/history").status_code == 200

    db = _db()
    try:
        rows = db.query(models.DataAccessLog).all()
        assert len(rows) == 1
        assert rows[0].subject_user_id == other_id
        assert rows[0].scope == "entry_history"
    finally:
        db.close()


def test_looking_at_your_own_data_is_not_logged(client):
    from app import models

    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(16, 0))
    _login(client)
    client.get(f"/admin/time-entries/{entry_id}/history")

    db = _db()
    try:
        assert db.query(models.DataAccessLog).count() == 0
    finally:
        db.close()


def test_subject_access_export_is_complete(client):
    uid = _admin_id()
    entry_id = _entry(uid, time(8, 0), time(18, 0))
    from app import crud, models, schemas

    db = _db()
    try:
        admin = crud.get_user(db, uid)
        payload = schemas.TimeEntryCreate(
            user_id=uid, work_date=DAY, start_time=time(8, 0), end_time=time(17, 0),
            break_minutes=30, is_open=False, notes="", status=models.TimeEntryStatus.APPROVED,
        )
        crud.update_time_entry(db, entry_id, payload, actor=admin, reason="Korrektur")
    finally:
        db.close()

    _login(client)
    response = client.get("/api/me/export")
    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")
    data = response.json()
    for key in ("person", "buchungen", "aenderungshistorie", "kennzeichnungen",
                "urlaub", "zugriffe_auf_diese_daten"):
        assert key in data, key
    assert data["person"]["benutzername"] == "admin"
    assert len(data["buchungen"]) == 1
    assert any(item["begruendung"] == "Korrektur" for item in data["aenderungshistorie"])


def test_retention_policy_is_configurable_and_reports(main):
    from app import privacy

    policy = privacy.load_policy()
    assert policy.time_entries_months == 24  # §16 ArbZG / §17 MiLoG
    policy.access_log_months = 6
    privacy.save_policy(policy)
    assert privacy.load_policy().access_log_months == 6

    uid = _admin_id()
    _entry(uid, time(8, 0), time(16, 0))
    db = _db()
    try:
        report = privacy.retention_report(db)
        assert report["policy"]["access_log_months"] == 6
        # Nichts wird automatisch gelöscht – der Bericht zählt nur.
        assert report["time_entries"]["count"] == 0
    finally:
        db.close()


# --- Berechtigungen --------------------------------------------------------

def test_history_of_a_foreign_entry_needs_permission(client):
    from app import crud, database, schemas, security

    db = database.SessionLocal()
    try:
        other = crud.create_user(db, schemas.UserCreate(
            username="fremd", full_name="Fremde Person", email="f@example.org",
            password="Fremd!00000",
        ))
        other.password_hash = security.hash_password("Fremd!00000")
        other.must_change_password = False
        db.commit()
        other_id = other.id
    finally:
        db.close()

    entry_id = _entry(other_id, time(8, 0), time(16, 0))
    _login(client, "fremd", "Fremd!00000")
    own = _entry(other_id, time(18, 0), time(19, 0))
    # Eigene Buchung: erlaubt.
    assert client.get(f"/admin/time-entries/{own}/history").status_code == 200

    # Fremde Buchung ohne Recht: abgewiesen.
    admin_entry = _entry(_admin_id(), time(8, 0), time(16, 0), day=DAY + timedelta(days=3))
    response = client.get(
        f"/admin/time-entries/{admin_entry}/history", follow_redirects=False
    )
    assert response.status_code in (302, 303)


# --- Verträglichkeit -------------------------------------------------------

def test_offline_sync_still_works(client):
    _login(client)
    payload = client.get("/mobile/sync-data").json()
    assert "entries" in payload and "permissions" in payload


def test_punch_flow_creates_intervals_and_flags(client):
    from app import crud, models

    _login(client)
    token = _csrf(client, "/dashboard")
    client.post("/punch", data={"action": "start_work", "csrf_token": token,
                                "next_url": "/dashboard"}, follow_redirects=False)
    client.post("/punch", data={"action": "start_break", "csrf_token": token,
                                "next_url": "/dashboard"}, follow_redirects=False)
    db = _db()
    try:
        uid = crud.get_user_by_username(db, "admin").id
        entry = crud.get_open_time_entry(db, uid)
        assert entry is not None
        assert entry.running_break is not None
        assert db.query(models.BreakInterval).count() == 1
    finally:
        db.close()


def test_terminal_import_still_creates_entries(main):
    """Terminalimporte laufen ohne Bearbeiter – die Historie hält das fest."""
    from app import crud, models, revisions, schemas

    uid = _admin_id()
    db = _db()
    try:
        entry = crud.create_time_entry(db, schemas.TimeEntryCreate(
            user_id=uid, work_date=DAY, start_time=time(7, 0), end_time=time(15, 0),
            break_minutes=30, is_open=False, notes="",
            status=models.TimeEntryStatus.APPROVED, source="terminal", external_id="T-1",
        ))
        history = revisions.history(db, entry.id)
        assert [item.action for item in history] == ["created"]
        assert history[0].source == "terminal"
        assert history[0].actor_label == "System"

        # Idempotenz: derselbe Fremdschlüssel legt nichts Neues an.
        again = crud.create_time_entry(db, schemas.TimeEntryCreate(
            user_id=uid, work_date=DAY, start_time=time(7, 0), end_time=time(15, 0),
            break_minutes=30, is_open=False, notes="",
            status=models.TimeEntryStatus.APPROVED, source="terminal", external_id="T-1",
        ))
        assert again.id == entry.id
        assert len(revisions.history(db, entry.id)) == 1
    finally:
        db.close()


def test_logical_backup_covers_the_new_tables(main):
    """Backup und Cross-Database-Restore müssen die neuen Tabellen mitnehmen.

    Der logische Export läuft über ``Base.metadata`` – die Prüfung stellt
    sicher, dass die neuen Tabellen dort tatsächlich ankommen und nicht
    versehentlich außen vor bleiben.
    """
    from app import data_transfer, database, models

    uid = _admin_id()
    _entry(uid, time(8, 0), time(16, 0))
    payload = data_transfer.export_database(database.engine)
    counts = data_transfer.table_counts_from_export(payload)
    for table in ("break_intervals", "time_entry_revisions", "compliance_flags",
                  "payroll_periods", "period_confirmations", "data_access_log"):
        assert table in counts, f"{table} fehlt im logischen Export"
    assert counts["time_entry_revisions"] >= 1
    assert models.TimeEntryRevision.__tablename__ in {
        table.name for table in models.Base.metadata.sorted_tables
    }


def test_exports_and_reports_still_render(client):
    uid = _admin_id()
    _entry(uid, time(8, 0), time(16, 0))
    _login(client)
    assert client.get("/records").status_code == 200
    assert client.get("/admin/reports/time").status_code == 200
    assert client.get("/admin/compliance").status_code == 200
    assert client.get("/admin/periods").status_code == 200
