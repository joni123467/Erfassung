"""Tests für 0.16.0 – Selbstbedienung, Dauerberechnung und Ausgleich.

Was dieses Release schließt:

* **Die Selbstbedienung kannte keine Rechte.** Wer angemeldet war, konnte sich
  über ``POST /api/time-entries`` eine Buchung anlegen – auch ohne
  ``Own.Time.Edit``. Und er konnte dabei ``status``, ``source``,
  ``external_id`` und die UTC-Stempel frei bestimmen: eine freigegebene
  Buchung, die wie eine Terminalstempelung aussieht.
* **Die Dauer wurde zweimal gerechnet.** ``compliance`` rechnete in UTC,
  ``TimeEntry.gross_minutes`` mit naiven Ortszeiten. Über eine Zeitumstellung
  hinweg wichen Regelprüfung und Auswertung um eine Stunde voneinander ab.
* **Feststellungen waren nur über den Code zugeordnet.** Zwei getrennte
  Schichten an einem Tag mit demselben Verstoß fielen zu einer Feststellung
  zusammen.
* **Der Ausgleich nach § 3 Satz 2 ArbZG fehlte.** Mehr als acht Stunden wurden
  gekennzeichnet, aber nie gegen den Durchschnitt geprüft.
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
DAY = date(2026, 3, 10)          # Dienstag, außerhalb jeder Zeitumstellung


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
    assert response.status_code in (302, 303)


def _api_token(client) -> dict[str, str]:
    return {"x-csrf-token": client.get("/api/csrf").json()["csrf_token"]}


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


def _company(name: str) -> int:
    from app import crud, schemas

    db = _db()
    try:
        company = crud.create_company(
            db, schemas.CompanyCreate(name=name, description="", is_internal=False)
        )
        return int(company.id)
    finally:
        db.close()


def _location(company_id: int, name: str, **fields) -> int:
    from app import crud, schemas

    db = _db()
    try:
        location = crud.create_company_location(
            db, company_id, schemas.CompanyLocationCreate(name=name, **fields)
        )
        return int(location.id)
    finally:
        db.close()


def _entry(
    *,
    start: time,
    end: time,
    day: date = DAY,
    breaks: int = 0,
    user_id: int | None = None,
    company_id: int | None = None,
    location_id: int | None = None,
    utc: bool = True,
):
    """Buchung anlegen – standardmäßig mit gepflegten UTC-Stempeln."""
    from app import crud, schemas

    uid = user_id or _admin_id()
    started = datetime.combine(day, start).replace(tzinfo=BERLIN)
    ended = datetime.combine(day, end).replace(tzinfo=BERLIN)
    if ended < started:
        ended += timedelta(days=1)
    db = _db()
    try:
        return crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=uid,
                work_date=day,
                start_time=start,
                end_time=end,
                break_minutes=breaks,
                company_id=company_id,
                location_id=location_id,
                started_at_utc=started.astimezone(timezone.utc).replace(tzinfo=None)
                if utc else None,
                ended_at_utc=ended.astimezone(timezone.utc).replace(tzinfo=None)
                if utc else None,
                tz_name="Europe/Berlin" if utc else None,
            ),
        )
    finally:
        db.close()


def _codes(db, user_id: int, day: date) -> set[str]:
    from app import compliance

    return {finding["code"] for finding in compliance.evaluate_day(db, user_id, day)}


def _second_user(username: str = "kollege") -> int:
    """Zweite Person in einer eigenen Gruppe – für Scope-Tests."""
    from app import crud, schemas, security

    db = _db()
    try:
        person = crud.create_user(
            db,
            schemas.UserCreate(
                username=username,
                full_name="Kollege Ohne Team",
                email=f"{username}@example.org",
                password="Kollege!0000",
            ),
        )
        person.password_hash = security.hash_password("Kollege!0000")
        person.must_change_password = False
        db.commit()
        return int(person.id)
    finally:
        db.close()


def _grant_only(*keys: str) -> None:
    """Dem Administrator genau die angegebenen Rechte lassen.

    Selbstbedienungsrechte gelten ohne Rolle als erlaubt (Bestandsverhalten).
    Erst mit einer Rolle entscheiden ausschließlich deren Rechte – nur so lässt
    sich ein fehlendes ``Own.*``-Recht überhaupt prüfen.
    """
    from app import crud, database, models

    db = database.SessionLocal()
    try:
        role = crud.create_role(db, name="Testrolle", description="", is_active=True,
                                permissions={key: "self" for key in keys})
        admin = crud.get_user_by_username(db, "admin")
        admin.roles = [role]
        admin.groups = []
        db.commit()
    finally:
        db.close()


def _self_entry_payload(**overrides) -> dict:
    payload = {
        "user_id": _admin_id(),
        "work_date": DAY.isoformat(),
        "start_time": "08:00:00",
        "end_time": "16:00:00",
        "break_minutes": 30,
    }
    payload.update(overrides)
    return payload


# ── Version ───────────────────────────────────────────────────────────────


def test_version_is_0160(client):
    assert client.app.version == "0.20.2"
    assert client.get("/health").json()["version"] == "0.20.2"


# ── 1. Selbstbedienungsrechte ─────────────────────────────────────────────


def test_anonymous_still_gets_401(client):
    assert client.get("/api/users").status_code == 401
    assert client.post(
        "/api/time-entries", json=_self_entry_payload(), headers=_api_token(client)
    ).status_code == 401


def test_own_booking_without_the_permission_is_refused(client):
    """Angemeldet genügt nicht – ``Own.Time.Edit`` muss vorhanden sein."""
    _grant_only("Own.Comment.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries", json=_self_entry_payload(), headers=_api_token(client)
    )
    assert response.status_code == 403


def test_own_booking_with_the_permission_works(client):
    _grant_only("Own.Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries", json=_self_entry_payload(), headers=_api_token(client)
    )
    assert response.status_code == 200, response.text


def test_own_cancellation_needs_its_own_permission(client):
    """Nachtragen und Zurücknehmen sind verschiedene Dinge."""
    from app import models

    entry = _entry(start=time(8, 0), end=time(12, 0))
    _grant_only("Own.Time.Edit")          # ausdrücklich **ohne** Own.Time.Cancel
    _login(client)
    response = client.delete(
        f"/api/time-entries/{entry.id}?reason=Test",
        headers=_api_token(client),
    )
    assert response.status_code == 403

    db = _db()
    try:
        from app import crud

        assert crud.get_time_entry(db, entry.id).status != models.TimeEntryStatus.CANCELLED
    finally:
        db.close()


def test_own_cancellation_with_the_permission_works(client):
    from app import crud, models

    entry = _entry(start=time(8, 0), end=time(12, 0))
    _grant_only("Own.Time.Cancel")
    _login(client)
    response = client.delete(
        f"/api/time-entries/{entry.id}?reason=Test%3A+doppelt",
        headers=_api_token(client),
    )
    assert response.status_code == 200

    db = _db()
    try:
        assert crud.get_time_entry(db, entry.id).status == models.TimeEntryStatus.CANCELLED
    finally:
        db.close()


def test_own_vacation_without_the_permission_is_refused(client):
    _grant_only("Own.Time.Edit")
    _login(client)
    response = client.post(
        "/api/vacations",
        json={
            "user_id": _admin_id(),
            "start_date": DAY.isoformat(),
            "end_date": DAY.isoformat(),
            "comment": "",
        },
        headers=_api_token(client),
    )
    assert response.status_code == 403


def test_a_foreign_booking_still_needs_time_edit(client):
    other = _second_user()
    _grant_only("Own.Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries",
        json=_self_entry_payload(user_id=other),
        headers=_api_token(client),
    )
    assert response.status_code == 403


# ── 2. Sichere Eingabeschemas ─────────────────────────────────────────────


def test_an_employee_cannot_approve_their_own_booking(client):
    """``status`` gehört dem Server, nicht dem Client."""
    from app import crud, models

    _grant_only("Own.Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries",
        json=_self_entry_payload(status=models.TimeEntryStatus.APPROVED),
        headers=_api_token(client),
    )
    assert response.status_code == 200

    db = _db()
    try:
        stored = crud.get_time_entry(db, response.json()["id"])
        assert stored.status == models.TimeEntryStatus.PENDING
    finally:
        db.close()


def test_an_employee_cannot_fake_a_terminal_source(client):
    """Sonst liesse sich ein Nachtrag als Terminalstempelung ausgeben."""
    from app import crud

    _grant_only("Own.Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries",
        json=_self_entry_payload(source="timemoto", external_id="fremd-4711"),
        headers=_api_token(client),
    )
    assert response.status_code == 200

    db = _db()
    try:
        stored = crud.get_time_entry(db, response.json()["id"])
        assert stored.source is None
        assert stored.external_id is None
    finally:
        db.close()


def test_an_employee_cannot_inject_utc_stamps(client):
    """Die UTC-Stempel entstehen aus der zentralen Betriebszeitzone."""
    from app import crud

    _grant_only("Own.Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries",
        json=_self_entry_payload(
            started_at_utc="1999-01-01T00:00:00",
            ended_at_utc="1999-01-01T023:00:00".replace("023", "23"),
            tz_name="Pacific/Auckland",
        ),
        headers=_api_token(client),
    )
    assert response.status_code == 200

    db = _db()
    try:
        stored = crud.get_time_entry(db, response.json()["id"])
        assert stored.tz_name == "Europe/Berlin"
        assert stored.started_at_utc.year == DAY.year
        # 08:00 MEZ = 07:00 UTC
        assert stored.started_at_utc.hour == 7
    finally:
        db.close()


def test_an_employee_cannot_mark_a_booking_as_stamped(client):
    """``is_manual=false`` würde den Nachtrag als Stempelung ausgeben."""
    from app import crud

    _grant_only("Own.Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries",
        json=_self_entry_payload(is_manual=False, is_open=True),
        headers=_api_token(client),
    )
    assert response.status_code == 200

    db = _db()
    try:
        stored = crud.get_time_entry(db, response.json()["id"])
        assert stored.is_manual is True
        assert stored.is_open is False
    finally:
        db.close()


def test_a_foreign_location_is_discarded(client):
    """Der Standort muss zur gebuchten Firma gehören."""
    from app import crud

    a = _company("Kunde A")
    b = _company("Kunde B")
    fremd = _location(b, "Werk B")
    _grant_only("Own.Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries",
        json=_self_entry_payload(company_id=a, location_id=fremd),
        headers=_api_token(client),
    )
    assert response.status_code == 200

    db = _db()
    try:
        stored = crud.get_time_entry(db, response.json()["id"])
        assert stored.location_id is None
    finally:
        db.close()


def test_the_terminal_import_keeps_its_trusted_fields(client):
    """Vertrauenswürdige Importpfade dürfen Quelle und externe ID setzen."""
    from app import crud, schemas

    db = _db()
    try:
        entry = crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=_admin_id(),
                work_date=DAY,
                start_time=time(6, 0),
                end_time=time(14, 0),
                source="timemoto",
                external_id="evt-4711",
            ),
        )
        assert entry.source == "timemoto"
        assert entry.external_id == "evt-4711"
    finally:
        db.close()


# ── 3. Einheitliche Dauerberechnung ───────────────────────────────────────


def test_duration_uses_utc_stamps(main):
    from app import worktime

    class _Entry:
        work_date = DAY
        start_time = time(8, 0)
        end_time = time(16, 0)
        is_open = False
        tz_name = "Europe/Berlin"
        started_at_utc = datetime(2026, 3, 10, 7, 0)
        ended_at_utc = datetime(2026, 3, 10, 15, 0)

    assert worktime.gross_minutes(_Entry()) == 8 * 60


def test_spring_forward_shortens_the_night_shift(client):
    """29.03.2026: Die Stunde von 2 auf 3 Uhr fällt aus.

    Wer von 22:00 bis 6:00 Ortszeit arbeitet, ist nur sieben Stunden im
    Betrieb – nicht acht. Die naive Rechnung sagte acht.
    """
    from app import crud

    entry = _entry(start=time(22, 0), end=time(6, 0), day=date(2026, 3, 28))
    db = _db()
    try:
        stored = crud.get_time_entry(db, entry.id)
        assert stored.gross_minutes == 7 * 60
    finally:
        db.close()


def test_autumn_back_lengthens_the_night_shift(client):
    """25.10.2026: Die Stunde von 3 auf 2 Uhr kommt doppelt – neun Stunden."""
    from app import crud

    entry = _entry(start=time(22, 0), end=time(6, 0), day=date(2026, 10, 24))
    db = _db()
    try:
        stored = crud.get_time_entry(db, entry.id)
        assert stored.gross_minutes == 9 * 60
    finally:
        db.close()


def test_midnight_is_handled(client):
    from app import crud

    entry = _entry(start=time(20, 0), end=time(4, 0))
    db = _db()
    try:
        assert crud.get_time_entry(db, entry.id).gross_minutes == 8 * 60
    finally:
        db.close()


def test_compliance_and_reports_agree_on_the_duration(client):
    """Regelprüfung, Tagessumme und Modell rechnen dieselbe Zahl."""
    from app import compliance, crud, main as main_module

    entry = _entry(start=time(22, 0), end=time(6, 0), day=date(2026, 3, 28))
    db = _db()
    try:
        stored = crud.get_time_entry(db, entry.id)
        start, end = compliance._entry_bounds(stored)
        aus_compliance = int((end - start).total_seconds() // 60)
        overview = main_module._build_daily_overview(
            db, _admin_id(), date(2026, 3, 28)
        )
    finally:
        db.close()
    assert aus_compliance == stored.gross_minutes
    assert overview["total_minutes"] == stored.worked_minutes


def test_booked_breaks_are_deducted(client):
    from app import crud

    entry = _entry(start=time(8, 0), end=time(17, 0), breaks=45)
    db = _db()
    try:
        stored = crud.get_time_entry(db, entry.id)
        assert stored.gross_minutes == 9 * 60
        assert stored.worked_minutes == 9 * 60 - 45
    finally:
        db.close()


# ── 4. Feststellungen je Schicht ──────────────────────────────────────────


def test_two_shifts_one_day_give_two_findings(client):
    """Zwei getrennte Schichten mit derselben Verfehlung sind zwei Befunde."""
    from app import compliance, models

    # Erste Schicht 00:30–07:00 (6:30 ohne Pause), acht Stunden Lücke,
    # zweite Schicht 15:00–21:30 (6:30 ohne Pause).
    _entry(start=time(0, 30), end=time(7, 0))
    _entry(start=time(15, 0), end=time(21, 30))

    db = _db()
    try:
        findings = [
            f for f in compliance.evaluate_day(db, _admin_id(), DAY)
            if f["code"] == models.ComplianceCode.BREAK_MISSING
        ]
        assert len(findings) == 2, "Beide Schichten müssen auftauchen"
        keys = {
            compliance.finding_key(_admin_id(), DAY, f) for f in findings
        }
        assert len(keys) == 2, "Die Schlüssel müssen sich unterscheiden"
    finally:
        db.close()


def test_two_findings_are_stored_separately(client):
    from app import compliance, models

    _entry(start=time(0, 30), end=time(7, 0))
    _entry(start=time(15, 0), end=time(21, 30))
    db = _db()
    try:
        compliance.refresh_day(db, _admin_id(), DAY)
        flags = (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.code == models.ComplianceCode.BREAK_MISSING)
            .all()
        )
        assert len(flags) == 2
        assert len({flag.finding_key for flag in flags}) == 2
    finally:
        db.close()


def test_one_finding_can_be_acknowledged_alone(client):
    """Die zweite Feststellung bleibt offen."""
    from app import compliance, crud, models

    _entry(start=time(0, 30), end=time(7, 0))
    _entry(start=time(15, 0), end=time(21, 30))
    db = _db()
    try:
        compliance.refresh_day(db, _admin_id(), DAY)
        flags = (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.code == models.ComplianceCode.BREAK_MISSING)
            .order_by(models.ComplianceFlag.id)
            .all()
        )
        admin = crud.get_user_by_username(db, "admin")
        compliance.acknowledge(db, flags[0].id, user=admin, note="Test: erste Schicht")
        assert compliance.get_flag(db, flags[0].id).state == models.ComplianceState.ACKNOWLEDGED
        assert compliance.get_flag(db, flags[1].id).state != models.ComplianceState.ACKNOWLEDGED
    finally:
        db.close()


# ── 5. Konfigurierbare Schichtgrenze ──────────────────────────────────────


def test_the_shift_gap_comes_from_the_configuration(main):
    from app import app_config, compliance

    assert compliance.shift_break_minutes() == 360
    settings = app_config.load_system_settings()
    settings.shift_break_minutes = 120
    app_config.save_system_settings(settings)
    assert compliance.shift_break_minutes() == 120


def test_the_shift_gap_is_persisted_in_the_config_volume(main, tmp_path):
    from app import app_config

    settings = app_config.load_system_settings()
    settings.shift_break_minutes = 240
    app_config.save_system_settings(settings)
    stored = (tmp_path / "config" / "system.json").read_text(encoding="utf-8")
    assert "shift_break_minutes" in stored
    assert "240" in stored


@pytest.mark.parametrize("value,valid", [(60, True), (720, True), (30, False), (900, False)])
def test_the_shift_gap_range_is_validated(main, value, valid):
    from app import app_config

    ok, message = app_config.validate_import(
        {"system": {"shift_break_minutes": value}}
    )
    assert ok is valid, message


def test_a_lower_shift_gap_changes_the_evaluation(client):
    """Mit zwei Stunden Grenze werden aus einer Schicht zwei."""
    from app import app_config, compliance

    _entry(start=time(6, 0), end=time(10, 0))
    _entry(start=time(13, 0), end=time(19, 0))   # drei Stunden Lücke

    db = _db()
    try:
        entries = compliance._entries_around(db, _admin_id(), DAY)
        assert len(compliance.build_shifts(entries)) == 1
    finally:
        db.close()

    settings = app_config.load_system_settings()
    settings.shift_break_minutes = 120
    app_config.save_system_settings(settings)

    db = _db()
    try:
        entries = compliance._entries_around(db, _admin_id(), DAY)
        assert len(compliance.build_shifts(entries)) == 2
    finally:
        db.close()


# ── 6. Ausgleich nach §3 ArbZG ────────────────────────────────────────────


def test_the_compensation_report_names_its_period(client):
    """Seit 0.19.0 ist der Nenner **Werktage**, nicht „Tage mit Buchung"."""
    from app import compliance

    _entry(start=time(6, 0), end=time(15, 0))
    db = _db()
    try:
        report = compliance.compensation_report(db, _admin_id(), DAY)
    finally:
        db.close()
    assert report.end == DAY
    assert (report.end - report.start).days + 1 == report.rules.days
    # 24 Wochen sind 144 Werktage (Mo–Sa) abzüglich der Ausnahmen.
    assert report.denominator > 100


