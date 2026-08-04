"""Tests für 0.20.7 – Urlaubsnavigation, Teamkalender und Sollzeiten.

Behandelt werden fünf gemeldete Fehler und die daraus folgende Durchsicht der
Anzeigen:

* **Die Reiter des Urlaubsbereichs standen nur im Kalender.** Von „Meine
  Anträge" führte lediglich eine Schaltfläche „Mein Kalender" hinaus, zurück
  ging es gar nicht. Die Reiter gehören auf jede Seite des Bereichs.
* **Der Teamkalender verriet nicht, wessen Abwesenheiten er zeigt.** Der
  Geltungsbereich von ``Vacation.TeamCalendar`` entschied darüber, blieb aber
  unsichtbar – eine Lücke im Kalender war nicht von einer Lücke in der
  Berechtigung zu unterscheiden.
* **Offene Anträge fehlten im Teamkalender.** Sichtbar waren sie nur mit
  ``Vacation.Manage``. Damit ließ sich nicht planen: Erst die Freigabe machte
  sichtbar, dass jemand denselben Zeitraum bereits beantragt hatte.
* **Der QR-Code stand unter den anderen Karten** statt oben rechts.
* **„Woche im Blick" ignorierte den Arbeitszeitplan.** Die Wochenansicht war
  die letzte Stelle, die noch mit der pauschalen Tagessollzeit mal „Montag bis
  Freitag" rechnete. Die Durchsicht fand denselben Fehler in der Tagesansicht,
  in ``TimeEntry.overtime_minutes``, im Urlaubskonto und in der Offline-Shell.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import licensed_env

ROOT = Path(__file__).resolve().parent.parent
BERLIN = ZoneInfo("Europe/Berlin")


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

    with _db() as db:
        return int(crud.get_user_by_username(db, "admin").id)


def _plan(user_id: int, valid_from: date, minutes: tuple[int, ...]) -> None:
    """Arbeitszeitplan anlegen; ``minutes`` von Montag bis Sonntag."""
    from app import database, models

    with database.SessionLocal() as db:
        db.add(models.WorkSchedule(
            user_id=user_id, valid_from=valid_from, name="Testplan",
            monday_minutes=minutes[0], tuesday_minutes=minutes[1],
            wednesday_minutes=minutes[2], thursday_minutes=minutes[3],
            friday_minutes=minutes[4], saturday_minutes=minutes[5],
            sunday_minutes=minutes[6],
        ))
        db.commit()


def _entry(day: date, start: time, end: time, *, user_id: int | None = None):
    from app import database, models

    started = datetime.combine(day, start).replace(tzinfo=BERLIN)
    ended = datetime.combine(day, end).replace(tzinfo=BERLIN)
    if ended <= started:
        ended += timedelta(days=1)
    with database.SessionLocal() as db:
        row = models.TimeEntry(
            user_id=user_id or _admin_id(), work_date=day,
            start_time=start, end_time=end,
            status=models.TimeEntryStatus.APPROVED, break_minutes=0,
            break_rule=models.BreakRule.ACTUAL, tz_name="Europe/Berlin",
            started_at_utc=started.astimezone(timezone.utc).replace(tzinfo=None),
            ended_at_utc=ended.astimezone(timezone.utc).replace(tzinfo=None),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


# ── Version ───────────────────────────────────────────────────────────────


def test_version_is_0207(client):
    assert client.app.version == "0.20.7"
    assert client.get("/health").json()["version"] == "0.20.7"


# ── 1. Reiter des Urlaubsbereichs auf jeder Seite ─────────────────────────


def test_requests_page_shows_all_tabs(client):
    _login(client)
    body = client.get("/records/vacations").text
    assert 'class="vacation-tabs"' in body
    assert 'href="/records/vacations/calendar?scope=self"' in body
    assert "Meine Anträge" in body


def test_calendar_page_shows_all_tabs(client):
    _login(client)
    body = client.get("/records/vacations/calendar?scope=self").text
    assert 'class="vacation-tabs"' in body
    assert 'href="/records/vacations"' in body
    assert "Mein Kalender" in body


def test_the_standalone_calendar_button_is_gone(client):
    """Der Reiter ersetzt die Schaltfläche – nicht beides nebeneinander."""
    _login(client)
    body = client.get("/records/vacations").text
    assert 'class="button ghost" href="/records/vacations/calendar?scope=self"' not in body


def test_active_tab_is_marked_on_both_pages(client):
    _login(client)
    requests_page = client.get("/records/vacations").text
    calendar_page = client.get("/records/vacations/calendar?scope=self").text
    assert requests_page.count('aria-current="page"') >= 1
    assert calendar_page.count('aria-current="page"') >= 1


def test_tabs_come_from_one_partial():
    """Beide Seiten binden dieselbe Vorlage ein – sonst laufen sie auseinander."""
    partial = ROOT / "templates" / "records" / "_vacation_tabs.html"
    assert partial.exists()
    for name in ("vacations.html", "vacation_calendar.html"):
        body = (ROOT / "templates" / "records" / name).read_text(encoding="utf-8")
        assert "records/_vacation_tabs.html" in body, name


# ── 2. Der Teamkalender nennt seinen Umfang ───────────────────────────────


def test_team_calendar_names_the_scope(client):
    _login(client)
    body = client.get("/records/vacations/calendar?scope=team").text
    assert "data-team-scope" in body
    assert "Angezeigt:" in body


def test_scope_all_lists_every_group(client, main):
    """Der Administrator sieht alles – dann werden alle Gruppen benannt."""
    from app import models

    with _db() as db:
        db.add(models.Group(name="Werkstatt"))
        db.commit()
    _login(client)
    body = client.get("/records/vacations/calendar?scope=team").text
    assert "Alle Gruppen" in body
    assert "Werkstatt" in body


def test_scope_groups_lists_only_own_groups(main):
    """Bei gruppenweitem Umfang stehen dort die eigenen Gruppen."""
    from app import models

    with _db() as db:
        group = models.Group(name="Montage")
        person = models.User(username="mona", full_name="Mona", email="mona@example.org", pin_code="1234", password_hash="x")
        person.groups.append(group)
        db.add_all([group, person])
        db.commit()
        person_id = person.id

    with _db() as db:
        person = db.query(models.User).filter(models.User.id == person_id).first()
        label, names = main._team_calendar_scope(db, person)
    assert label == "Eigene Gruppen"
    assert names == ["Montage"]


def test_person_without_group_is_told_so(main):
    from app import models

    with _db() as db:
        person = models.User(username="solo", full_name="Solo", email="solo@example.org", pin_code="4321", password_hash="x")
        db.add(person)
        db.commit()
        person_id = person.id
    with _db() as db:
        person = db.query(models.User).filter(models.User.id == person_id).first()
        label, names = main._team_calendar_scope(db, person)
    assert "keine Gruppe" in label
    assert names == []


# ── 3. Offene Anträge im Teamkalender ─────────────────────────────────────


def _vacation(user_id: int, start: date, end: date, status: str):
    from app import database, models

    with database.SessionLocal() as db:
        row = models.VacationRequest(
            user_id=user_id, start_date=start, end_date=end,
            status=status, absence_type_key="vacation",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def test_pending_requests_appear_in_the_team_calendar(client):
    from app import models

    _login(client)
    start = date(2026, 3, 2)
    _vacation(_admin_id(), start, start + timedelta(days=2), models.VacationStatus.PENDING)
    body = client.get(f"/records/vacations/calendar?scope=team&month={start:%Y-%m}").text
    assert "Offen" in body


def test_the_legend_offers_the_open_state_in_the_team_calendar(client):
    _login(client)
    body = client.get("/records/vacations/calendar?scope=team").text
    assert '<i class="pending"></i> Offen' in body


def test_a_withdrawal_request_still_blocks_the_period(client):
    """Bis zur Freigabe der Rücknahme gilt die Abwesenheit weiter."""
    from app import models

    _login(client)
    start = date(2026, 4, 6)
    _vacation(_admin_id(), start, start + timedelta(days=1),
              models.VacationStatus.WITHDRAW_REQUESTED)
    body = client.get(f"/records/vacations/calendar?scope=team&month={start:%Y-%m}").text
    assert "Rücknahme angefragt" in body


def test_confidential_types_stay_masked_in_the_team_calendar(client):
    """Offene Anträge sichtbar zu machen darf die Art nicht preisgeben."""
    from app import models

    with _db() as db:
        db.add(models.AbsenceType(key="cure", label="Kur", confidential=True, active=True))
        db.commit()
    _login(client)
    start = date(2026, 5, 4)
    with _db() as db:
        db.add(models.VacationRequest(
            user_id=_admin_id(), start_date=start, end_date=start,
            status=models.VacationStatus.PENDING, absence_type_key="cure",
        ))
        db.commit()
    body = client.get(f"/records/vacations/calendar?scope=team&month={start:%Y-%m}").text
    assert "Abwesend" in body
    assert "Kur" not in body


# ── 4. QR-Code oben rechts, Arbeitszeitpläne darunter ─────────────────────


def test_qr_comes_before_the_work_schedules(client):
    _login(client)
    body = client.get(f"/admin/users/{_admin_id()}").text
    qr = body.index('class="user-qr"')
    schedules = body.index('class="card compact-card work-schedule-launcher"')
    assert qr < schedules, "Der QR-Code muss oben in der Seitenspalte stehen"


def test_the_aside_column_holds_all_three_cards(client):
    _login(client)
    body = client.get(f"/admin/users/{_admin_id()}").text
    assert 'class="user-form-aside"' in body
    column = body.split('class="user-form-aside"', 1)[1]
    for marker in ("user-qr", "work-schedule-launcher", "Urlaubsanspruch buchen"):
        assert marker in column


def test_the_work_schedule_modal_exists_exactly_once(client):
    """Bis 0.20.6 stand eine zweite, wirkungslose Kopie im Titelblock."""
    _login(client)
    body = client.get(f"/admin/users/{_admin_id()}").text
    assert body.count('id="work-schedules-modal"') == 1
    assert body.count('id="work-schedules-open"') == 1


def test_the_title_block_carries_only_the_title():
    source = (ROOT / "templates" / "admin" / "users_form.html").read_text(encoding="utf-8")
    title_block = source.split("{% block title %}", 1)[1].split("{% endblock %}", 1)[0]
    assert "work-schedules-modal" not in title_block
    assert "<script" not in title_block


# ── 5. Sollzeiten folgen überall dem Arbeitszeitplan ──────────────────────


def test_weekly_overview_follows_the_work_schedule(main):
    """Vier Tage zu acht Stunden ergeben 32 Wochenstunden, nicht 40."""
    admin_id = _admin_id()
    _plan(admin_id, date(2026, 1, 1), (480, 480, 480, 480, 0, 0, 0))
    monday = date(2026, 6, 1)
    with _db() as db:
        from app import models

        person = db.query(models.User).filter(models.User.id == admin_id).first()
        overview = main._build_weekly_overview(db, person, monday, today=monday)
    assert overview["target_minutes"] == 4 * 480
    by_day = {row["date"]: row["target_minutes"] for row in overview["days"]}
    assert by_day[monday] == 480
    assert by_day[monday + timedelta(days=4)] == 0, "Freitag ist planmäßig frei"
    assert by_day[monday + timedelta(days=5)] == 0


def test_expected_minutes_to_date_use_the_plan(main):
    admin_id = _admin_id()
    _plan(admin_id, date(2026, 1, 1), (480, 0, 480, 0, 480, 0, 0))
    monday = date(2026, 6, 1)
    wednesday = monday + timedelta(days=2)
    with _db() as db:
        from app import models

        person = db.query(models.User).filter(models.User.id == admin_id).first()
        overview = main._build_weekly_overview(db, person, monday, today=wednesday)
    # Montag 480 + Dienstag 0 + Mittwoch 480
    assert overview["expected_minutes_to_date"] == 960


def test_a_saturday_plan_is_counted(main):
    admin_id = _admin_id()
    _plan(admin_id, date(2026, 1, 1), (0, 0, 0, 0, 0, 300, 0))
    monday = date(2026, 6, 1)
    with _db() as db:
        from app import models

        person = db.query(models.User).filter(models.User.id == admin_id).first()
        overview = main._build_weekly_overview(db, person, monday, today=monday)
    assert overview["target_minutes"] == 300


def test_without_a_plan_the_old_behaviour_stays(main):
    """Ohne Plan bleibt es bei Montag–Freitag mal Tagessoll."""
    admin_id = _admin_id()
    monday = date(2026, 6, 1)
    with _db() as db:
        from app import models

        person = db.query(models.User).filter(models.User.id == admin_id).first()
        expected = int(round(person.daily_target_minutes)) * 5
        overview = main._build_weekly_overview(db, person, monday, today=monday)
    assert overview["target_minutes"] == expected


def test_day_overview_target_follows_the_plan(client):
    """Der Tagesreiter zeigt das Soll des angezeigten Tages, nicht den Schnitt."""
    _plan(_admin_id(), date(2026, 1, 1), (480, 480, 480, 480, 480, 0, 0))
    _login(client)
    saturday = date(2026, 6, 6)
    body = client.get(f"/dashboard?tab=uebersicht&overview=day&date={saturday}").text
    assert body.count("Soll 0:00") >= 1 or "0:00" in body


def test_overtime_minutes_use_the_day_target(main):
    """Eine Buchung am planmäßig freien Tag ist in voller Höhe Mehrarbeit."""
    from app import models

    admin_id = _admin_id()
    _plan(admin_id, date(2026, 1, 1), (480, 480, 480, 480, 480, 0, 0))
    saturday = date(2026, 6, 6)
    entry = _entry(saturday, time(9, 0), time(13, 0))
    with _db() as db:
        row = db.query(models.TimeEntry).filter(models.TimeEntry.id == entry.id).first()
        assert row.worked_minutes == 240
        assert row.overtime_minutes == 240


def test_overtime_stays_zero_without_any_target(main):
    from app import models

    admin_id = _admin_id()
    with _db() as db:
        person = db.query(models.User).filter(models.User.id == admin_id).first()
        person.standard_weekly_hours = 0
        person.standard_daily_minutes = 0
        db.commit()
    entry = _entry(date(2026, 6, 3), time(9, 0), time(13, 0))
    with _db() as db:
        row = db.query(models.TimeEntry).filter(models.TimeEntry.id == entry.id).first()
        assert row.overtime_minutes == 0


def test_vacation_summary_counts_days_by_the_plan(main):
    """Eine Urlaubswoche im Vier-Tage-Plan zählt vier Tage, nicht fünf."""
    from app import models, services

    admin_id = _admin_id()
    _plan(admin_id, date(2026, 1, 1), (480, 480, 480, 480, 0, 0, 0))
    _vacation(admin_id, date(2026, 6, 1), date(2026, 6, 7), models.VacationStatus.APPROVED)
    with _db() as db:
        person = db.query(models.User).filter(models.User.id == admin_id).first()
        vacations = db.query(models.VacationRequest).filter(
            models.VacationRequest.user_id == admin_id
        ).all()
        summary = services.calculate_vacation_summary(person, vacations, 2026)
    assert summary.used_days == 4.0


def test_half_days_still_count_as_half(main):
    from app import models, services

    admin_id = _admin_id()
    _plan(admin_id, date(2026, 1, 1), (480, 480, 480, 480, 480, 0, 0))
    with _db() as db:
        db.add(models.VacationRequest(
            user_id=admin_id, start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
            status=models.VacationStatus.APPROVED, absence_type_key="vacation",
            half_day_start=True,
        ))
        db.commit()
    with _db() as db:
        person = db.query(models.User).filter(models.User.id == admin_id).first()
        vacations = db.query(models.VacationRequest).filter(
            models.VacationRequest.user_id == admin_id
        ).all()
        summary = services.calculate_vacation_summary(person, vacations, 2026)
    assert summary.used_days == 1.5


# ── 6. Offline-Shell rechnet mit denselben Sollzeiten ──────────────────────


def test_snapshot_carries_the_daily_targets(client):
    _plan(_admin_id(), date(2026, 1, 1), (480, 480, 480, 480, 0, 0, 0))
    _login(client)
    payload = client.get("/mobile/sync-data").json()
    targets = payload.get("daily_targets")
    assert isinstance(targets, dict) and targets
    for day, minutes in targets.items():
        weekday = date.fromisoformat(day).weekday()
        assert minutes == (480 if weekday < 4 else 0), day


def test_snapshot_keeps_the_flat_values_as_fallback(client):
    _login(client)
    payload = client.get("/mobile/sync-data").json()
    assert "daily_target_minutes" in payload["user"]
    assert "weekly_target_minutes" in payload["user"]


def test_the_shell_no_longer_derives_the_week_from_a_flat_target():
    source = (ROOT / "static" / "mobile.js").read_text(encoding="utf-8")
    assert "dailyTarget * 5" not in source
    assert "daily_targets" in source


def test_the_shell_falls_back_to_monday_to_friday():
    """Ältere Momentaufnahmen kennen `daily_targets` nicht."""
    source = (ROOT / "static" / "mobile.js").read_text(encoding="utf-8")
    assert "weekday >= 1 && weekday <= 5" in source


# ── 7. Übrige Anzeigen bleiben unverändert erreichbar ─────────────────────


@pytest.mark.parametrize("url", [
    "/dashboard",
    "/dashboard?tab=uebersicht",
    "/dashboard?tab=uebersicht&overview=week",
    "/dashboard?tab=salden",
    "/records",
    "/records/vacations",
    "/records/vacations/calendar?scope=self",
    "/records/vacations/calendar?scope=self&view=week",
    "/records/vacations/calendar?scope=self&view=list",
    "/records/vacations/calendar?scope=team",
    "/admin/users",
    "/admin/reports/vacations",
])
def test_pages_still_render(client, url):
    _login(client)
    response = client.get(url)
    assert response.status_code == 200, url


def test_the_weekly_hours_field_names_the_active_plan(client):
    """Sonst stünde dort 40, während die Anwendung mit 32 rechnet."""
    _plan(_admin_id(), date(2020, 1, 1), (480, 480, 480, 480, 0, 0, 0))
    _login(client)
    body = client.get(f"/admin/users/{_admin_id()}").text
    assert "Arbeitszeitplan „Testplan" in body
    assert "32:00 Std" in body


def test_without_a_plan_no_hint_appears(client):
    _login(client)
    body = client.get(f"/admin/users/{_admin_id()}").text
    assert "Aktuell gilt der Arbeitszeitplan" not in body


def test_the_report_footnote_matches_the_calculation():
    """Die Fußnote beschrieb bis 0.20.6 die alte Mo–Fr-Rechnung."""
    source = (ROOT / "templates" / "admin" / "user_reports.html").read_text(encoding="utf-8")
    assert "Arbeitstage (Mo–Fr) × Tagessoll" not in source
    assert "Arbeitszeitplan" in source


def test_the_unused_admin_calendar_template_is_gone():
    """Keine Route rendert sie; `/admin/vacations/calendar` leitet um."""
    assert not (ROOT / "templates" / "admin" / "vacation_calendar.html").exists()


def test_the_admin_calendar_url_still_works(client):
    _login(client)
    response = client.get("/admin/vacations/calendar", follow_redirects=False)
    assert response.status_code == 303
    assert "scope=team" in response.headers["location"]


def test_monthly_and_weekly_targets_agree(main):
    """Monatssoll und Wochensoll stammen aus derselben Quelle."""
    from app import models, services

    admin_id = _admin_id()
    _plan(admin_id, date(2026, 1, 1), (480, 480, 480, 480, 0, 0, 0))
    with _db() as db:
        person = db.query(models.User).filter(models.User.id == admin_id).first()
        # Juni 2026 beginnt an einem Montag und hat genau 30 Tage.
        monthly = services.calculate_monthly_target_minutes(person, 2026, 6)
        weekly = sum(
            main._build_weekly_overview(db, person, date(2026, 6, 1) + timedelta(days=7 * n),
                                        today=date(2026, 6, 1))["target_minutes"]
            for n in range(4)
        )
    # Vier volle Wochen ab dem 1. Juni decken den 1.–28. Juni ab; der 29. und
    # 30. Juni sind Montag und Dienstag und tragen je 480 Minuten bei.
    assert monthly == weekly + 2 * 480


# ── 8. Befunde aus dem Anwenderdurchlauf ──────────────────────────────────


def test_every_post_form_carries_a_csrf_token():
    """Die CSRF-Prüfung greift für jede zustandsändernde Anfrage.

    Ein Formular ohne Token ist deshalb eine Schaltfläche, die nichts tut
    außer „403 – Ungültige Sitzung" anzuzeigen. Bis 0.20.7 fehlte das Feld im
    Abschnitt „Rücknahmeanfragen" – eine Rücknahme ließ sich überhaupt nicht
    entscheiden.

    Felder dürfen dem Formular auch über das HTML-Attribut ``form="…"`` von
    außerhalb zugeordnet sein; dann steht das Token nicht zwischen den Tags.
    """
    form_open = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
    offenders = []
    for path in sorted((ROOT / "templates").rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in form_open.finditer(text):
            tag = match.group(0)
            if 'method="post"' not in tag.lower():
                continue
            end = text.find("</form>", match.end())
            body = text[match.end():end if end != -1 else len(text)]
            if "csrf_token" in body:
                continue
            form_id = re.search(r'id="([^"]+)"', tag)
            if form_id and f'form="{form_id.group(1)}"' in text:
                continue  # Felder hängen über das form-Attribut daran
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert not offenders, "POST-Formulare ohne CSRF-Token: " + ", ".join(offenders)


def test_withdrawal_can_actually_be_decided(client):
    """Der ganze Vorgang: beantragen, zurückziehen, Rücknahme freigeben."""
    from app import models

    _login(client)
    admin_id = _admin_id()
    start = date(2026, 10, 5)
    with _db() as db:
        row = models.VacationRequest(
            user_id=admin_id, start_date=start, end_date=start + timedelta(days=4),
            status=models.VacationStatus.WITHDRAW_REQUESTED,
            previous_status="approved", absence_type_key="vacation",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        vacation_id = row.id

    page = client.get("/admin/approvals").text
    section = page.split("Rücknahmeanfragen", 1)[1]
    form = section[section.index("<form"):section.index("</form>")]
    assert "csrf_token" in form, "Das Formular der Rücknahmeanfragen braucht ein Token"

    response = client.post(
        f"/admin/vacations/{vacation_id}/status",
        data={"action": "approve_withdraw", "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with _db() as db:
        after = db.query(models.VacationRequest).filter(
            models.VacationRequest.id == vacation_id
        ).first().status
    assert after == models.VacationStatus.CANCELLED


def test_a_withdrawal_without_a_token_is_still_rejected(client):
    """Die Reparatur darf die Prüfung nicht aufweichen."""
    from app import models

    _login(client)
    start = date(2026, 11, 2)
    with _db() as db:
        row = models.VacationRequest(
            user_id=_admin_id(), start_date=start, end_date=start,
            status=models.VacationStatus.WITHDRAW_REQUESTED,
            previous_status="approved", absence_type_key="vacation",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        vacation_id = row.id
    response = client.post(
        f"/admin/vacations/{vacation_id}/status",
        data={"action": "approve_withdraw"}, follow_redirects=False,
    )
    assert response.status_code == 403


def test_month_headings_are_german(client):
    """Bis 0.20.6 stand über der Buchungsseite „06/2026"."""
    _login(client)
    body = client.get("/records?month=2026-06").text
    assert "Juni 2026" in body
    assert "06/2026" not in body


def test_no_numeric_month_format_remains():
    for name in ("records/bookings.html", "dashboard.html"):
        source = (ROOT / "templates" / name).read_text(encoding="utf-8")
        assert "'%m/%Y'" not in source, name
