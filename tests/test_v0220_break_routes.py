"""HTTP-Schutz und Rückmeldung beim Korrigieren gestempelter Pausen."""
from datetime import date, datetime, time, timedelta
import json
import re

import pytest

from test_v0209 import client, main, _login


DAY = date(2026, 6, 10)


def _records():
    from app import database, models

    with database.SessionLocal() as db:
        db.get(models.User, 1).auto_break_deduction = False
        other = models.User(username="other", full_name="Anderes Team", email="other@example.invalid", pin_code="7728", must_change_password=False, auto_break_deduction=False)
        db.add(other)
        db.flush()
        entries = [models.TimeEntry(user_id=owner, work_date=DAY + timedelta(days=offset), start_time=time(8), end_time=time(17), break_minutes=30, is_open=False, status=models.TimeEntryStatus.APPROVED, tz_name="Europe/Berlin") for owner, offset in ((1, 0), (1, 1), (other.id, 0))]
        db.add_all(entries)
        db.flush()
        intervals = [models.BreakInterval(entry_id=e.id, started_at_utc=datetime.combine(e.work_date, time(10, 0, 15)), ended_at_utc=datetime.combine(e.work_date, time(10, 30, 15)), tz_name="Europe/Berlin") for e in entries]
        db.add_all(intervals)
        db.commit()
        return [(e.id, p.id) for e, p in zip(entries, intervals)]


def _state():
    from app import database, models

    with database.SessionLocal() as db:
        return (
            [(p.id, p.started_at_utc, p.ended_at_utc) for p in db.query(models.BreakInterval).order_by(models.BreakInterval.id)],
            [(e.id, e.break_minutes, e.status) for e in db.query(models.TimeEntry).order_by(models.TimeEntry.id)],
            db.query(models.TimeEntryRevision).count(),
        )


def _post(client, entry_id, pause_id, **changes):
    payload = {"started_at": "2026-06-10T12:10:00", "ended_at": "2026-06-10T12:50:00", "change_reason": "Pause nach Rücksprache korrigiert", "next_url": "/admin/reports/time", "csrf_token": client.get("/api/csrf").json()["csrf_token"], **changes}
    return client.post(f"/admin/time-entries/{entry_id}/breaks/{pause_id}", data=payload, follow_redirects=False)


def test_break_form_is_separate_and_uses_recorded_times_and_readonly_sum(client):
    _login(client)
    (entry_id, pause_id), *_ = _records()
    response = client.get(f"/admin/time-entries/{entry_id}/edit")
    assert response.status_code == 200
    pause_field = re.search(r'<input[^>]+name="break_minutes"[^>]*>', response.text).group()
    assert "readonly" in pause_field and 'value="30"' in pause_field
    assert f'action="/admin/time-entries/{entry_id}/breaks/{pause_id}"' in response.text
    row = response.context["break_edit_rows"][0]
    assert row["started_local"] == "2026-06-10T12:00:15"
    assert row["ended_local"] == "2026-06-10T12:30:15"
    assert row["can_edit"] is True
    assert 'step="1"' in response.text


def test_corrected_break_changes_worked_time_with_actor_and_reason(client):
    _login(client)
    (entry_id, pause_id), *_ = _records()
    result = _post(client, entry_id, pause_id)
    assert result.status_code == 303
    assert result.headers["location"].endswith("#break-intervals")
    page = client.get(result.headers["location"])
    assert "Pausenkorrektur gespeichert" in page.text
    from app import database, models

    with database.SessionLocal() as db:
        entry = db.get(models.TimeEntry, entry_id)
        pause = db.get(models.BreakInterval, pause_id)
        assert pause.started_at_utc == datetime(2026, 6, 10, 10, 10)
        assert pause.ended_at_utc == datetime(2026, 6, 10, 10, 50)
        assert entry.break_minutes == 40
        assert entry.worked_minutes == 500
        assert entry.status == models.TimeEntryStatus.APPROVED
        revision = db.query(models.TimeEntryRevision).filter_by(entry_id=entry_id).one()
        assert revision.actor_id == 1
        assert revision.action == models.RevisionAction.BREAK_CORRECTED
        assert revision.reason == "Pause nach Rücksprache korrigiert"
        assert json.loads(revision.before_json)["breaks"][0]["minutes"] == 30
        assert json.loads(revision.after_json)["breaks"][0]["minutes"] == 40


def test_break_correction_rejects_csrf_and_foreign_interval(client):
    _login(client)
    (entry_id, pause_id), (_, other_pause), *_ = _records()
    before = _state()
    assert _post(client, entry_id, pause_id, csrf_token="wrong").status_code == 403
    assert _post(client, entry_id, other_pause).status_code == 404
    assert _state() == before


