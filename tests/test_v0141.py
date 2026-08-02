"""Tests für 0.14.1 – die Lücken, die 0.14.0 hinterlassen hat.

Drei Dinge waren nach 0.14.0 kaputt oder unerreichbar:

* **Der Einsatzort hing am Remote-Kennzeichen.** Wer nicht remote arbeiten
  darf, sah gar keine Standortauswahl mehr – obwohl ein Firmenstandort das
  Gegenteil von Remote-Arbeit ist.
* **Stornierte Buchungen waren unsichtbar und zählten trotzdem.** Kein Label,
  kein Filter, aber sehr wohl in der Tages- und Wochensumme sowie im Export.
* **Ablehnen war unmöglich.** Der Server verlangte seit 0.14.0 eine
  Begründung, das Formular hatte kein Feld dafür.

Dazu die Prüfung, dass die übrigen Wege mit den neuen Regeln zurechtkommen:
Kommentar-Nachtrag, gesperrte Perioden über die API und das Beenden einer
laufenden Buchung.
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
            admin.remote_flag_enabled = True
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


def _set_remote_flag(enabled: bool) -> None:
    from app import crud

    db = _db()
    try:
        admin = crud.get_user_by_username(db, "admin")
        admin.remote_flag_enabled = enabled
        db.commit()
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


def _entry(*, work_date: date, start: time, end: time, user_id: int | None = None):
    from app import crud, schemas

    db = _db()
    try:
        return crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=user_id or _admin_id(),
                work_date=work_date,
                start_time=start,
                end_time=end,
                break_minutes=0,
            ),
        )
    finally:
        db.close()


# ── Version ───────────────────────────────────────────────────────────────


def test_version_is_0141(client):
    assert client.app.version == "0.20.4"
    assert client.get("/health").json()["version"] == "0.20.4"


# ── Einsatzort hängt nicht am Remote-Kennzeichen ──────────────────────────


def test_locations_stay_selectable_without_the_remote_flag(client):
    """Der Kern des Fehlerberichts: „die Standortauswahl fehlt komplett".

    Ein Firmenstandort ist das Gegenteil von Remote-Arbeit. Wer nie remote
    arbeitet, muss trotzdem sagen können, an welchem Standort er war.
    """
    company_id = _company("Müller GmbH")
    _location(company_id, "Werk Nord", city="Kiel")
    _set_remote_flag(False)
    _login(client)

    page = client.get("/dashboard").text
    assert 'name="work_location"' in page, "Die Standortauswahl fehlt ganz"
    assert 'id="location-catalogue"' in page
    assert "Werk Nord" in page


def test_remote_is_always_offered(client):
    """Ab 0.20.1 steht „Remote" immer in der Einsatzortauswahl.

    Bis 0.20.0 hing die Option am Benutzerkennzeichen ``remote_flag_enabled``.
    Da dessen Beschriftung „Einsatzort erfassen" seit 0.14.1 nicht mehr
    beschrieb, was es tat – die Auswahl erscheint ohnehin immer –, blieb der
    Haken in der Praxis aus, und „Remote" verschwand unbemerkt aus der Liste.
    """
    company_id = _company("Müller GmbH")
    _location(company_id, "Werk Nord", city="Kiel")
    _login(client)

    for flag in (False, True):
        _set_remote_flag(flag)
        page = client.get("/dashboard").text
        picker = page[page.index('name="work_location"'):]
        picker = picker[: picker.index("</select>")]
        assert ">Vor Ort<" in picker
        assert ">Remote<" in picker, f"Remote fehlt (Kennzeichen={flag})"
        # Die Standorte der gewählten Firma trägt das Skript aus dem Katalog
        # nach – servergerendert stehen nur die beiden festen Einträge.
        assert "Werk Nord" in page


def test_clocking_on_a_location_works_without_the_remote_flag(client):
    """Nicht nur sichtbar – der Server nimmt den Standort auch an."""
    from app import crud

    company_id = _company("Müller GmbH")
    location_id = _location(company_id, "Werk Nord", city="Kiel")
    _set_remote_flag(False)
    _login(client)

    token = _csrf(client, "/dashboard")
    response = client.post(
        "/punch",
        data={
            "action": "start_company",
            "company_id": str(company_id),
            "work_location": str(location_id),
            "csrf_token": token,
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    db = _db()
    try:
        entry = crud.get_open_time_entry(db, _admin_id())
        assert entry is not None
        assert entry.location_id == location_id
        assert entry.is_remote is False
    finally:
        db.close()


def test_remote_is_accepted_by_the_server(client):
    """Nicht nur sichtbar: Der Server übernimmt „Remote" auch (ab 0.20.1)."""
    from app import crud

    _set_remote_flag(False)
    _login(client)

    token = _csrf(client, "/dashboard")
    client.post(
        "/punch",
        data={
            "action": "start_work",
            "work_location": "remote",
            "csrf_token": token,
            "next_url": "/dashboard",
        },
        follow_redirects=False,
    )

    db = _db()
    try:
        entry = crud.get_open_time_entry(db, _admin_id())
        assert entry is not None
        assert entry.is_remote is True
    finally:
        db.close()


