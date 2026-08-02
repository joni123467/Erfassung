"""Tests für 0.19.0 – Ausgleich, Compliance-Recht, Historie, Zeitzone.

Was dieses Release schließt:

* **Der Ausgleich nach § 3 ArbZG rechnete mit dem falschen Nenner.** Der
  Durchschnitt lief über „Tage mit Buchungen". Wer an vier Tagen je zehn
  Stunden arbeitete, kam damit auf zehn Stunden Durchschnitt und war
  überfällig – obwohl § 3 auf den **werktäglichen** Durchschnitt abstellt und
  die freien Werktage mitzählen.
* **Die Ausgleichsfrist hing am Zeitraum, nicht am Tag.** Das rollierende
  Fenster ist immer gleich lang, also blieb rechnerisch nie eine Restlaufzeit
  übrig. Es war nie zu sagen, *was* bis *wann* auszugleichen ist.
* **``Time.View`` genügte, um die arbeitsrechtliche Bewertung zu ändern.** Ein
  Leserecht konnte Verstöße einordnen, Ausnahmen begründen und Ersatzruhetage
  eintragen – lauter Arbeitgeberentscheidungen.
* **Ausnahmen wurden ungeprüft übernommen.** Ein Ersatzruhetag durfte vor dem
  Arbeitstag liegen, auf einen Sonntag fallen, außerhalb der Frist des
  § 11 Abs. 3 ArbZG liegen oder mehrfach verwendet werden.
* **Die Bewertung wurde überschrieben.** Wer eine Begründung austauschte,
  hinterließ keine Spur.
* **``Time.Edit`` war zugleich ein Importrecht.** Wer fremde Buchungen
  korrigieren durfte, konnte ``source``, ``external_id`` und die UTC-Stempel
  frei setzen – eine Handbuchung ließ sich als Terminalstempelung ausgeben.
* **Die Betriebszeitzone stand nur in einer Umgebungsvariablen.** Sie war
  weder gespeichert noch ihre Änderung nachvollziehbar.
"""

from __future__ import annotations

import json
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
#: Dienstag, außerhalb jeder Zeitumstellung.
DAY = date(2026, 3, 10)
#: Sonntag – für §§ 9 ff. ArbZG.
SUNDAY = date(2026, 3, 8)


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


def _entry(*, start: time, end: time, day: date = DAY, breaks: int = 0,
           user_id: int | None = None):
    """Buchung mit gepflegten UTC-Stempeln anlegen."""
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
                started_at_utc=started.astimezone(timezone.utc).replace(tzinfo=None),
                ended_at_utc=ended.astimezone(timezone.utc).replace(tzinfo=None),
                tz_name="Europe/Berlin",
            ),
        )
    finally:
        db.close()


def _second_user(username: str = "kollege") -> int:
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


def _grant_only(*keys: str, scope: str = "all") -> None:
    """Dem Administrator genau die angegebenen Rechte lassen."""
    from app import crud, database

    db = database.SessionLocal()
    try:
        role = crud.create_role(db, name="Testrolle", description="", is_active=True,
                                permissions={key: scope for key in keys})
        admin = crud.get_user_by_username(db, "admin")
        admin.roles = [role]
        admin.groups = []
        db.commit()
    finally:
        db.close()


def _flag_for(day: date, code: str):
    """Feststellung des Administrators zu einem Tag holen (nach Neuberechnung)."""
    from app import compliance, models

    db = _db()
    try:
        compliance.refresh_day(db, _admin_id(), day)
        return (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.user_id == _admin_id())
            .filter(models.ComplianceFlag.work_date == day)
            .filter(models.ComplianceFlag.code == code)
            .first()
        )
    finally:
        db.close()


def _entry_payload(**overrides) -> dict:
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


def test_version_is_0170(client):
    assert client.app.version == "0.20.1"
    assert client.get("/health").json()["version"] == "0.20.1"


# ── 1. Ausgleich nach § 3 ArbZG: der Nenner ───────────────────────────────


