"""Tests für 0.20.8 – Tätigkeitsbeschreibungen nachtragen.

Bis 0.20.7 ließ sich ein Kommentar nur an der **zuletzt beendeten Buchung des
laufenden Tages** ändern (Dashboard und App). Wer die Tätigkeit später
beschreiben wollte – am Monatsende für den Nachweis, oder weil die Buchung
vom Terminal kam –, brauchte dafür die Administration.

Seit 0.20.8 steht das Feld unter **Buchungen** an jeder eigenen Buchung und
unter **Urlaub** an jedem eigenen Antrag. Geändert wird ausschließlich der
Kommentar: Zeiten, Firma, Zeitraum, Art und Status bleiben unberührt.

Die Grenzen bleiben, wo sie waren:

* nur eigene Vorgänge,
* nur mit dem Recht ``Own.Comment.Edit``,
* nicht in einer abgerechneten (gesperrten) Periode,
* und jede Änderung wird festgehalten – bei Buchungen in der Revisionshistorie,
  bei Anträgen im Auditlog.
"""

from __future__ import annotations

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
    match = _CSRF_RE.search(client.get(url, follow_redirects=True).text)
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


DAY = date(2026, 6, 1)


def _entry(day: date = DAY, *, user_id: int | None = None, notes: str = ""):
    from app import models

    started = datetime.combine(day, time(8, 0)).replace(tzinfo=BERLIN)
    ended = datetime.combine(day, time(16, 30)).replace(tzinfo=BERLIN)
    with _db() as db:
        row = models.TimeEntry(
            user_id=user_id or _admin_id(), work_date=day,
            start_time=time(8, 0), end_time=time(16, 30), notes=notes,
            status=models.TimeEntryStatus.APPROVED, break_minutes=30,
            break_rule=models.BreakRule.ACTUAL, tz_name="Europe/Berlin",
            started_at_utc=started.astimezone(timezone.utc).replace(tzinfo=None),
            ended_at_utc=ended.astimezone(timezone.utc).replace(tzinfo=None),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def _vacation(*, user_id: int | None = None, comment: str = "",
              status: str | None = None) -> int:
    from app import models

    with _db() as db:
        row = models.VacationRequest(
            user_id=user_id or _admin_id(),
            start_date=date(2026, 10, 5), end_date=date(2026, 10, 9),
            status=status or models.VacationStatus.PENDING,
            comment=comment, absence_type_key="vacation",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def _entry_notes(entry_id: int) -> str:
    from app import models

    with _db() as db:
        return db.query(models.TimeEntry).filter(
            models.TimeEntry.id == entry_id
        ).first().notes or ""


def _vacation_comment(vacation_id: int) -> str:
    from app import models

    with _db() as db:
        return db.query(models.VacationRequest).filter(
            models.VacationRequest.id == vacation_id
        ).first().comment or ""


def _second_person() -> int:
    """Ein zweites Konto – für die Frage „fremde Vorgänge"."""
    from app import models

    with _db() as db:
        person = models.User(
            username="kolleg", full_name="Kolleg Person",
            email="kolleg@example.org", pin_code="4321", password_hash="x",
        )
        db.add(person)
        db.commit()
        db.refresh(person)
        return person.id


# ── Version ───────────────────────────────────────────────────────────────


def test_version_is_0208(client):
    assert client.app.version == "0.20.8"
    assert client.get("/health").json()["version"] == "0.20.8"


# ── 1. Buchungen: das Feld ist da ─────────────────────────────────────────


def test_the_bookings_page_offers_the_field(client):
    _login(client)
    entry_id = _entry()
    body = client.get(f"/records?month={DAY:%Y-%m}").text
    assert f'action="/records/entries/{entry_id}/note"' in body
    assert 'name="notes"' in body


def test_the_field_carries_the_current_text(client):
    _login(client)
    entry_id = _entry(notes="Wartung Halle 2")
    body = client.get(f"/records?month={DAY:%Y-%m}").text
    block = body.split(f'action="/records/entries/{entry_id}/note"', 1)[1]
    assert "Wartung Halle 2" in block


def test_the_form_has_a_csrf_token(client):
    """Ohne Token endete jeder Klick auf „403 – Ungültige Sitzung"."""
    _login(client)
    entry_id = _entry()
    body = client.get(f"/records?month={DAY:%Y-%m}").text
    block = body.split(f'id="note-{entry_id}"', 1)[1].split("</td>", 1)[0]
    assert "csrf_token" in block


# ── 2. Buchungen: nachtragen wirkt ────────────────────────────────────────


def test_a_comment_can_be_added_afterwards(client):
    _login(client)
    entry_id = _entry()
    response = client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "Aufmaß beim Kunden", "month": f"{DAY:%Y-%m}",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert _entry_notes(entry_id) == "Aufmaß beim Kunden"


def test_an_existing_comment_can_be_replaced(client):
    _login(client)
    entry_id = _entry(notes="Alt")
    client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "Neu", "month": f"{DAY:%Y-%m}",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    assert _entry_notes(entry_id) == "Neu"


def test_a_comment_can_be_cleared(client):
    _login(client)
    entry_id = _entry(notes="Versehentlich")
    client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "", "month": f"{DAY:%Y-%m}",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    assert _entry_notes(entry_id) == ""


def test_the_selected_month_survives(client):
    """Sonst landet man nach dem Speichern im laufenden Monat."""
    _login(client)
    entry_id = _entry()
    response = client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "Text", "month": "2026-06",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    assert "month=2026-06" in response.headers["location"]


def test_times_and_company_stay_untouched(client):
    """Nur der Kommentar – die Buchung selbst ist tabu."""
    from app import models

    _login(client)
    entry_id = _entry()
    with _db() as db:
        before = db.query(models.TimeEntry).filter(models.TimeEntry.id == entry_id).first()
        snapshot = (before.start_time, before.end_time, before.work_date,
                    before.break_minutes, before.status, before.worked_minutes)
    client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "Nur Text", "month": f"{DAY:%Y-%m}",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    with _db() as db:
        after = db.query(models.TimeEntry).filter(models.TimeEntry.id == entry_id).first()
        assert (after.start_time, after.end_time, after.work_date,
                after.break_minutes, after.status, after.worked_minutes) == snapshot


def test_the_change_is_historised(client):
    """Auch ein Nachtrag ist eine Änderung."""
    from app import models

    _login(client)
    entry_id = _entry(notes="Vorher")
    client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "Nachher", "month": f"{DAY:%Y-%m}",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    with _db() as db:
        revisions = db.query(models.TimeEntryRevision).filter(
            models.TimeEntryRevision.entry_id == entry_id
        ).all()
    assert revisions, "keine Revision zum Nachtrag"
    assert any("Vorher" in (row.before_json or "") for row in revisions)


def test_the_history_page_shows_the_change(client):
    _login(client)
    entry_id = _entry(notes="Vorher")
    client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "Nachher", "month": f"{DAY:%Y-%m}",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    body = client.get(f"/admin/time-entries/{entry_id}/history").text
    assert "Nachher" in body


# ── 3. Buchungen: die Grenzen ─────────────────────────────────────────────


def test_a_foreign_booking_is_refused(client):
    _login(client)
    other_id = _second_person()
    entry_id = _entry(user_id=other_id, notes="Fremd")
    response = client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "Übernommen", "month": f"{DAY:%Y-%m}",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "error" in response.headers["location"]
    assert _entry_notes(entry_id) == "Fremd"


def test_a_locked_period_refuses_the_change(client):
    from app import models

    _login(client)
    entry_id = _entry(notes="Abgerechnet")
    with _db() as db:
        db.add(models.PayrollPeriod(
            period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
            status=models.PeriodStatus.LOCKED,
        ))
        db.commit()
    response = client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "Doch noch", "month": f"{DAY:%Y-%m}",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    assert "error" in response.headers["location"]
    assert _entry_notes(entry_id) == "Abgerechnet"


def test_a_locked_period_hides_the_field(client):
    """Kein Feld anbieten, das beim Absenden abgewiesen würde."""
    from app import models

    _login(client)
    entry_id = _entry()
    with _db() as db:
        db.add(models.PayrollPeriod(
            period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
            status=models.PeriodStatus.LOCKED,
        ))
        db.commit()
    body = client.get(f"/records?month={DAY:%Y-%m}").text
    assert f'action="/records/entries/{entry_id}/note"' not in body
    assert "Zeitraum abgerechnet" in body


def test_without_the_right_there_is_no_field(client, main):
    from app import models

    _login(client)
    _entry()
    with _db() as db:
        permission = db.query(models.RolePermission).filter(
            models.RolePermission.permission_key == "Own.Comment.Edit"
        ).all()
        for row in permission:
            db.delete(row)
        db.commit()
    body = client.get(f"/records?month={DAY:%Y-%m}").text
    assert 'name="notes"' not in body


def test_the_comment_is_capped_at_the_column_width(client):
    _login(client)
    entry_id = _entry()
    client.post(
        f"/records/entries/{entry_id}/note",
        data={"notes": "x" * 400, "month": f"{DAY:%Y-%m}",
              "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    assert len(_entry_notes(entry_id)) == 255


# ── 4. Urlaub: Kommentar am eigenen Antrag ────────────────────────────────


def test_the_vacation_page_offers_the_field(client):
    _login(client)
    vacation_id = _vacation()
    body = client.get("/records/vacations").text
    assert f'action="/vacations/{vacation_id}/comment"' in body


def test_a_vacation_comment_can_be_added(client):
    _login(client)
    vacation_id = _vacation()
    response = client.post(
        f"/vacations/{vacation_id}/comment",
        data={"comment": "Familienfeier", "csrf_token": _csrf(client, "/records/vacations")},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert _vacation_comment(vacation_id) == "Familienfeier"


def test_an_approved_request_can_still_be_described(client):
    """Der Kommentar beschreibt, er entscheidet nicht."""
    from app import models

    _login(client)
    vacation_id = _vacation(status=models.VacationStatus.APPROVED)
    client.post(
        f"/vacations/{vacation_id}/comment",
        data={"comment": "Nachtrag", "csrf_token": _csrf(client, "/records/vacations")},
        follow_redirects=False,
    )
    assert _vacation_comment(vacation_id) == "Nachtrag"


def test_period_type_and_status_stay_untouched(client):
    from app import models

    _login(client)
    vacation_id = _vacation(status=models.VacationStatus.APPROVED)
    with _db() as db:
        before = db.query(models.VacationRequest).filter(
            models.VacationRequest.id == vacation_id).first()
        snapshot = (before.start_date, before.end_date, before.status,
                    before.absence_type_key, before.half_day_start)
    client.post(
        f"/vacations/{vacation_id}/comment",
        data={"comment": "Nur Text", "csrf_token": _csrf(client, "/records/vacations")},
        follow_redirects=False,
    )
    with _db() as db:
        after = db.query(models.VacationRequest).filter(
            models.VacationRequest.id == vacation_id).first()
        assert (after.start_date, after.end_date, after.status,
                after.absence_type_key, after.half_day_start) == snapshot


def test_a_foreign_request_is_refused(client):
    _login(client)
    other_id = _second_person()
    vacation_id = _vacation(user_id=other_id, comment="Fremd")
    response = client.post(
        f"/vacations/{vacation_id}/comment",
        data={"comment": "Übernommen", "csrf_token": _csrf(client, "/records/vacations")},
        follow_redirects=False,
    )
    assert "error" in response.headers["location"]
    assert _vacation_comment(vacation_id) == "Fremd"


def test_the_vacation_change_is_audited(client, tmp_path):
    """Ein Antrag ist ein Nachweis – eine stille Änderung wäre keiner."""
    _login(client)
    vacation_id = _vacation(comment="Vorher")
    client.post(
        f"/vacations/{vacation_id}/comment",
        data={"comment": "Nachher", "csrf_token": _csrf(client, "/records/vacations")},
        follow_redirects=False,
    )
    audit = tmp_path / "logs" / "audit.log"
    assert audit.exists(), "kein Auditlog geschrieben"
    text = audit.read_text(encoding="utf-8")
    assert "Kommentar am Abwesenheitsantrag geändert" in text
    assert "Vorher" in text and "Nachher" in text


def test_the_vacation_comment_is_capped(client):
    _login(client)
    vacation_id = _vacation()
    client.post(
        f"/vacations/{vacation_id}/comment",
        data={"comment": "y" * 400, "csrf_token": _csrf(client, "/records/vacations")},
        follow_redirects=False,
    )
    assert len(_vacation_comment(vacation_id)) == 255


# ── 5. Was unverändert bleibt ─────────────────────────────────────────────


def test_the_dashboard_shortcut_still_works(client):
    """Der bisherige Weg über /punch bleibt bestehen."""
    _login(client)
    entry_id = _entry(day=date.today())
    response = client.post(
        "/punch",
        data={"action": "update_notes", "entry_id": str(entry_id),
              "notes": "Über das Dashboard", "csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert _entry_notes(entry_id) == "Über das Dashboard"


def test_every_new_form_carries_a_csrf_token():
    """Dieselbe Prüfung wie in 0.20.7 – jetzt auch für die neuen Formulare."""
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
                continue
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert not offenders, "POST-Formulare ohne CSRF-Token: " + ", ".join(offenders)


@pytest.mark.parametrize("url", ["/records", "/records/vacations", "/dashboard"])
def test_pages_still_render(client, url):
    _login(client)
    _entry()
    _vacation()
    assert client.get(url).status_code == 200


# ── 6. Nullminuten-Buchung belegt keine 24 Stunden ────────────────────────
#
# Beim vollen Testlauf zu dieser Version fiel
# ``test_v0121.py::test_a_running_order_can_still_be_ended`` sporadisch aus:
# „Zeitraum überschneidet sich mit einer vorhandenen Buchung." Dahinter stand
# kein Zufall, sondern ein Rechenfehler in ``crud._entry_bounds``.


def test_equal_start_and_end_spans_no_time():
    """Gleiche Start- und Endzeit heißt null Minuten, nicht 24 Stunden."""
    from app import crud

    start, end = crud._entry_bounds(date(2026, 6, 1), time(15, 42), time(15, 42), False)
    assert end == start
    assert (end - start).total_seconds() == 0


def test_an_end_before_the_start_is_still_the_next_day():
    """Nachtschicht: 22:00–06:00 endet am Folgetag – das muss bleiben."""
    from app import crud

    start, end = crud._entry_bounds(date(2026, 6, 1), time(22, 0), time(6, 0), False)
    assert end.date() == date(2026, 6, 2)
    assert (end - start).total_seconds() == 8 * 3600


def test_a_zero_minute_booking_blocks_nothing(client):
    """Sonst wäre nach einem Fehlklick der ganze Tag gesperrt."""
    from app import crud, models

    _login(client)
    day = date(2026, 6, 1)
    with _db() as db:
        db.add(models.TimeEntry(
            user_id=_admin_id(), work_date=day,
            start_time=time(15, 42), end_time=time(15, 42),
            status=models.TimeEntryStatus.APPROVED, break_minutes=0,
            break_rule=models.BreakRule.ACTUAL, tz_name="Europe/Berlin",
            started_at_utc=datetime(2026, 6, 1, 13, 42),
            ended_at_utc=datetime(2026, 6, 1, 13, 42),
        ))
        db.commit()

    for label, work_date, start, end in (
        ("später am selben Tag", day, time(17, 0), time(18, 0)),
        ("früher am selben Tag", day, time(8, 0), time(9, 0)),
        ("am Folgetag", day + timedelta(days=1), time(8, 0), time(9, 0)),
    ):
        payload = {"user_id": _admin_id(), "work_date": work_date,
                   "start_time": start, "end_time": end, "is_open": False}
        with _db() as db:
            assert crud._overlapping_entries(db, payload) == [], label


def test_a_real_overlap_is_still_detected(client):
    """Die Korrektur darf die Prüfung nicht aufweichen."""
    from app import crud, models

    _login(client)
    day = date(2026, 6, 1)
    with _db() as db:
        db.add(models.TimeEntry(
            user_id=_admin_id(), work_date=day,
            start_time=time(8, 0), end_time=time(16, 0),
            status=models.TimeEntryStatus.APPROVED, break_minutes=0,
            break_rule=models.BreakRule.ACTUAL, tz_name="Europe/Berlin",
            started_at_utc=datetime(2026, 6, 1, 6, 0),
            ended_at_utc=datetime(2026, 6, 1, 14, 0),
        ))
        db.commit()
    payload = {"user_id": _admin_id(), "work_date": day,
               "start_time": time(12, 0), "end_time": time(13, 0), "is_open": False}
    with _db() as db:
        assert crud._overlapping_entries(db, payload), "echte Überschneidung übersehen"


def test_touching_bookings_do_not_overlap(client):
    """Ende 16:00 und Beginn 16:00 grenzen an, sie überschneiden sich nicht."""
    from app import crud, models

    _login(client)
    day = date(2026, 6, 1)
    with _db() as db:
        db.add(models.TimeEntry(
            user_id=_admin_id(), work_date=day,
            start_time=time(8, 0), end_time=time(16, 0),
            status=models.TimeEntryStatus.APPROVED, break_minutes=0,
            break_rule=models.BreakRule.ACTUAL, tz_name="Europe/Berlin",
            started_at_utc=datetime(2026, 6, 1, 6, 0),
            ended_at_utc=datetime(2026, 6, 1, 14, 0),
        ))
        db.commit()
    payload = {"user_id": _admin_id(), "work_date": day,
               "start_time": time(16, 0), "end_time": time(17, 0), "is_open": False}
    with _db() as db:
        assert crud._overlapping_entries(db, payload) == []


def test_ending_an_order_within_the_same_minute_keeps_time_running(client):
    """Der Vorgang, der den Fehler zutage gefördert hat.

    „Auftrag beenden" schließt die Auftragsbuchung und startet unmittelbar die
    normale Arbeitszeit. Fallen Start und Ende in dieselbe Minute, belegte die
    gerade geschlossene Buchung 24 Stunden – und die Arbeitszeit lief nicht
    weiter.
    """
    from app import crud, models

    _login(client)
    with _db() as db:
        company = models.Company(name="Muster GmbH")
        db.add(company)
        db.commit()
        company_id = company.id

    token = _csrf(client, "/dashboard")
    client.post("/punch", data={"action": "start_company", "company_id": str(company_id),
                                "csrf_token": token}, follow_redirects=False)
    response = client.post("/punch", data={"action": "end_company", "csrf_token": token},
                           follow_redirects=False)
    assert response.status_code in (302, 303)
    assert "error=" not in response.headers["location"], response.headers["location"]
    with _db() as db:
        assert crud.get_open_time_entry(db, _admin_id()) is not None, \
            "die Arbeitszeit muss weiterlaufen"