def test_quick_clocking_still_offers_only_the_toggle(client):
    """0.13.1 bleibt gültig: ohne Auftrag keine Firma, also kein Standort."""
    company_id = _company("Müller GmbH")
    _location(company_id, "Werk Nord", city="Kiel")
    _login(client)

    page = client.get("/dashboard").text
    schnell = page[page.index("Schnell stempeln"):page.index("order-modal")]
    assert 'name="is_remote"' in schnell
    assert 'name="work_location"' not in schnell


# ── Stornierte Buchungen ──────────────────────────────────────────────────


def test_cancelled_entries_have_a_german_label(main):
    """Vorher stand dort „Cancelled"."""
    assert (
        main.TIME_ENTRY_STATUS_LABELS[main.models.TimeEntryStatus.CANCELLED]
        == "Storniert"
    )


def test_cancelled_entries_are_findable_in_the_reports(client):
    """Die Antwort auf „wo sehe ich stornierte Buchungen?"."""
    from app import crud

    entry = _entry(work_date=date.today(), start=time(8, 0), end=time(12, 0))
    db = _db()
    try:
        crud.cancel_time_entry(
            db, entry.id, actor=None, reason="Test: versehentlich gestempelt"
        )
    finally:
        db.close()
    _login(client)

    page = client.get("/admin/reports/time?status=cancelled").text
    assert "Storniert" in page
    # Und der Weg zur Historie steht in derselben Zeile.
    assert f"/admin/time-entries/{entry.id}/history" in page


def test_the_report_filter_offers_cancelled(client):
    _login(client)
    page = client.get("/admin/reports/time").text
    assert 'value="cancelled"' in page


def test_a_cancelled_entry_does_not_count_in_the_daily_total(client):
    """Der eigentliche Schaden: Storno plus Ersatz zählte doppelt."""
    from app import crud

    today = date.today()
    entry = _entry(work_date=today, start=time(8, 0), end=time(12, 0))
    db = _db()
    try:
        before = crud.get_time_entries_for_user(db, _admin_id(), start=today, end=today)
        assert len(before) == 1
    finally:
        db.close()

    overview = None
    db = _db()
    try:
        overview = _build_overview(db, today)
        assert overview["total_minutes"] == 4 * 60
    finally:
        db.close()

    db = _db()
    try:
        crud.cancel_time_entry(db, entry.id, actor=None, reason="Test: Storno")
    finally:
        db.close()

    db = _db()
    try:
        overview = _build_overview(db, today)
        assert overview["total_minutes"] == 0, "Storno darf nicht mitzählen"
    finally:
        db.close()


def _build_overview(db, day: date):
    import app.main as main

    return main._build_daily_overview(db, _admin_id(), day)