def test_a_single_long_day_is_required_but_not_overdue(client):
    """Seit 0.19.0: ausgleichspflichtig, aber nicht sofort überfällig."""
    from app import models

    _entry(start=time(6, 0), end=time(16, 0))    # zehn Stunden
    db = _db()
    try:
        codes = _codes(db, _admin_id(), DAY)
    finally:
        db.close()
    assert models.ComplianceCode.OVER_8H in codes
    assert models.ComplianceCode.COMPENSATION_REQUIRED in codes
    assert models.ComplianceCode.COMPENSATION_OVERDUE not in codes


def test_the_average_stays_compliant_with_free_workdays(client):
    """Über nicht gearbeitete Werktage läuft der Ausgleich."""
    from app import compliance, models

    _entry(start=time(6, 0), end=time(16, 0))    # zehn Stunden am Stichtag
    db = _db()
    try:
        report = compliance.compensation_report(db, _admin_id(), DAY)
        codes = _codes(db, _admin_id(), DAY)
    finally:
        db.close()
    # Ein einzelner langer Tag unter über hundert freien Werktagen reißt den
    # Schnitt nicht.
    assert report.is_compliant, report.average_minutes
    # Der Tagesverstoß bleibt – er wird gekennzeichnet, nicht wegdiskutiert.
    assert models.ComplianceCode.OVER_8H in codes


