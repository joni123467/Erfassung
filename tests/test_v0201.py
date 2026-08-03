"""Tests für 0.20.1 – gemeldete Bedienfehler, deutsche Ausgabe, toter Code.

Was diese Fassung schließt:

* **„Remote" fehlte in der Einsatzortauswahl.** Das Kennzeichen
  ``users.remote_flag_enabled`` stammte aus 0.9.21, als „Remote" die *gesamte*
  Einsatzorterfassung war. Seit 0.14.1 entfernte es nur noch **einen Eintrag**
  aus der Liste – bei unveränderter Beschriftung „Einsatzort erfassen".
* **Wochentage standen auf Englisch.** ``strftime('%A')`` richtet sich nach der
  Locale des Betriebssystems, und ``de_DE`` fehlt in schlanken Container-Abbildern.
* **Die Anmeldeseite war gesperrt gesetzt** (``letter-spacing: 0.3rem``).
* **„Anzurechnung"** ist kein deutsches Wort.
* **In der App klebten Einsatzort und „Arbeitszeit starten" aneinander.**
* **Ein erfülltes Sonntagsminimum war gelb hinterlegt** statt grün.
* **Systemeinstellungen setzten sich beim Speichern zurück.**
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
            # Ausdrücklich **aus**: Genau so hat der Fehler sich gezeigt.
            admin.remote_flag_enabled = False
            db.commit()
        finally:
            db.close()
        yield test_client


_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')

BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 3, 10)          # Dienstag


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


def _company_with_location(name: str = "Kunde AG", location: str = "Werk Nord") -> int:
    from app import crud, schemas

    db = _db()
    try:
        company = crud.create_company(
            db, schemas.CompanyCreate(name=name, description="", is_internal=False)
        )
        crud.create_company_location(
            db, company.id,
            schemas.CompanyLocationCreate(name=location, city="Kiel", is_primary=True),
        )
        return int(company.id)
    finally:
        db.close()


def _picker(html: str) -> str:
    """Den servergerenderten Einsatzort-Auswahlkasten herausschneiden."""
    start = html.index('name="work_location"')
    return html[start: html.index("</select>", start)]


# ── Version ───────────────────────────────────────────────────────────────


def test_version_is_0201(client):
    assert client.app.version == "0.20.5"
    assert client.get("/health").json()["version"] == "0.20.5"


# ── 1. „Remote" steht wieder zur Wahl ─────────────────────────────────────


def test_remote_is_in_the_picker_without_any_activation(client):
    """Der gemeldete Fehler: „Remote ist bei Standort im Web nicht verfügbar."."""
    _company_with_location()
    _login(client)

    picker = _picker(client.get("/dashboard").text)
    assert ">Vor Ort<" in picker
    assert ">Remote<" in picker


def test_remote_is_in_the_mobile_picker_too(client):
    _company_with_location()
    _login(client)

    picker = _picker(client.get("/mobile").text)
    assert ">Remote<" in picker


def test_quick_punch_still_offers_the_toggle(client):
    """Ohne Auftrag gibt es keine Firma – dort bleibt es beim Umschalter."""
    _login(client)
    page = client.get("/dashboard").text
    schnell = page[page.index("Schnell stempeln"):page.index("order-modal")]
    assert 'name="is_remote"' in schnell


def test_server_accepts_remote_without_activation(client):
    from app import crud

    _login(client)
    client.post(
        "/punch",
        data={"action": "start_work", "work_location": "remote",
              "csrf_token": _csrf(client, "/dashboard"), "next_url": "/dashboard"},
        follow_redirects=False,
    )
    db = _db()
    try:
        entry = crud.get_open_time_entry(db, _admin_id())
        assert entry is not None and entry.is_remote is True
    finally:
        db.close()


def test_user_form_no_longer_shows_the_misleading_switch(client):
    _login(client)
    html = client.get("/admin/users/new").text
    assert 'name="remote_flag_enabled"' not in html


def test_forms_mark_that_they_carry_a_location_field(client):
    """``location_field`` unterscheidet „nicht angehakt" von „Feld fehlt"."""
    _company_with_location()
    _login(client)
    assert 'name="location_field"' in client.get("/dashboard").text