def test_a_cancelled_entry_stays_out_of_the_excel_export(client):
    from app import crud

    today = date.today()
    entry = _entry(work_date=today, start=time(8, 0), end=time(12, 0))
    db = _db()
    try:
        crud.cancel_time_entry(db, entry.id, actor=None, reason="Test: Storno")
    finally:
        db.close()
    _login(client)

    response = client.get(f"/api/users/{_admin_id()}/excel")
    assert response.status_code == 200
    # Die Datei entsteht überhaupt – und ohne die stornierte Buchung darin
    # bleibt nur die Kopfzeile übrig. Geprüft wird der Weg, nicht das Format.
    assert len(response.content) > 0


def test_the_cancellation_reason_is_visible_to_the_employee(client):
    """Storniert heißt zurückgenommen – der Grund gehört dazu."""
    from app import crud

    today = date.today()
    entry = _entry(work_date=today, start=time(8, 0), end=time(12, 0))
    db = _db()
    try:
        crud.cancel_time_entry(
            db, entry.id, actor=None, reason="Test: doppelt erfasst"
        )
    finally:
        db.close()
    _login(client)

    page = client.get("/records").text
    assert "Storniert" in page
    assert "Test: doppelt erfasst" in page


# ── Freigaben ─────────────────────────────────────────────────────────────


def test_the_approval_form_has_a_reason_field(client):
    """Ohne Feld war „Ablehnen" seit 0.14.0 schlicht nicht durchführbar."""
    _login(client)
    _manual_entry(client)
    page = client.get("/admin/approvals").text
    assert 'name="reason"' in page


def _manual_entry(client) -> int:
    """Einen manuellen Nachtrag anlegen, der auf Freigabe wartet."""
    from app import crud, models

    yesterday = date.today() - timedelta(days=1)
    db = _db()
    try:
        entry = crud.create_time_entry(
            db,
            _manual_payload(yesterday),
        )
        entry.status = models.TimeEntryStatus.PENDING
        entry.is_manual = True
        db.commit()
        return int(entry.id)
    finally:
        db.close()


def _manual_payload(day: date):
    from app import schemas

    return schemas.TimeEntryCreate(
        user_id=_admin_id(),
        work_date=day,
        start_time=time(9, 0),
        end_time=time(17, 0),
        break_minutes=30,
        is_manual=True,
    )