def test_sunday_work_stays_out_of_the_average(client):
    """§3 ArbZG spricht von werktäglicher Arbeitszeit – Sonntag zählt nicht."""
    from app import compliance

    sunday = date(2026, 3, 8)
    assert sunday.weekday() == 6
    _entry(start=time(8, 0), end=time(18, 0), day=sunday)
    db = _db()
    try:
        report = compliance.compensation_report(db, _admin_id(), DAY)
    finally:
        db.close()
    # Die Sonntagsarbeit bleibt gemäß § 11 Abs. 2 in der Arbeitszeitsumme …
    assert report.total_minutes == 600
    # … aber der Sonntag steht weiterhin nicht im Werktagsnenner.
    assert all(item.day.weekday() != 6 for item in report.counted_days)


def test_work_over_eight_hours_is_never_blocked(client):
    """Gekennzeichnet, nicht verhindert – die Zeit steht in der Datenbank."""
    from app import crud

    entry = _entry(start=time(6, 0), end=time(18, 0))
    db = _db()
    try:
        stored = crud.get_time_entry(db, entry.id)
        assert stored.worked_minutes == 12 * 60
    finally:
        db.close()


# ── 7. Sonn-/Feiertagsarbeit ──────────────────────────────────────────────


def test_an_exception_can_be_documented(client):
    from app import compliance, models

    sunday = date(2026, 3, 8)
    _entry(start=time(8, 0), end=time(14, 0), day=sunday)
    db = _db()
    try:
        compliance.refresh_day(db, _admin_id(), sunday)
        flag = (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.code == models.ComplianceCode.SUNDAY_WORK)
            .first()
        )
        assert flag is not None
        compliance.document_exception(
            db,
            flag.id,
            user=None,
            reason="Notdienst",
            legal_basis="§10 Abs. 1 Nr. 3 ArbZG",
            replacement_rest_date=date(2026, 3, 11),
            handling_state="rest_granted",
        )
        stored = compliance.get_flag(db, flag.id)
        assert stored.exception_reason == "Notdienst"
        assert stored.legal_basis == "§10 Abs. 1 Nr. 3 ArbZG"
        assert stored.replacement_rest_date == date(2026, 3, 11)
        assert stored.handling_state == "rest_granted"
    finally:
        db.close()