@pytest.mark.parametrize("change,expected", [
    ({"started_at": "2026-02-30T12:00"}, 422),
    ({"ended_at": "2026-06-10T11:30"}, 303),
    ({"ended_at": "2026-06-11T12:30"}, 303),
    ({"change_reason": "   "}, 303),
])
def test_invalid_break_input_leaves_interval_and_history_unchanged(client, change, expected):
    _login(client)
    (entry_id, pause_id), *_ = _records()
    before = _state()
    response = _post(client, entry_id, pause_id, **change)
    assert response.status_code == expected
    if expected == 303:
        page = client.get(response.headers["location"])
        assert page.context["error"]
    assert _state() == before


def test_break_correction_respects_time_edit_scope(client):
    _login(client)
    *_, (entry_id, pause_id) = _records()
    from app import crud, database, models

    with database.SessionLocal() as db:
        user = db.get(models.User, 1)
        role = crud.create_role(db, name="Nur eigene Gruppen korrigieren", permissions={"Time.Edit": "groups"})
        user.roles = [role]
        db.commit()
    before = _state()
    assert _post(client, entry_id, pause_id).status_code == 403
    assert _state() == before


@pytest.mark.parametrize("blocked", ["locked", "running", "overlap"])
def test_locked_running_or_overlapping_break_cannot_be_changed(client, blocked):
    _login(client)
    (entry_id, pause_id), *_ = _records()
    from app import database, models

    with database.SessionLocal() as db:
        if blocked == "locked":
            db.add(models.PayrollPeriod(period_start=DAY, period_end=DAY, status=models.PeriodStatus.LOCKED))
        elif blocked == "running":
            db.get(models.BreakInterval, pause_id).ended_at_utc = None
        else:
            db.add(models.BreakInterval(entry_id=entry_id, started_at_utc=datetime(2026, 6, 10, 10, 40), ended_at_utc=datetime(2026, 6, 10, 11), tz_name="Europe/Berlin"))
        db.commit()
    before = _state()
    page = client.get(f"/admin/time-entries/{entry_id}/edit")
    if blocked != "overlap":
        assert page.context["break_edit_rows"][0]["can_edit"] is False
    result = _post(client, entry_id, pause_id)
    assert result.status_code == 303
    assert client.get(result.headers["location"]).context["error"]
    assert _state() == before


@pytest.mark.parametrize("end_time,confirmed", [("01:00", False), ("23:00", False), ("23:00", True), ("23:30", True)])
def test_manual_overnight_entry_requires_explicit_confirmation_and_nonzero_duration(client, end_time, confirmed):
    _login(client)
    before = _state()
    response = client.post("/time", data={
        "work_date": DAY.isoformat(), "start_time": "23:00", "end_time": end_time,
        "ends_next_day": "1" if confirmed else "0", "next_url": "/dashboard",
        "csrf_token": client.get("/api/csrf").json()["csrf_token"],
    }, follow_redirects=False)
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert _state() == before


def test_confirmed_manual_overnight_entry_keeps_following_day_and_actor(client):
    _login(client)
    response = client.post("/time", data={
        "work_date": DAY.isoformat(), "start_time": "23:00", "end_time": "01:00",
        "ends_next_day": "1", "next_url": "/dashboard",
        "csrf_token": client.get("/api/csrf").json()["csrf_token"],
    }, follow_redirects=False)
    assert response.status_code == 303
    assert "msg=" in response.headers["location"]
    from app import database, models

    with database.SessionLocal() as db:
        entry = db.query(models.TimeEntry).one()
        assert entry.work_date == DAY
        assert entry.start_time == time(23) and entry.end_time == time(1)
        assert entry.started_at_utc == datetime(2026, 6, 10, 21)
        assert entry.ended_at_utc == datetime(2026, 6, 10, 23)
        assert entry.worked_minutes == 120
        assert entry.status == models.TimeEntryStatus.PENDING
        assert db.query(models.TimeEntryRevision).one().actor_id == 1


@pytest.mark.parametrize("locked_day", [DAY, DAY + timedelta(days=1)])
def test_manual_overnight_checks_both_periods_before_creating_company(client, locked_day):
    _login(client)
    from app import database, models

    with database.SessionLocal() as db:
        db.add(models.PayrollPeriod(period_start=locked_day, period_end=locked_day, status=models.PeriodStatus.LOCKED))
        db.commit()
        companies_before = db.query(models.Company).count()
    before = _state()
    response = client.post("/time", data={
        "work_date": DAY.isoformat(), "start_time": "23:00", "end_time": "01:00",
        "ends_next_day": "1", "new_company_name": "Nicht bei gesperrter Periode anlegen",
        "next_url": "/dashboard", "csrf_token": client.get("/api/csrf").json()["csrf_token"],
    }, follow_redirects=False)
    assert response.status_code == 303 and "error=" in response.headers["location"]
    assert _state() == before
    with database.SessionLocal() as db:
        assert db.query(models.Company).count() == companies_before