def test_denominator_counts_werktage_not_days_with_bookings(client):
    """Der Durchschnitt läuft über Werktage, nicht über gebuchte Tage.

    Vier Zehnstundentage in einem 24-Wochen-Fenster ergeben rund 2400 Minuten
    auf über 140 Werktage – weit unter acht Stunden. Der alte Nenner „Tage mit
    Buchungen" hätte glatt 600 Minuten je Tag ausgewiesen.
    """
    from app import compensation

    for offset in range(4):
        day = DAY + timedelta(days=offset)
        _entry(start=time(6, 0), end=time(16, 0), day=day)

    db = _db()
    try:
        report = compensation.build_report(db, _admin_id(), DAY + timedelta(days=3))
    finally:
        db.close()

    worked = [item for item in report.counted_days if item.minutes]
    assert len(worked) == 4
    assert report.denominator > 100, "Werktage des Zeitraums, nicht Buchungstage"
    assert report.average_minutes < 480
    assert report.is_compliant


def test_sundays_never_count_as_werktag(client):
    """Werktage sind Mo–Sa. Ein Sonntag erhöht den Nenner nicht."""
    from app import compensation

    db = _db()
    try:
        rules = compensation.CompensationRules(weeks=1)
        report = compensation.build_report(
            db, _admin_id(), date(2026, 3, 14), rules=rules
        )
    finally:
        db.close()

    # Eine Woche Mo–Sa: sechs Werktage, kein siebter.
    assert report.denominator == 6


def test_holidays_and_vacation_leave_the_denominator(client):
    """Ausfalltage sollen keine Mehrarbeit ausgleichen."""
    from app import compensation, crud, models, schemas

    db = _db()
    try:
        crud.create_holiday(
            db,
            schemas.HolidayCreate(
                name="Testfeiertag", date=date(2026, 3, 11), source="custom"
            ),
        )
    finally:
        db.close()

    db = _db()
    try:
        rules = compensation.CompensationRules(weeks=1)
        report = compensation.build_report(
            db, _admin_id(), date(2026, 3, 14), rules=rules
        )
    finally:
        db.close()

    assert report.denominator == 5, "der Feiertag fällt aus dem Nenner"
    assert len(report.excluded_days) >= 1
    assert compensation.EXCLUDED_HOLIDAY in report.exclusion_summary()


def test_report_names_every_exclusion(client):
    """Keine stille Annahme: Jede Herausnahme ist benannt und zählbar."""
    from app import compensation

    db = _db()
    try:
        report = compensation.build_report(db, _admin_id(), DAY)
        text = report.describe()
    finally:
        db.close()

    assert str(report.denominator) in text
    assert "Werktage" in text
    assert isinstance(report.exclusion_summary(), dict)
    # Jeder Tag des Fensters ist genau einmal eingeordnet – gezählt oder mit
    # benanntem Grund ausgenommen. Eine stille dritte Kategorie gibt es nicht.
    assert len(report.counted_days) + len(report.excluded_days) == len(report.days)
    assert all(item.excluded for item in report.excluded_days)


# ── 2. Ausgleichsfristen je Überschreitungstag ────────────────────────────


def test_each_excess_day_gets_its_own_case(client):
    """Zwei Zehnstundentage sind zwei Vorgänge – nicht ein Saldo."""
    from app import compensation

    first = DAY
    second = DAY + timedelta(days=1)
    _entry(start=time(6, 0), end=time(16, 0), day=first)
    _entry(start=time(6, 0), end=time(16, 0), day=second)

    db = _db()
    try:
        cases = compensation.build_cases(db, _admin_id(), second)
    finally:
        db.close()

    dates = {case.work_date for case in cases}
    assert first in dates and second in dates
    for case in cases:
        assert case.excess_minutes == 120
        assert case.deadline > case.work_date