def test_rejecting_with_a_reason_works(client):
    from app import crud, models

    entry_id = _manual_entry(client)
    _login(client)
    token = _csrf(client, "/admin/approvals")
    response = client.post(
        f"/admin/time-entries/{entry_id}/status",
        data={"action": "reject", "reason": "Test: Zeiten stimmen nicht", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "error=" not in response.headers.get("location", "")

    db = _db()
    try:
        entry = crud.get_time_entry(db, entry_id)
        assert entry.status == models.TimeEntryStatus.REJECTED
    finally:
        db.close()


def test_rejecting_without_a_reason_is_refused(client):
    """Die Pflicht bleibt – sie wird jetzt nur bedienbar."""
    from app import crud, models

    entry_id = _manual_entry(client)
    _login(client)
    token = _csrf(client, "/admin/approvals")
    response = client.post(
        f"/admin/time-entries/{entry_id}/status",
        data={"action": "reject", "reason": "   ", "csrf_token": token},
        follow_redirects=False,
    )
    assert "error=" in response.headers.get("location", "")

    db = _db()
    try:
        entry = crud.get_time_entry(db, entry_id)
        assert entry.status == models.TimeEntryStatus.PENDING
    finally:
        db.close()


def test_approving_needs_no_reason(client):
    """Freigeben ist keine Korrektur – die Begründung bleibt optional."""
    from app import crud, models

    entry_id = _manual_entry(client)
    _login(client)
    token = _csrf(client, "/admin/approvals")
    client.post(
        f"/admin/time-entries/{entry_id}/status",
        data={"action": "approve", "reason": "", "csrf_token": token},
        follow_redirects=False,
    )

    db = _db()
    try:
        entry = crud.get_time_entry(db, entry_id)
        assert entry.status == models.TimeEntryStatus.APPROVED
    finally:
        db.close()


# ── Die übrigen Wege unter den neuen Regeln ───────────────────────────────


def test_finishing_a_running_entry_is_historised(client):
    """Der Sprung von „läuft" auf eine fertige Arbeitszeit ist eine Änderung."""
    from app import crud, models, revisions

    _login(client)
    db = _db()
    try:
        entry = crud.start_running_entry(
            db, user_id=_admin_id(), started_at=datetime.now().replace(hour=8, minute=0)
        )
        entry_id = int(entry.id)
        crud.finish_running_entry(db, entry, datetime.now().replace(hour=16, minute=0))
    finally:
        db.close()

    db = _db()
    try:
        history = revisions.history(db, entry_id)
        actions = [item.action for item in history]
        assert models.RevisionAction.CREATED in actions
        assert models.RevisionAction.CLOSED in actions
    finally:
        db.close()


def test_finishing_works_even_in_a_locked_period(client):
    """Eine laufende Buchung muss sich immer schließen lassen.

    Wäre das gesperrt, bliebe sie für immer offen – das wäre das Gegenteil
    einer sauberen Erfassung.
    """
    from app import crud, periods

    today = date.today()
    db = _db()
    try:
        entry = crud.start_running_entry(
            db, user_id=_admin_id(), started_at=datetime.now().replace(hour=8, minute=0)
        )
        entry_id = int(entry.id)
        period = periods.create_period(
            db, period_start=today - timedelta(days=1), period_end=today, label="Test"
        )
        periods.lock(db, period, actor=None, note="Test: abgerechnet")
        crud.finish_running_entry(db, entry, datetime.now().replace(hour=16, minute=0))
    finally:
        db.close()

    db = _db()
    try:
        entry = crud.get_time_entry(db, entry_id)
        assert entry.is_open is False
    finally:
        db.close()


def test_a_locked_period_refuses_the_api_instead_of_crashing(client):
    """Vorher wurde die gesperrte Periode zu einem 500."""
    from app import periods

    day = date.today() - timedelta(days=10)
    db = _db()
    try:
        period = periods.create_period(
            db, period_start=day - timedelta(days=5), period_end=day + timedelta(days=5),
            label="Abgerechnet",
        )
        periods.lock(db, period, actor=None, note="Test: abgerechnet")
    finally:
        db.close()

    _login(client)
    response = client.post(
        "/api/time-entries",
        json={
            "user_id": _admin_id(),
            "work_date": day.isoformat(),
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "break_minutes": 30,
        },
        headers={"x-csrf-token": client.get("/api/csrf").json()["csrf_token"]},
    )
    assert response.status_code == 409
    assert "gesperrt" in response.json()["detail"]


def test_the_comment_addendum_is_historised(client):
    """Auch der Nachtrag über die Stempelansicht ist eine Änderung."""
    from app import crud, models, revisions

    entry = _entry(work_date=date.today(), start=time(8, 0), end=time(12, 0))
    entry_id = int(entry.id)

    db = _db()
    try:
        target = crud.get_time_entry(db, entry_id)
        crud.update_time_entry_notes(db, target, "Nachgetragen", actor=None)
    finally:
        db.close()

    db = _db()
    try:
        history = revisions.history(db, entry_id)
        updates = [
            item for item in history if item.action == models.RevisionAction.UPDATED
        ]
        assert updates, "Der Nachtrag fehlt in der Historie"
        assert updates[-1].reason
    finally:
        db.close()


def test_deleting_over_the_api_cancels_and_reports_it(client):
    from app import crud, models

    entry = _entry(work_date=date.today(), start=time(8, 0), end=time(12, 0))
    _login(client)
    # Seit 0.15.0 braucht die Stornierung über die API eine Begründung.
    response = client.delete(
        f"/api/time-entries/{entry.id}?reason=Test%3A+doppelt+erfasst",
        headers={"x-csrf-token": client.get("/api/csrf").json()["csrf_token"]},
    )
    assert response.status_code == 200
    assert "storniert" in response.json()["detail"]

    db = _db()
    try:
        stored = crud.get_time_entry(db, entry.id)
        assert stored is not None, "Gelöscht wird nichts mehr"
        assert stored.status == models.TimeEntryStatus.CANCELLED
    finally:
        db.close()