def test_a_plain_comment_update_keeps_the_location(client):
    """Ohne Einsatzortfeld bleibt der gespeicherte Wert stehen."""
    from app import crud, models, schemas

    _login(client)
    db = _db()
    try:
        entry = crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=_admin_id(), work_date=date.today(),
                start_time=time(8, 0), end_time=time(12, 0),
                status=models.TimeEntryStatus.APPROVED, is_remote=True,
            ),
        )
        entry_id = entry.id
    finally:
        db.close()

    client.post(
        "/punch",
        data={"action": "update_notes", "entry_id": str(entry_id), "notes": "Nur Text",
              "csrf_token": _csrf(client, "/dashboard"), "next_url": "/dashboard"},
        follow_redirects=False,
    )
    db = _db()
    try:
        assert crud.get_time_entry(db, entry_id).is_remote is True
    finally:
        db.close()


# ── 2. Deutsche Wochentage ────────────────────────────────────────────────


ENGLISH_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday")


def test_weekday_filters_are_locale_independent(main):
    """Eigene Namenstabelle statt ``locale`` – ``de_DE`` fehlt oft im Abbild."""
    assert main._weekday_name(date(2026, 3, 10)) == "Dienstag"
    assert main._weekday_short(date(2026, 3, 10)) == "Di"
    assert main._month_name(date(2026, 3, 10)) == "März"
    assert main._german_date(date(2026, 3, 10)) == "Dienstag, 10.03.2026"


def test_weekday_filters_survive_nonsense(main):
    """Ein unbrauchbarer Wert darf keine Seite zerreißen."""
    assert main._weekday_name(None) == ""
    assert main._month_name("keine Zahl") == ""
    assert main._german_date(None) == ""


def test_dashboard_has_no_english_weekday(client):
    _login(client)
    for url in ("/dashboard", "/mobile"):
        html = client.get(url).text
        found = [day for day in ENGLISH_DAYS if day in html]
        assert not found, f"{url}: englischer Wochentag {found}"


# ── 3./5. Darstellung ─────────────────────────────────────────────────────


def test_login_has_no_letter_spacing(client):
    css = client.get("/static/styles.css").text
    block = css[css.index(".login-form input"):]
    block = block[: block.index("}")]
    assert "letter-spacing: normal" in block
    assert "0.3rem" not in block


def test_mobile_action_form_has_spacing(client):
    """Einsatzort und „Arbeitszeit starten" brauchen Abstand."""
    css = client.get("/static/styles.css").text
    block = css[css.index(".mobile-action-grid form {"):]
    block = block[: block.index("}")]
    assert "gap:" in block


# ── 4. „Anzurechnung" ─────────────────────────────────────────────────────


def test_the_invented_word_is_gone(client):
    _login(client)
    html = client.get("/admin/reports/time").text
    assert "Anzurechnung" not in html
    assert "Angerechnete Zeit" in html


def test_exports_use_the_correct_word():
    import pathlib

    for name in ("app/pdf_export.py", "app/excel_export.py"):
        assert "Anzurechnung" not in pathlib.Path(name).read_text(encoding="utf-8")


# ── 6. Erfülltes Sonntagsminimum ist grün ─────────────────────────────────


def test_met_sunday_minimum_is_green(client):
    """Gelb heißt „aufpassen" – erfüllt gehört grün.

    Seit 0.20.2 setzt ein positives Prüfurteil einen bekannten
    Beschäftigungsbeginn voraus; ohne ihn steht dort „Beschäftigungsbeginn
    fehlt". Der Test hinterlegt deshalb ein Eintrittsdatum.
    """
    from app import database, models

    with database.SessionLocal() as db:
        person = db.query(models.User).filter(
            models.User.id == _admin_id()
        ).first()
        person.employment_start_date = date(date.today().year, 1, 1)
        db.commit()

    _login(client)
    html = client.get("/admin/compliance").text
    marker = html.index("Sonntagsminimum erfüllt")
    span = html.rfind("<span", 0, marker)
    assert "license-state--valid" in html[span:marker]


def test_unreachable_sunday_minimum_stays_red(client):
    """Die kritische Meldung bleibt kritisch."""
    import pathlib

    template = pathlib.Path("templates/admin/compliance.html").read_text(encoding="utf-8")
    block = template[template.index("sunday_rule_impossible"):]
    assert "license-state--invalid" in block[:400]


# ── 7. Systemeinstellungen setzen sich nicht mehr zurück ──────────────────


def test_saving_settings_keeps_untouched_values(client):
    from app import app_config

    settings = app_config.load_system_settings()
    settings.timezone = "Europe/Vienna"
    settings.compensation_exclude_vacation = False
    app_config.save_system_settings(settings)

    _login(client)
    client.post(
        "/admin/system/settings",
        data={
            "level": "INFO", "rotation_max_mb": "5", "rotation_backup_count": "5",
            "auto_cleanup_days": "90", "sync_interval_minutes": "60",
            "shift_break_minutes": "360", "compensation_weeks": "24",
            "timezone_name": "Europe/Vienna",
            "csrf_token": _csrf(client, "/admin/system/settings"),
        },
        follow_redirects=False,
    )
    saved = app_config.load_system_settings()
    assert saved.timezone == "Europe/Vienna"
    assert saved.compensation_exclude_vacation is False