def test_an_unknown_handling_state_is_refused(client):
    from app import compliance, models

    sunday = date(2026, 3, 8)
    _entry(start=time(8, 0), end=time(14, 0), day=sunday)
    db = _db()
    try:
        compliance.refresh_day(db, _admin_id(), sunday)
        flag = db.query(models.ComplianceFlag).first()
        with pytest.raises(ValueError):
            compliance.document_exception(
                db, flag.id, user=None, handling_state="erfunden"
            )
    finally:
        db.rollback()
        db.close()


def test_a_customer_holiday_does_not_apply(client):
    """Der Kundenstandort ändert die Feiertagsbewertung nicht."""
    from app import crud, models, services

    company = _company("Kunde in Bayern")
    location = _location(company, "Werk München", city="München")
    fronleichnam = date(2026, 6, 4)
    _entry(start=time(8, 0), end=time(16, 0), day=fronleichnam,
           company_id=company, location_id=location)

    db = _db()
    try:
        assert fronleichnam not in crud.get_holiday_dates_in_range(
            db, fronleichnam, fronleichnam
        )
        assert models.ComplianceCode.HOLIDAY_WORK not in _codes(
            db, _admin_id(), fronleichnam
        )
    finally:
        db.close()


def test_the_central_holiday_applies_during_customer_work(client):
    from app import crud, models, schemas, services

    company = _company("Kunde anderswo")
    location = _location(company, "Werk Süd", city="München")
    own = date(2026, 5, 1)
    db = _db()
    try:
        crud.upsert_holidays(
            db, [schemas.HolidayCreate(name="Tag der Arbeit", date=own, region="DE")]
        )
    finally:
        db.close()

    _entry(start=time(8, 0), end=time(16, 0), day=own,
           company_id=company, location_id=location)
    db = _db()
    try:
        assert models.ComplianceCode.HOLIDAY_WORK in _codes(db, _admin_id(), own)
        person = crud.get_user_by_username(db, "admin")
        assert services.holiday_credit_minutes(
            person, crud.get_holiday_dates_in_range(db, own, own), own, own
        ) == 480
    finally:
        db.close()