def test_deadline_is_bound_to_the_excess_day(client):
    """Die Frist hängt am Tag, nicht am rollierenden Fenster."""
    from app import compensation

    _entry(start=time(6, 0), end=time(16, 0), day=DAY)

    db = _db()
    try:
        rules = compensation.CompensationRules(weeks=24)
        cases = compensation.build_cases(db, _admin_id(), DAY, rules=rules)
    finally:
        db.close()

    assert len(cases) == 1
    case = cases[0]
    # 24 Wochen ab dem Beschäftigungstag – nicht ab „heute".
    assert case.deadline == DAY + timedelta(days=rules.days - 1)
    assert case.remaining_days(DAY) > 0


def test_a_single_ten_hour_day_is_required_not_overdue(client):
    """Ausgleichspflichtig heißt nicht überfällig."""
    from app import compliance, models

    _entry(start=time(6, 0), end=time(16, 0), day=DAY)

    db = _db()
    try:
        codes = {f["code"] for f in compliance.evaluate_day(db, _admin_id(), DAY)}
    finally:
        db.close()

    assert models.ComplianceCode.COMPENSATION_REQUIRED in codes
    assert models.ComplianceCode.COMPENSATION_OVERDUE not in codes


def test_compensation_is_assigned_oldest_first(client):
    """FIFO – der älteste Vorgang hat die kürzeste Restlaufzeit."""
    from app import compensation

    old = DAY
    new = DAY + timedelta(days=1)
    _entry(start=time(6, 0), end=time(16, 0), day=old)
    _entry(start=time(6, 0), end=time(16, 0), day=new)
    # Ein kurzer Tag schafft freie Kapazität.
    _entry(start=time(8, 0), end=time(12, 0), day=DAY + timedelta(days=2))

    db = _db()
    try:
        cases = compensation.build_cases(db, _admin_id(), DAY + timedelta(days=2))
    finally:
        db.close()

    by_date = {case.work_date: case for case in cases}
    assert by_date[old].compensated_minutes >= by_date[new].compensated_minutes


# ── 3. Recht Time.Compliance.Manage ───────────────────────────────────────


def test_permission_exists_and_is_scoped(client):
    from app import permissions

    assert "Time.Compliance.Manage" in permissions.PERMISSION_KEYS
    assert "Time.Compliance.Manage" in permissions.SCOPED_KEYS