# ── 8. Toter Code ist weg ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "module, name",
    [
        ("app.crud", "get_group_by_name"),
        ("app.crud", "get_holiday_regions"),
        ("app.crud", "replace_holidays_for_region"),
        ("app.crud", "get_internal_locations"),
        ("app.crud", "get_active_terminals"),
        ("app.crud", "get_terminal_sync_runs"),
        ("app.database", "DB_TYPES"),
        ("app.db_migration_jobs", "clear_status"),
        ("app.db_migration_jobs", "TERMINAL_STATES"),
    ],
)
def test_dead_helpers_are_removed(main, module, name):
    import importlib

    assert not hasattr(importlib.import_module(module), name)


def test_apply_statutory_holidays_still_protects_custom_entries(client):
    """``replace_holidays_for_region`` ist weg – der sichere Weg bleibt.

    Die entfernte Funktion löschte *alle* Feiertage einer Region, auch die von
    Hand angelegten. Genau das darf nicht passieren.
    """
    from app import crud, schemas

    db = _db()
    try:
        crud.create_holiday(
            db,
            schemas.HolidayCreate(
                name="Betriebsfeier", date=date(2026, 5, 4), source="custom"
            ),
        )
        crud.apply_statutory_holidays(
            db, "DE", 2026,
            [schemas.HolidayCreate(name="Tag der Arbeit", date=date(2026, 5, 1),
                                   region="DE", source="statutory")],
        )
        names = {
            holiday.name for holiday in crud.get_holidays_for_year(db, 2026, "DE")
        }
        assert "Betriebsfeier" in names, "eigener Feiertag wurde mitgelöscht"
        assert "Tag der Arbeit" in names
    finally:
        db.close()


# ── Bestandsprüfung 0.18.0–0.20.0 ─────────────────────────────────────────


def test_annual_sunday_night_report_still_works(client):
    """Die Jahresprüfung aus 0.20.0 rechnet unverändert."""
    from app import compliance

    db = _db()
    try:
        report = compliance.annual_compliance_report(
            db, _admin_id(), 2026, reference_date=date(2026, 3, 10)
        )
    finally:
        db.close()

    assert report["required_free_sundays"] == 15
    assert report["worked_sundays"] == 0
    assert report["sunday_rule_met"] is False, "im März sind erst 10 Sonntage vorbei"
    assert report["sunday_rule_impossible"] is False
    assert report["free_sundays"] + report["future_sundays"] >= 15


def test_night_minutes_counts_across_midnight(client):
    """Nachtzeit 23–6 Uhr, auch über Mitternacht (0.20.0)."""
    from app import compliance, crud, models, schemas

    started = datetime.combine(DAY, time(22, 0)).replace(tzinfo=BERLIN)
    ended = datetime.combine(DAY + timedelta(days=1), time(3, 0)).replace(tzinfo=BERLIN)
    db = _db()
    try:
        entry = crud.create_time_entry(
            db,
            schemas.TimeEntryCreate(
                user_id=_admin_id(), work_date=DAY,
                start_time=time(22, 0), end_time=time(3, 0),
                status=models.TimeEntryStatus.APPROVED,
                started_at_utc=started.astimezone(timezone.utc).replace(tzinfo=None),
                ended_at_utc=ended.astimezone(timezone.utc).replace(tzinfo=None),
                tz_name="Europe/Berlin",
            ),
        )
        # 23:00–03:00 = vier Stunden in der Nachtzeit.
        assert compliance.night_minutes([entry]) == 240
    finally:
        db.close()


def test_compensation_report_still_uses_werktage(client):
    """Der Nenner aus 0.17.0/0.18.0 bleibt unangetastet."""
    from app import compensation

    db = _db()
    try:
        rules = compensation.CompensationRules(weeks=1)
        report = compensation.build_report(db, _admin_id(), date(2026, 3, 14), rules=rules)
    finally:
        db.close()

    assert report.denominator == 6, "Mo–Sa; der Sonntag zählt nicht"


def test_all_migrations_are_still_applied(client):
    from app import database, db_schema

    applied = set(db_schema.applied_versions(database.engine))
    assert set(range(1, 21)) <= applied