def test_a_customer_switch_changes_no_rule(client):
    """Zwei Kunden an einem Tag ergeben eine Schicht und einen Arbeitstag."""
    from app import compliance, models

    a = _company("Kunde A")
    b = _company("Kunde B")
    _entry(start=time(6, 0), end=time(12, 0), company_id=a)
    _entry(start=time(12, 5), end=time(17, 0), company_id=b)

    db = _db()
    try:
        shifts = compliance.build_shifts(
            compliance._entries_around(db, _admin_id(), DAY)
        )
        assert len(shifts) == 1, "Der Kundenwechsel darf keine Schicht trennen"
        assert models.ComplianceCode.BREAK_MISSING in _codes(db, _admin_id(), DAY)
    finally:
        db.close()


# ── 8. Migration und Bestand ──────────────────────────────────────────────


def test_migration_19_is_registered(main):
    from app import db_migrations

    numbers = [number for number, _ in db_migrations.MIGRATIONS]
    assert 19 in numbers
    assert numbers == sorted(numbers)


def test_the_new_columns_exist(main):
    from sqlalchemy import inspect

    from app import database

    columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("compliance_flags")
    }
    for expected in (
        "finding_key", "shift_start_utc", "exception_reason",
        "legal_basis", "replacement_rest_date", "handling_state",
    ):
        assert expected in columns, expected