def test_time_view_alone_cannot_acknowledge(client):
    """Ein Leserecht trifft keine Arbeitgeberentscheidung."""
    _entry(start=time(6, 0), end=time(17, 0), day=DAY)
    flag = _flag_for(DAY, "over_10h")
    assert flag is not None
    flag_id = flag.id

    _grant_only("Time.View")
    _login(client)
    response = client.post(
        f"/admin/compliance/{flag_id}/acknowledge",
        data={"note": "Passt schon"},
        headers=_api_token(client),
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_time_view_alone_cannot_document_an_exception(client):
    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag = _flag_for(SUNDAY, "sunday_work")
    assert flag is not None
    flag_id = flag.id

    _grant_only("Time.View")
    _login(client)
    response = client.post(
        f"/admin/compliance/{flag_id}/exception",
        data={
            "reason": "Notdienst",
            "legal_basis": "§ 10 Abs. 1 Nr. 3 ArbZG",
            "handling_state": "documented",
        },
        headers=_api_token(client),
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_refused_write_is_logged(client, tmp_path):
    """403 allein genügt nicht – der Versuch gehört ins Protokoll."""
    _entry(start=time(6, 0), end=time(17, 0), day=DAY)
    flag_id = _flag_for(DAY, "over_10h").id

    _grant_only("Time.View")
    _login(client)
    client.post(
        f"/admin/compliance/{flag_id}/acknowledge",
        data={"note": "Test"},
        headers=_api_token(client),
        follow_redirects=False,
    )

    from app import paths

    security_log = paths.LOGS_DIR / "security.log"
    assert security_log.exists()
    assert "Time.Compliance.Manage" in security_log.read_text(encoding="utf-8")


def test_manage_permission_allows_the_write(client):
    _entry(start=time(6, 0), end=time(17, 0), day=DAY)
    flag_id = _flag_for(DAY, "over_10h").id

    _grant_only("Time.View", "Time.Compliance.Manage")
    _login(client)
    response = client.post(
        f"/admin/compliance/{flag_id}/acknowledge",
        data={"note": "Ausgleich in der Folgewoche"},
        headers=_api_token(client),
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    from app import compliance

    db = _db()
    try:
        flag = compliance.get_flag(db, flag_id)
        assert flag.acknowledgement == "Ausgleich in der Folgewoche"
    finally:
        db.close()


def test_manage_permission_respects_the_scope(client):
    """Die Kenntnis einer ID genügt nicht – der Geltungsbereich entscheidet."""
    from app import compliance, models

    other = _second_user()
    _entry(start=time(6, 0), end=time(17, 0), day=DAY, user_id=other)
    db = _db()
    try:
        compliance.refresh_day(db, other, DAY)
        foreign = (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.user_id == other)
            .first()
        )
        foreign_id = foreign.id
    finally:
        db.close()

    _grant_only("Time.View", "Time.Compliance.Manage", scope="self")
    _login(client)
    response = client.post(
        f"/admin/compliance/{foreign_id}/acknowledge",
        data={"note": "Fremd"},
        headers=_api_token(client),
        follow_redirects=False,
    )
    assert response.status_code == 403


# ── 4. Sonn-/Feiertagsausnahmen strikt validieren ─────────────────────────


def _document(flag_id: int, **kwargs):
    from app import compliance, crud

    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        return compliance.document_exception(db, flag_id, user=admin, **kwargs)
    finally:
        db.close()


def test_exception_only_for_sunday_and_holiday_work(client):
    from app import compliance

    _entry(start=time(6, 0), end=time(17, 0), day=DAY)
    flag_id = _flag_for(DAY, "over_10h").id

    with pytest.raises(compliance.ExceptionError):
        _document(flag_id, reason="Egal", legal_basis="§ 7", handling_state="documented")


def test_documented_state_requires_reason_and_legal_basis(client):
    from app import compliance

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id

    with pytest.raises(compliance.ExceptionError):
        _document(flag_id, reason="Notdienst", legal_basis="", handling_state="documented")


def test_rest_granted_requires_a_rest_day(client):
    from app import compliance

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id

    with pytest.raises(compliance.ExceptionError):
        _document(
            flag_id,
            reason="Notdienst",
            legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
            handling_state="rest_granted",
        )


def test_not_required_still_needs_a_reason(client):
    """Die weitreichendste Behauptung darf nicht unbegründet dastehen."""
    from app import compliance

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id

    with pytest.raises(compliance.ExceptionError):
        _document(flag_id, reason="", handling_state="not_required")


def test_rest_day_before_the_work_day_is_refused(client):
    from app import compliance

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id

    with pytest.raises(compliance.ExceptionError):
        _document(
            flag_id,
            reason="Notdienst",
            legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
            replacement_rest_date=SUNDAY - timedelta(days=3),
            handling_state="rest_granted",
        )


def test_rest_day_outside_the_two_week_window_is_refused(client):
    """§ 11 Abs. 3: zwei Wochen bei Sonntagsarbeit."""
    from app import compliance

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id

    with pytest.raises(compliance.ExceptionError):
        _document(
            flag_id,
            reason="Notdienst",
            legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
            replacement_rest_date=SUNDAY + timedelta(days=20),
            handling_state="rest_granted",
        )


def test_rest_day_inside_the_window_is_accepted(client):
    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id

    flag = _document(
        flag_id,
        reason="Notdienst",
        legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
        replacement_rest_date=SUNDAY + timedelta(days=3),
        handling_state="rest_granted",
    )
    assert flag.replacement_rest_date == SUNDAY + timedelta(days=3)
    assert flag.handling_state == "rest_granted"


def test_a_sunday_cannot_be_the_rest_day(client):
    from app import compliance

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id

    with pytest.raises(compliance.ExceptionError):
        _document(
            flag_id,
            reason="Notdienst",
            legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
            replacement_rest_date=SUNDAY + timedelta(days=7),
            handling_state="rest_granted",
        )


def test_a_holiday_cannot_be_the_rest_day(client):
    from app import compliance, crud, schemas

    holiday = SUNDAY + timedelta(days=4)
    db = _db()
    try:
        crud.create_holiday(
            db,
            schemas.HolidayCreate(
                name="Testfeiertag", date=holiday, source="custom"
            ),
        )
    finally:
        db.close()

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id

    with pytest.raises(compliance.ExceptionError):
        _document(
            flag_id,
            reason="Notdienst",
            legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
            replacement_rest_date=holiday,
            handling_state="rest_granted",
        )


def test_a_rest_day_is_used_only_once(client):
    """Zwei Sonntage lassen sich nicht mit einem freien Mittwoch abgelten."""
    from app import compliance

    second_sunday = SUNDAY + timedelta(days=7)
    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    _entry(start=time(8, 0), end=time(14, 0), day=second_sunday)
    first_id = _flag_for(SUNDAY, "sunday_work").id
    second_id = _flag_for(second_sunday, "sunday_work").id
    rest_day = SUNDAY + timedelta(days=3)

    _document(
        first_id,
        reason="Notdienst",
        legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
        replacement_rest_date=rest_day,
        handling_state="rest_granted",
    )
    with pytest.raises(compliance.ExceptionError):
        _document(
            second_id,
            reason="Notdienst",
            legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
            replacement_rest_date=rest_day,
            handling_state="rest_granted",
        )


def test_holiday_work_gets_the_eight_week_window(client):
    """Werktagsfeiertag: acht Wochen statt zwei."""
    from app import compliance, models

    assert compliance.REST_DAY_DEADLINE_DAYS[models.ComplianceCode.SUNDAY_WORK] == 14
    assert compliance.REST_DAY_DEADLINE_DAYS[models.ComplianceCode.HOLIDAY_WORK] == 56


# ── 5. Append-only Historie ───────────────────────────────────────────────


def test_detection_writes_a_history_entry(client):
    from app import compliance, models

    _entry(start=time(6, 0), end=time(17, 0), day=DAY)
    flag_id = _flag_for(DAY, "over_10h").id

    db = _db()
    try:
        rows = compliance.history(db, flag_id)
    finally:
        db.close()

    assert rows
    assert rows[0].action == models.ComplianceAction.DETECTED


def test_every_change_appends_instead_of_overwriting(client):
    from app import compliance

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id

    _document(flag_id, reason="Erste Fassung", legal_basis="§ 10 ArbZG",
              handling_state="documented")
    _document(flag_id, reason="Zweite Fassung", legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
              handling_state="documented")

    db = _db()
    try:
        rows = compliance.history(db, flag_id)
        reasons = [row.reason for row in rows if row.reason]
    finally:
        db.close()

    assert "Erste Fassung" in reasons, "die alte Begründung bleibt erhalten"
    assert "Zweite Fassung" in reasons


def test_history_carries_before_and_after(client):
    from app import compliance, models

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id
    _document(flag_id, reason="Notdienst", legal_basis="§ 10 ArbZG",
              handling_state="documented")

    db = _db()
    try:
        rows = [
            row for row in compliance.history(db, flag_id)
            if row.action == models.ComplianceAction.EXCEPTION_DOCUMENTED
        ]
    finally:
        db.close()

    assert rows
    before = json.loads(rows[-1].before_json)
    after = json.loads(rows[-1].after_json)
    assert before["exception_reason"] is None
    assert after["exception_reason"] == "Notdienst"


def test_setting_a_rest_day_is_its_own_entry(client):
    from app import compliance, models

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id
    _document(
        flag_id,
        reason="Notdienst",
        legal_basis="§ 10 Abs. 1 Nr. 3 ArbZG",
        replacement_rest_date=SUNDAY + timedelta(days=3),
        handling_state="rest_granted",
    )

    db = _db()
    try:
        actions = {row.action for row in compliance.history(db, flag_id)}
    finally:
        db.close()

    assert models.ComplianceAction.REST_DAY_SET in actions


def test_history_page_is_readable_with_time_view(client):
    _entry(start=time(6, 0), end=time(17, 0), day=DAY)
    flag_id = _flag_for(DAY, "over_10h").id

    _grant_only("Time.View")
    _login(client)
    response = client.get(f"/admin/compliance/{flag_id}/history")
    assert response.status_code == 200
    assert "Historie der Kennzeichnung" in response.text


def test_history_is_part_of_the_subject_export(client):
    from app import crud, privacy

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id
    _document(flag_id, reason="Notdienst", legal_basis="§ 10 ArbZG",
              handling_state="documented")

    db = _db()
    try:
        export = privacy.subject_export(db, crud.get_user_by_username(db, "admin"))
    finally:
        db.close()

    assert export["compliance_historie"]
    assert any(
        row["begruendung"] == "Notdienst" for row in export["compliance_historie"]
    )
    assert export["kennzeichnungen"][0]["rechtsgrundlage"] == "§ 10 ArbZG"


def test_migration_20_writes_a_bestandsvermerk(client, tmp_path):
    """Bestandsfeststellungen bekommen einen ehrlichen Startvermerk."""
    from sqlalchemy import text

    from app import database, db_migrations, models

    _entry(start=time(6, 0), end=time(17, 0), day=DAY)
    _flag_for(DAY, "over_10h")

    with database.engine.begin() as connection:
        connection.execute(text("DELETE FROM compliance_logs"))
        connection.execute(text("DROP TABLE compliance_logs"))
        connection.execute(text("DELETE FROM schema_migrations WHERE version = 20"))

    db_migrations._add_compliance_logs(database.engine)

    db = _db()
    try:
        rows = db.query(models.ComplianceLog).all()
        assert rows
        assert all(row.action == models.ComplianceAction.MIGRATED for row in rows)
        assert all(row.actor_id is None for row in rows)
    finally:
        db.close()

    # Zweiter Lauf darf nichts verdoppeln.
    before = len(rows)
    db_migrations._add_compliance_logs(database.engine)
    db = _db()
    try:
        assert db.query(models.ComplianceLog).count() == before
    finally:
        db.close()


# ── 6. Terminal-/Importpfad getrennt ──────────────────────────────────────


def test_admin_api_cannot_fake_a_terminal_source(client):
    from app import crud

    other = _second_user()
    _grant_only("Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries",
        json=_entry_payload(user_id=other, source="timemoto", external_id="evt-1"),
        headers=_api_token(client),
    )
    assert response.status_code == 200, response.text

    db = _db()
    try:
        stored = crud.get_time_entry(db, response.json()["id"])
        assert stored.source != "timemoto"
        assert stored.external_id is None
    finally:
        db.close()


def test_admin_api_ignores_client_supplied_utc_stamps(client):
    """Ortszeit und UTC-Stempel dürfen nicht gegeneinander verschoben werden."""
    from app import crud

    other = _second_user()
    _grant_only("Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries",
        json=_entry_payload(
            user_id=other,
            started_at_utc="2020-01-01T00:00:00",
            ended_at_utc="2020-01-01T023:00:00".replace("023", "02"),
            tz_name="Pacific/Auckland",
        ),
        headers=_api_token(client),
    )
    assert response.status_code == 200, response.text

    db = _db()
    try:
        stored = crud.get_time_entry(db, response.json()["id"])
        assert stored.tz_name == "Europe/Berlin"
        assert stored.started_at_utc.date() == DAY
        # 08:00 Berlin im März = 07:00 UTC
        assert stored.started_at_utc.hour == 7
    finally:
        db.close()


def test_admin_api_may_still_set_status_and_manual(client):
    """Freigeben und Nachtrag kennzeichnen bleibt Teil der Korrektur."""
    from app import crud, models

    other = _second_user()
    _grant_only("Time.Edit")
    _login(client)
    response = client.post(
        "/api/time-entries",
        json=_entry_payload(
            user_id=other, status=models.TimeEntryStatus.PENDING, is_manual=True
        ),
        headers=_api_token(client),
    )
    assert response.status_code == 200, response.text

    db = _db()
    try:
        stored = crud.get_time_entry(db, response.json()["id"])
        assert stored.status == models.TimeEntryStatus.PENDING
        assert bool(stored.is_manual) is True
    finally:
        db.close()


def test_internal_import_path_keeps_source_and_external_id(client):
    """Der Terminalimport ruft ``crud`` direkt – er bleibt unberührt."""
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


# ── 7. Betriebszeitzone ───────────────────────────────────────────────────


def test_stored_timezone_beats_the_environment(client, monkeypatch):
    from app import app_config, worktime

    settings = app_config.load_system_settings()
    settings.timezone = "Europe/Warsaw"
    app_config.save_system_settings(settings)

    monkeypatch.setenv("ERFASSUNG_TIMEZONE", "UTC")
    assert worktime.timezone_name() == "Europe/Warsaw"


def test_timezone_change_is_audited(client):
    _login(client)
    token = _csrf(client, "/admin/system/settings")
    response = client.post(
        "/admin/system/settings",
        data={
            "level": "INFO",
            "audit_logging": "on",
            "rotation_max_mb": "5",
            "rotation_backup_count": "5",
            "auto_cleanup_days": "90",
            "sync_interval_minutes": "60",
            "shift_break_minutes": "360",
            "compensation_weeks": "24",
            "timezone_name": "Europe/Vienna",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    from app import app_config, paths

    assert app_config.load_system_settings().timezone == "Europe/Vienna"
    audit = (paths.LOGS_DIR / "audit.log").read_text(encoding="utf-8")
    assert "Betriebszeitzone geändert" in audit
    assert "Europe/Vienna" in audit


def test_unknown_timezone_is_refused_and_the_old_one_stays(client):
    _login(client)
    token = _csrf(client, "/admin/system/settings")
    response = client.post(
        "/admin/system/settings",
        data={
            "level": "INFO",
            "audit_logging": "on",
            "rotation_max_mb": "5",
            "rotation_backup_count": "5",
            "auto_cleanup_days": "90",
            "sync_interval_minutes": "60",
            "shift_break_minutes": "360",
            "compensation_weeks": "24",
            "timezone_name": "Mittelerde/Auenland",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "error=" in response.headers["location"]

    from app import app_config

    assert app_config.load_system_settings().timezone == "Europe/Berlin"


def test_changing_the_timezone_leaves_existing_bookings_alone(client):
    """Vergangene Zeiten dürfen nicht nachträglich verrutschen."""
    from app import app_config, crud

    entry = _entry(start=time(8, 0), end=time(16, 0), day=DAY)
    entry_id, stored_tz = entry.id, entry.tz_name

    settings = app_config.load_system_settings()
    settings.timezone = "Europe/Istanbul"
    app_config.save_system_settings(settings)

    db = _db()
    try:
        again = crud.get_time_entry(db, entry_id)
        assert again.tz_name == stored_tz == "Europe/Berlin"
        assert again.gross_minutes == 8 * 60
    finally:
        db.close()


def test_saving_the_form_keeps_the_other_settings(client):
    """Ein Formular ohne Feld darf keinen Wert zurücksetzen."""
    from app import app_config

    settings = app_config.load_system_settings()
    settings.compensation_exclude_vacation = False
    app_config.save_system_settings(settings)

    _login(client)
    token = _csrf(client, "/admin/system/settings")
    client.post(
        "/admin/system/settings",
        data={
            "level": "INFO",
            "rotation_max_mb": "5",
            "rotation_backup_count": "5",
            "auto_cleanup_days": "90",
            "sync_interval_minutes": "60",
            "shift_break_minutes": "360",
            "compensation_weeks": "12",
            "timezone_name": "Europe/Berlin",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    saved = app_config.load_system_settings()
    assert saved.compensation_weeks == 12
    assert saved.compensation_exclude_vacation is False


# ── Upgrade aus 0.14.2 / 0.15.0 / 0.16.0 ──────────────────────────────────


def test_all_migrations_are_applied(client):
    from app import database, db_schema

    applied = db_schema.applied_versions(database.engine)
    assert set(range(1, 21)) <= set(applied)


def test_schema_has_the_new_table(client):
    from sqlalchemy import inspect

    from app import database

    columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("compliance_logs")
    }
    assert {"flag_id", "action", "changed_at_utc", "before_json", "after_json"} <= columns


def test_config_carries_the_new_settings(client):
    from app import app_config

    settings = app_config.load_system_settings()
    assert settings.timezone
    assert app_config.COMPENSATION_MIN_WEEKS <= settings.compensation_weeks \
        <= app_config.COMPENSATION_MAX_WEEKS


def test_settings_import_rejects_an_unknown_timezone(client):
    from app import app_config

    errors = app_config.validate_import({"system": {"timezone": "Mittelerde/Auenland"}})
    assert errors


def test_no_secrets_in_the_logs(client):
    """Keine Passwörter, PINs, Tokens oder Standortdaten im Protokoll."""
    from app import paths

    _login(client)
    for log in paths.LOGS_DIR.glob("*.log"):
        text = log.read_text(encoding="utf-8", errors="ignore")
        assert "Admin!0000" not in text
        assert "password_hash" not in text

# ── 0.19.0 – erneute Logikprüfung ─────────────────────────────────────────


def test_work_on_an_excluded_holiday_still_counts(client):
    """Ein Feiertag neutralisiert nie tatsächlich geleistete Arbeitszeit."""
    from app import compensation, crud, schemas

    holiday = DAY
    db = _db()
    try:
        crud.upsert_holidays(
            db, [schemas.HolidayCreate(name="Eigener Feiertag", date=holiday, region="DE")]
        )
    finally:
        db.close()
    _entry(start=time(6, 0), end=time(16, 0), day=holiday)
    db = _db()
    try:
        report = compensation.build_report(db, _admin_id(), holiday)
        item = next(item for item in report.days if item.day == holiday)
        assert item.counts is True
        assert item.minutes == 10 * 60
        assert report.total_minutes >= 10 * 60
    finally:
        db.close()


def test_the_work_day_itself_cannot_be_its_rest_day(client):
    from app import compliance

    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    flag_id = _flag_for(SUNDAY, "sunday_work").id
    with pytest.raises(compliance.ExceptionError):
        _document(
            flag_id,
            reason="Notdienst",
            legal_basis="§ 10 ArbZG",
            replacement_rest_date=SUNDAY,
            handling_state="rest_granted",
        )


def test_a_day_with_work_cannot_be_a_replacement_rest_day(client):
    from app import compliance

    rest_day = SUNDAY + timedelta(days=3)
    _entry(start=time(8, 0), end=time(14, 0), day=SUNDAY)
    _entry(start=time(8, 0), end=time(12, 0), day=rest_day)
    flag_id = _flag_for(SUNDAY, "sunday_work").id
    with pytest.raises(compliance.ExceptionError):
        _document(
            flag_id,
            reason="Notdienst",
            legal_basis="§ 10 ArbZG",
            replacement_rest_date=rest_day,
            handling_state="rest_granted",
        )


def test_a_later_short_day_resolves_the_stored_compensation_flag(client):
    from app import compliance, models

    excess_day = DAY
    short_day = DAY + timedelta(days=1)
    _entry(start=time(6, 0), end=time(16, 0), day=excess_day)
    db = _db()
    try:
        compliance.refresh_day(db, _admin_id(), excess_day, reference_date=excess_day)
    finally:
        db.close()
    _entry(start=time(8, 0), end=time(14, 0), day=short_day)
    db = _db()
    try:
        compliance.refresh_open_compensations(db, reference_date=short_day)
        flags = (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.user_id == _admin_id())
            .filter(models.ComplianceFlag.work_date == excess_day)
            .filter(models.ComplianceFlag.code.in_((
                models.ComplianceCode.COMPENSATION_REQUIRED,
                models.ComplianceCode.COMPENSATION_DUE,
                models.ComplianceCode.COMPENSATION_OVERDUE,
            )))
            .all()
        )
        assert flags
        assert all(flag.state == models.ComplianceState.RESOLVED for flag in flags)
    finally:
        db.close()
