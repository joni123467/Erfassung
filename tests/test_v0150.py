"""Tests für 0.15.0 – Absicherung der API, Schichtpausen und Feststellungen.

Die vier Lücken, die dieses Release schließt:

* **Die JSON-Schnittstelle war offen.** Neun Endpunkte hatten keinerlei
  Prüfung – darunter das Anlegen von Benutzern und der vollständige
  Arbeitszeitexport einer beliebigen Person. Der CSRF-Schutz war keine Hürde:
  ``GET /api/csrf`` liefert Sitzung und Token auch ohne Anmeldung.
* **Pausen wurden je Buchung geprüft.** Wer von 8 bis 12 für Kunde A und von
  12 bis 17 für Kunde B arbeitete, hatte nach alter Rechnung zweimal knapp
  unter sechs Stunden – und damit keine Pausenpflicht. Tatsächlich sind es
  neun Stunden am Stück.
* **UTC-Stempel wurden behauptet, aber nicht benutzt.** Über eine
  Zeitumstellung hinweg lag die Ruhezeit um eine Stunde daneben.
* **Feststellungen wurden gelöscht.** Bei jeder Neuberechnung verschwanden
  offene Kennzeichnungen spurlos.
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


# ── Version ───────────────────────────────────────────────────────────────


def test_version_is_0150(client):
    assert client.app.version == "0.20.7"
    assert client.get("/health").json()["version"] == "0.20.7"


# ── 1. Absicherung der Schnittstelle ──────────────────────────────────────


ANONYMOUS_READS = [
    "/api/users",
    "/api/groups",
]


@pytest.mark.parametrize("path", ANONYMOUS_READS)
def test_anonymous_reads_are_refused(client, path):
    """Vorher gaben diese Endpunkte jedem Aufrufer alle Stammdaten heraus."""
    response = client.get(path)
    assert response.status_code == 401, path


def test_the_excel_export_is_not_public(client):
    """Der schwerste Fall: vollständige Arbeitszeit einer Person, ohne Anmeldung."""
    response = client.get(f"/api/users/{_admin_id()}/excel")
    assert response.status_code == 401


def test_anonymous_writes_are_refused(client):
    """Ein CSRF-Token gibt es auch ohne Anmeldung – das war keine Hürde."""
    headers = _api_token(client)
    created = client.post(
        "/api/users",
        json={
            "username": "eindringling",
            "full_name": "Frei Erfunden",
            "email": "eindringling@example.org",
            "password": "Eindringling!0000",
        },
        headers=headers,
    )
    assert created.status_code == 401

    booked = client.post(
        "/api/time-entries",
        json={
            "user_id": _admin_id(),
            "work_date": DAY.isoformat(),
            "start_time": "08:00:00",
            "end_time": "16:00:00",
            "break_minutes": 30,
        },
        headers=headers,
    )
    assert booked.status_code == 401


def test_anonymous_cancellation_is_refused(client):
    entry = _entry(start=time(8, 0), end=time(12, 0))
    response = client.delete(
        f"/api/time-entries/{entry.id}?reason=Test",
        headers=_api_token(client),
    )
    assert response.status_code == 401

    from app import crud, models

    db = _db()
    try:
        assert crud.get_time_entry(db, entry.id).status != models.TimeEntryStatus.CANCELLED
    finally:
        db.close()


def test_missing_permission_gives_403(client):
    """Angemeldet, aber ohne Recht: 403, nicht 401 – der Unterschied zählt."""
    from app import crud

    _second_user()
    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        admin.roles = []
        admin.groups = []
        db.commit()
    finally:
        db.close()
    _login(client)

    assert client.get("/api/users").status_code == 403
    assert client.get("/api/groups").status_code == 403


def test_scope_cannot_be_bypassed_with_a_foreign_id(client):
    """Die Kenntnis einer fremden Benutzer-ID darf nichts freischalten."""
    from app import crud

    other = _second_user()
    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        admin.roles = []
        admin.groups = []
        db.commit()
    finally:
        db.close()
    _login(client)

    # Die eigenen Daten bleiben erreichbar …
    assert client.get(f"/api/users/{_admin_id()}/excel").status_code == 200
    # … die fremden nicht.
    assert client.get(f"/api/users/{other}/excel").status_code == 403


def test_booking_for_someone_else_needs_the_scope(client):
    from app import crud

    other = _second_user()
    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        admin.roles = []
        admin.groups = []
        db.commit()
    finally:
        db.close()
    _login(client)

    response = client.post(
        "/api/time-entries",
        json={
            "user_id": other,
            "work_date": DAY.isoformat(),
            "start_time": "08:00:00",
            "end_time": "16:00:00",
            "break_minutes": 30,
        },
        headers=_api_token(client),
    )
    assert response.status_code == 403


def test_api_cancellation_stores_actor_and_reason(client):
    """Eine Stornierung ohne Urheber wäre für die Nachvollziehbarkeit wertlos."""
    from app import models, revisions

    entry = _entry(start=time(8, 0), end=time(12, 0))
    _login(client)
    response = client.delete(
        f"/api/time-entries/{entry.id}?reason=Test%3A+doppelt+gestempelt",
        headers=_api_token(client),
    )
    assert response.status_code == 200

    db = _db()
    try:
        history = revisions.history(db, entry.id)
        storno = [
            item for item in history
            if item.action == models.RevisionAction.CANCELLED
        ]
        assert storno, "Die Stornierung fehlt in der Historie"
        assert storno[-1].reason == "Test: doppelt gestempelt"
        assert storno[-1].actor_id == _admin_id()
        assert storno[-1].actor_label
    finally:
        db.close()


def test_api_cancellation_without_a_reason_is_refused(client):
    entry = _entry(start=time(8, 0), end=time(12, 0))
    _login(client)
    response = client.delete(
        f"/api/time-entries/{entry.id}", headers=_api_token(client)
    )
    assert response.status_code == 400


def test_refused_access_is_logged(client, tmp_path):
    """Sicherheitsrelevante Abweisungen müssen sichtbar sein – ohne Geheimnisse."""
    client.get("/api/users")
    log = tmp_path / "logs" / "security.log"
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "/api/users" in content
    assert "Admin!0000" not in content


# ── 2. Compliance-Berechtigungen ──────────────────────────────────────────


def test_acknowledging_a_foreign_flag_is_refused(client):
    """Die Kenntnis einer flag_id darf nicht genügen."""
    from app import compliance, crud, models

    other = _second_user()
    _entry(start=time(6, 0), end=time(20, 0), user_id=other)
    db = _db()
    try:
        compliance.refresh_day(db, other, DAY)
        flag = (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.user_id == other)
            .first()
        )
        assert flag is not None
        flag_id = int(flag.id)
        admin = crud.get_user_by_username(db, "admin")
        # Nur Auswertungsrecht im eigenen Team – der Kollege gehört nicht dazu.
        admin.roles = []
        admin.groups = []
        db.commit()
    finally:
        db.close()
    _login(client)

    token = _csrf(client, "/dashboard")
    response = client.post(
        f"/admin/compliance/{flag_id}/acknowledge",
        data={"note": "Test", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code in (303, 403)

    db = _db()
    try:
        stored = compliance.get_flag(db, flag_id)
        assert stored.acknowledged_at is None, "Fremde Kennzeichnung wurde eingeordnet"
    finally:
        db.close()


# ── 3. Pausen über die ganze Schicht ──────────────────────────────────────


def test_two_bookings_without_a_break_trigger_the_warning(client):
    """Der Kern: 8–12 bei Kunde A, 12–17 bei Kunde B sind neun Stunden am Stück."""
    from app import models

    a = _company("Kunde A")
    b = _company("Kunde B")
    _entry(start=time(8, 0), end=time(12, 0), company_id=a)
    _entry(start=time(12, 0), end=time(17, 0), company_id=b)

    db = _db()
    try:
        assert models.ComplianceCode.BREAK_MISSING in _codes(db, _admin_id(), DAY)
    finally:
        db.close()


def test_a_customer_switch_is_not_a_break(client):
    """Auch eine kurze Lücke zwischen zwei Aufträgen ist keine Ruhepause."""
    from app import models

    a = _company("Kunde A")
    b = _company("Kunde B")
    _entry(start=time(8, 0), end=time(12, 0), company_id=a)
    # Zehn Minuten Fahrtzeit – unter dem Mindestabschnitt von 15 Minuten.
    _entry(start=time(12, 10), end=time(17, 0), company_id=b)

    db = _db()
    try:
        assert models.ComplianceCode.BREAK_MISSING in _codes(db, _admin_id(), DAY)
    finally:
        db.close()


def test_a_location_switch_is_not_a_break(client):
    """Standortwechsel beim selben Kunden ebenfalls nicht."""
    from app import models

    company = _company("Kunde A")
    nord = _location(company, "Werk Nord")
    sued = _location(company, "Werk Süd")
    _entry(start=time(8, 0), end=time(12, 0), company_id=company, location_id=nord)
    _entry(start=time(12, 5), end=time(17, 0), company_id=company, location_id=sued)

    db = _db()
    try:
        assert models.ComplianceCode.BREAK_MISSING in _codes(db, _admin_id(), DAY)
    finally:
        db.close()


def test_a_real_interruption_counts_as_a_break(client):
    """Eine echte Unterbrechung ab 15 Minuten wird angerechnet."""
    from app import models

    a = _company("Kunde A")
    b = _company("Kunde B")
    _entry(start=time(8, 0), end=time(12, 0), company_id=a)
    # 30 Minuten Pause – für neun Stunden Arbeitszeit genau richtig.
    _entry(start=time(12, 30), end=time(17, 0), company_id=b)

    db = _db()
    try:
        assert models.ComplianceCode.BREAK_MISSING not in _codes(db, _admin_id(), DAY)
    finally:
        db.close()


def test_fourteen_minutes_are_not_a_break(client):
    """Der Mindestabschnitt ist scharf: 14 Minuten zählen nicht."""
    from app import models

    _entry(start=time(8, 0), end=time(12, 0))
    _entry(start=time(12, 14), end=time(17, 0))

    db = _db()
    try:
        assert models.ComplianceCode.BREAK_MISSING in _codes(db, _admin_id(), DAY)
    finally:
        db.close()


@pytest.mark.parametrize(
    "end_time,expected_break",
    [
        (time(14, 0), False),   # exakt 6:00 – noch keine Pflicht
        (time(14, 1), True),    # 6:01 – 30 Minuten fällig
        (time(17, 0), True),    # exakt 9:00 – 30 Minuten fällig
        (time(17, 1), True),    # 9:01 – 45 Minuten fällig
    ],
)
def test_the_thresholds_are_exact(client, end_time, expected_break):
    """§ 4 ArbZG greift bei *mehr als* sechs bzw. neun Stunden."""
    from app import models

    _entry(start=time(8, 0), end=end_time)
    db = _db()
    try:
        has_flag = models.ComplianceCode.BREAK_MISSING in _codes(db, _admin_id(), DAY)
    finally:
        db.close()
    assert has_flag is expected_break


def test_exactly_nine_hours_needs_thirty_minutes(client):
    """Bei genau 9:00 Stunden genügen 30 Minuten – 45 erst darüber."""
    from app import models

    _entry(start=time(8, 0), end=time(12, 0))
    _entry(start=time(12, 30), end=time(17, 30))   # 9:00 Arbeitszeit, 30 min Pause

    db = _db()
    try:
        assert models.ComplianceCode.BREAK_MISSING not in _codes(db, _admin_id(), DAY)
    finally:
        db.close()


def test_night_work_across_midnight_is_one_shift(client):
    """Eine Nachtschicht zerfällt nicht am Kalendertagwechsel."""
    from app import compliance

    _entry(start=time(20, 0), end=time(5, 0))
    db = _db()
    try:
        shifts = compliance.build_shifts(
            compliance._entries_around(db, _admin_id(), DAY)
        )
        assert len(shifts) == 1
        assert shifts[0].work_minutes == 9 * 60
    finally:
        db.close()


# ── 4. Pausen in der Historie ─────────────────────────────────────────────


def test_break_start_and_end_are_historised(client):
    from app import crud, models, revisions

    _login(client)
    db = _db()
    try:
        entry = crud.start_running_entry(
            db, user_id=_admin_id(), started_at=datetime(2026, 3, 10, 8, 0)
        )
        entry_id = int(entry.id)
        crud.start_break(db, entry, datetime(2026, 3, 10, 12, 0), actor=None)
        crud.end_break(db, entry, datetime(2026, 3, 10, 12, 30), actor=None)
    finally:
        db.close()

    db = _db()
    try:
        actions = [item.action for item in revisions.history(db, entry_id)]
        assert models.RevisionAction.BREAK_STARTED in actions
        assert models.RevisionAction.BREAK_ENDED in actions
    finally:
        db.close()


def test_a_break_correction_needs_a_reason(client):
    from app import crud, models, revisions

    db = _db()
    try:
        entry = crud.start_running_entry(
            db, user_id=_admin_id(), started_at=datetime(2026, 3, 10, 8, 0)
        )
        entry_id = int(entry.id)
        crud.start_break(db, entry, datetime(2026, 3, 10, 12, 0))
        crud.end_break(db, entry, datetime(2026, 3, 10, 12, 30))
        db.refresh(entry)
        interval_id = int(entry.breaks[0].id)
    finally:
        db.close()

    db = _db()
    try:
        with pytest.raises(revisions.ReasonRequired):
            crud.correct_break(
                db, interval_id, actor=None, reason="",
                ended_at=datetime(2026, 3, 10, 12, 45),
            )
    finally:
        db.rollback()
        db.close()

    db = _db()
    try:
        crud.correct_break(
            db, interval_id, actor=None, reason="Test: falsch gestempelt",
            ended_at=datetime(2026, 3, 10, 12, 45),
        )
    finally:
        db.close()

    db = _db()
    try:
        actions = [item.action for item in revisions.history(db, entry_id)]
        assert models.RevisionAction.BREAK_CORRECTED in actions
    finally:
        db.close()


def test_a_cancelled_break_stays_visible(client):
    """Storniert heißt auf null gesetzt, nicht gelöscht."""
    from app import crud, models, revisions

    db = _db()
    try:
        entry = crud.start_running_entry(
            db, user_id=_admin_id(), started_at=datetime(2026, 3, 10, 8, 0)
        )
        entry_id = int(entry.id)
        crud.start_break(db, entry, datetime(2026, 3, 10, 12, 0))
        crud.end_break(db, entry, datetime(2026, 3, 10, 12, 30))
        db.refresh(entry)
        interval_id = int(entry.breaks[0].id)
        crud.cancel_break(db, interval_id, actor=None, reason="Test: Fehleingabe")
    finally:
        db.close()

    db = _db()
    try:
        interval = (
            db.query(models.BreakInterval)
            .filter(models.BreakInterval.id == interval_id)
            .first()
        )
        assert interval is not None, "Gelöscht wird nichts"
        assert interval.minutes == 0
        actions = [item.action for item in revisions.history(db, entry_id)]
        assert models.RevisionAction.BREAK_CANCELLED in actions
    finally:
        db.close()


# ── 5. UTC und Zeitzonen ──────────────────────────────────────────────────


def test_utc_stamps_are_actually_used(client):
    """Bis 0.14.2 behauptete die Funktion den UTC-Vorrang nur."""
    from app import compliance

    entry = _entry(start=time(8, 0), end=time(16, 0))
    db = _db()
    try:
        stored = db.query(type(entry)).filter_by(id=entry.id).first()
        start, end = compliance._entry_bounds(stored)
    finally:
        db.close()
    assert start.tzinfo is not None, "Zeitpunkte müssen zonenbehaftet sein"
    assert start == datetime(2026, 3, 10, 7, 0, tzinfo=timezone.utc)  # MEZ = UTC+1
    assert end == datetime(2026, 3, 10, 15, 0, tzinfo=timezone.utc)


def test_legacy_entries_fall_back_to_local_time(client):
    """Bestandsbuchungen ohne UTC-Stempel müssen weiter funktionieren."""
    from app import compliance

    entry = _entry(start=time(8, 0), end=time(16, 0), utc=False)
    db = _db()
    try:
        stored = db.query(type(entry)).filter_by(id=entry.id).first()
        start, end = compliance._entry_bounds(stored)
    finally:
        db.close()
    assert start.tzinfo is not None
    assert int((end - start).total_seconds() // 3600) == 8


def test_spring_forward_keeps_the_rest_period_honest(client):
    """In der Nacht zum 29.03.2026 fällt eine Stunde aus (MEZ → MESZ).

    Wer am 28. um 22:00 aufhört und am 29. um 8:00 anfängt, hat in Ortszeit
    zehn Stunden Ruhe – tatsächlich sind es nur neun. Ohne UTC-Rechnung wäre
    das unentdeckt geblieben.
    """
    from app import compliance, models

    _entry(start=time(14, 0), end=time(22, 0), day=date(2026, 3, 28))
    _entry(start=time(8, 0), end=time(16, 0), day=date(2026, 3, 29))

    db = _db()
    try:
        codes = _codes(db, _admin_id(), date(2026, 3, 29))
    finally:
        db.close()
    assert models.ComplianceCode.REST_UNDER_11H in codes


def test_autumn_back_gives_an_extra_hour(client):
    """In der Nacht zum 25.10.2026 gibt es eine Stunde mehr (MESZ → MEZ).

    22:00 bis 8:00 sind in Ortszeit zehn Stunden, tatsächlich aber elf – die
    Ruhezeit ist eingehalten.
    """
    from app import compliance, models

    _entry(start=time(14, 0), end=time(22, 0), day=date(2026, 10, 24))
    _entry(start=time(8, 0), end=time(16, 0), day=date(2026, 10, 25))

    db = _db()
    try:
        codes = _codes(db, _admin_id(), date(2026, 10, 25))
    finally:
        db.close()
    assert models.ComplianceCode.REST_UNDER_11H not in codes


# ── 6. Feststellungen versionieren ────────────────────────────────────────


def test_a_resolved_finding_is_kept(client):
    """Nicht mehr zutreffende Feststellungen werden erledigt, nicht gelöscht."""
    from app import compliance, crud, models, schemas

    entry = _entry(start=time(6, 0), end=time(20, 0))
    db = _db()
    try:
        compliance.refresh_day(db, _admin_id(), DAY)
        before = db.query(models.ComplianceFlag).count()
        assert before > 0
        crud.update_time_entry(
            db,
            entry.id,
            schemas.TimeEntryCreate(
                user_id=_admin_id(),
                work_date=DAY,
                start_time=time(9, 0),
                end_time=time(13, 0),
                break_minutes=0,
            ),
            reason="Test: Korrektur",
        )
        compliance.refresh_day(db, _admin_id(), DAY)
        flags = db.query(models.ComplianceFlag).all()
        assert len(flags) >= before, "Feststellungen dürfen nicht verschwinden"
        assert any(
            flag.state == models.ComplianceState.RESOLVED for flag in flags
        )
    finally:
        db.close()


def test_a_change_after_acknowledgement_reopens_the_finding(client):
    """Eine Bestätigung gilt nur für den geprüften Datenstand."""
    from app import compliance, crud, models, schemas

    entry = _entry(start=time(6, 0), end=time(18, 0))
    db = _db()
    try:
        compliance.refresh_day(db, _admin_id(), DAY)
        flag = (
            db.query(models.ComplianceFlag)
            .filter(models.ComplianceFlag.code == models.ComplianceCode.OVER_10H)
            .first()
        )
        assert flag is not None
        flag_id = int(flag.id)
        admin = crud.get_user_by_username(db, "admin")
        compliance.acknowledge(db, flag_id, user=admin, note="Test: Ausgleich vereinbart")
        assert compliance.get_flag(db, flag_id).state == models.ComplianceState.ACKNOWLEDGED

        # Jetzt ändert sich die Buchung – die Bestätigung passt nicht mehr.
        crud.update_time_entry(
            db,
            entry.id,
            schemas.TimeEntryCreate(
                user_id=_admin_id(),
                work_date=DAY,
                start_time=time(5, 0),
                end_time=time(19, 0),
                break_minutes=0,
            ),
            reason="Test: Korrektur nach oben",
        )
        compliance.refresh_day(db, _admin_id(), DAY)
        reopened = compliance.get_flag(db, flag_id)
        assert reopened.state == models.ComplianceState.REOPENED
        assert reopened.acknowledged_at is None
        assert reopened.revision_no > 1
    finally:
        db.close()


def test_an_unchanged_finding_keeps_its_acknowledgement(client):
    """Ohne Änderung soll niemand zweimal dasselbe einordnen müssen."""
    from app import compliance, crud, models

    _entry(start=time(6, 0), end=time(18, 0))
    db = _db()
    try:
        compliance.refresh_day(db, _admin_id(), DAY)
        flag = db.query(models.ComplianceFlag).first()
        flag_id = int(flag.id)
        admin = crud.get_user_by_username(db, "admin")
        compliance.acknowledge(db, flag_id, user=admin, note="Test: gesehen")
        compliance.refresh_day(db, _admin_id(), DAY)
        assert compliance.get_flag(db, flag_id).state == models.ComplianceState.ACKNOWLEDGED
    finally:
        db.close()


# ── 7. Kunden sind keine Arbeitgeber ──────────────────────────────────────


def test_two_customers_share_one_working_day(client):
    """Arbeit bei zwei Kunden ist ein Arbeitstag, kein zweimal halber."""
    from app import models

    a = _company("Kunde A")
    b = _company("Kunde B")
    nord = _location(a, "Werk Nord", city="Kiel")
    sued = _location(b, "Werk Süd", city="München")
    _entry(start=time(6, 0), end=time(12, 0), company_id=a, location_id=nord)
    _entry(start=time(12, 30), end=time(19, 0), company_id=b, location_id=sued)

    db = _db()
    try:
        codes = _codes(db, _admin_id(), DAY)
    finally:
        db.close()
    # 12:30 Stunden Arbeitszeit über zwei Kunden – zusammen über zehn Stunden.
    assert models.ComplianceCode.OVER_10H in codes


def test_a_holiday_at_the_customer_site_changes_nothing(client):
    """Fronleichnam gilt in Bayern, nicht bundesweit.

    Wer für einen bayerischen Kunden arbeitet, bekommt deswegen weder eine
    Feiertagsgutschrift noch eine Feiertagswarnung – maßgeblich ist die eigene
    Region.
    """
    from app import crud, models, schemas, services

    company = _company("Kunde in Bayern")
    _location(company, "Werk München", city="München")
    # Fronleichnam 2026: 4. Juni, Donnerstag – nur in einigen Bundesländern.
    fronleichnam = date(2026, 6, 4)
    db = _db()
    try:
        # Die eigene Region kennt den Tag nicht: nichts eingetragen.
        holidays = crud.get_holiday_dates_in_range(db, fronleichnam, fronleichnam)
        assert fronleichnam not in holidays
    finally:
        db.close()

    _entry(start=time(8, 0), end=time(16, 0), day=fronleichnam, company_id=company)
    db = _db()
    try:
        codes = _codes(db, _admin_id(), fronleichnam)
        assert models.ComplianceCode.HOLIDAY_WORK not in codes
        person = crud.get_user_by_username(db, "admin")
        credit = services.holiday_credit_minutes(
            person,
            crud.get_holiday_dates_in_range(db, fronleichnam, fronleichnam),
            fronleichnam,
            fronleichnam,
        )
        assert credit == 0
    finally:
        db.close()


def test_the_own_region_holiday_applies_to_customer_work(client):
    """Umgekehrt: Der eigene Feiertag gilt auch bei Arbeit für einen Kunden."""
    from app import crud, models, schemas, services

    company = _company("Kunde anderswo")
    location = _location(company, "Werk Süd", city="München")
    # Ein Feiertag der zentral konfigurierten eigenen Region.
    own = date(2026, 5, 1)
    db = _db()
    try:
        crud.upsert_holidays(
            db, [schemas.HolidayCreate(name="Tag der Arbeit", date=own, region="DE")]
        )
    finally:
        db.close()

    _entry(
        start=time(8, 0), end=time(16, 0), day=own,
        company_id=company, location_id=location,
    )
    db = _db()
    try:
        codes = _codes(db, _admin_id(), own)
        assert models.ComplianceCode.HOLIDAY_WORK in codes
        person = crud.get_user_by_username(db, "admin")
        credit = services.holiday_credit_minutes(
            person,
            crud.get_holiday_dates_in_range(db, own, own),
            own,
            own,
        )
        assert credit == 480
    finally:
        db.close()


# ── 8. Migration und Bestand ──────────────────────────────────────────────


def test_migration_18_is_registered(main):
    from app import db_migrations

    numbers = [number for number, _ in db_migrations.MIGRATIONS]
    assert 18 in numbers
    assert numbers == sorted(numbers), "Migrationen müssen fortlaufend bleiben"


def test_the_flag_lifecycle_columns_exist(main):
    from sqlalchemy import inspect

    from app import database

    columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("compliance_flags")
    }
    for expected in (
        "state", "fingerprint", "acknowledged_fingerprint",
        "resolved_at", "reopened_at", "revision_no", "updated_at",
    ):
        assert expected in columns, expected


def test_migration_preserves_existing_flags(tmp_path, monkeypatch):
    """Aufstieg von einem 0.14.x-Bestand: Kennzeichnungen bleiben erhalten."""
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
            acknowledgement VARCHAR(500)
        );
        INSERT INTO compliance_flags
            (id, user_id, work_date, code, severity, detail, detected_at,
             acknowledged_at, acknowledgement)
        VALUES
            (1, 1, '2026-03-10', 'over_8h', 'warning', 'Alt', '2026-03-10 10:00:00',
             NULL, NULL),
            (2, 1, '2026-03-11', 'over_10h', 'critical', 'Alt bestätigt',
             '2026-03-11 10:00:00', '2026-03-11 12:00:00', 'War abgesprochen');
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
        rows = list(
            conn.exec_driver_sql(
                "SELECT id, code, detail, state, acknowledgement "
                "FROM compliance_flags ORDER BY id"
            )
        )
    assert len(rows) == 2, "Bestehende Kennzeichnungen dürfen nicht verschwinden"
    assert rows[0][3] == "detected"
    assert rows[1][3] == "acknowledged", "Bestätigte behalten ihren Zustand"
    assert rows[1][4] == "War abgesprochen"


def test_the_migration_is_idempotent(tmp_path, monkeypatch):
    """Zweimal ausführen darf nichts beschädigen."""
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


def test_the_logical_backup_covers_the_new_columns(main):
    """Neue Spalten wandern automatisch in Backup und Cross-DB-Restore."""
    from app import models

    table = models.Base.metadata.tables["compliance_flags"]
    names = set(table.columns.keys())
    assert {"state", "fingerprint", "revision_no"} <= names
    assert table in models.Base.metadata.sorted_tables