def test_upgrade_from_0150_keeps_everything(tmp_path, monkeypatch):
    """Aufstieg aus einem 0.15.0-Bestand: nichts geht verloren."""
    import sqlite3

    db_path = tmp_path / "alt.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE compliance_flags (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            entry_id INTEGER,
            work_date DATE NOT NULL,
            code VARCHAR(32) NOT NULL,
            severity VARCHAR(16) NOT NULL,
            detail VARCHAR(500),
            detected_at DATETIME,
            acknowledged_at DATETIME,
            acknowledged_by_id INTEGER,
            acknowledgement VARCHAR(500),
            state VARCHAR(16) DEFAULT 'detected',
            fingerprint VARCHAR(64),
            acknowledged_fingerprint VARCHAR(64),
            resolved_at DATETIME,
            reopened_at DATETIME,
            revision_no INTEGER DEFAULT 1,
            updated_at DATETIME
        );
        INSERT INTO compliance_flags
            (id, user_id, work_date, code, severity, detail, state,
             acknowledged_at, acknowledgement, revision_no)
        VALUES
            (1, 1, '2026-03-10', 'break_missing', 'warning', 'Alt', 'acknowledged',
             '2026-03-10 12:00:00', 'War abgesprochen', 2);
        """
    )
    connection.commit()
    connection.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    for key in ("DB_TYPE", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER",
                "DB_PASSWORD", "DB_SSL", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]

    from app import database, db_migrations

    db_migrations.run()

    with database.engine.begin() as conn:
        row = list(
            conn.exec_driver_sql(
                "SELECT code, state, acknowledgement, revision_no, handling_state "
                "FROM compliance_flags WHERE id = 1"
            )
        )[0]
    assert row[0] == "break_missing"
    assert row[1] == "acknowledged", "Bestätigung muss erhalten bleiben"
    assert row[2] == "War abgesprochen"
    assert row[3] == 2
    assert row[4] == "open"


def test_the_migration_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/zweimal.db")
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    for key in ("DB_TYPE", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER",
                "DB_PASSWORD", "DB_SSL", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    for name in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[name]

    from app import db_migrations

    db_migrations.run()
    db_migrations.run()


def test_entries_breaks_and_revisions_survive(client):
    """Buchungen, Pausen und Revisionen bleiben über die Migration erhalten."""
    from app import crud, models, revisions

    db = _db()
    try:
        entry = crud.start_running_entry(
            db, user_id=_admin_id(), started_at=datetime(2026, 3, 10, 8, 0)
        )
        entry_id = int(entry.id)
        crud.start_break(db, entry, datetime(2026, 3, 10, 12, 0))
        crud.end_break(db, entry, datetime(2026, 3, 10, 12, 30))
        crud.finish_running_entry(db, entry, datetime(2026, 3, 10, 17, 0))
    finally:
        db.close()

    db = _db()
    try:
        stored = crud.get_time_entry(db, entry_id)
        assert stored is not None
        assert len(stored.breaks) == 1
        actions = [item.action for item in revisions.history(db, entry_id)]
        assert models.RevisionAction.BREAK_STARTED in actions
        assert models.RevisionAction.BREAK_ENDED in actions
    finally:
        db.close()


def test_the_logical_backup_covers_the_new_columns(main):
    from app import models

    table = models.Base.metadata.tables["compliance_flags"]
    names = set(table.columns.keys())
    assert {"finding_key", "shift_start_utc", "handling_state"} <= names
    assert table in models.Base.metadata.sorted_tables
