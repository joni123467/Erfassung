"""Real bookkeeping regressions for the new interface, not prototype arithmetic.

The shared fixture boots a fresh database without activation.
Assertions cover persisted minutes, attribution and immutable before/after
history; UI text and implementation details are deliberately not the oracle.
"""
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from test_v0209 import main, client, _admin_id, _csrf, _login

DAY = date(2026, 2, 10)
BERLIN = ZoneInfo("Europe/Berlin")


def payload(start=time(8), end=time(16), **changes):
    from app import schemas

    values = dict(user_id=_admin_id(), work_date=DAY, start_time=start,
                  end_time=end, break_minutes=0, status="approved", is_manual=False)
    values.update(changes)
    return schemas.TimeEntryCreate(**values)


def create(db, start=time(8), end=time(16), **changes):
    from app import crud

    return crud.create_time_entry(db, payload(start, end, **changes))


def pause(db, entry, start=time(12), end=time(12, 30)):
    from app import models

    row = models.BreakInterval(
        entry_id=entry.id,
        started_at_utc=datetime.combine(entry.work_date, start).replace(tzinfo=BERLIN)
        .astimezone(timezone.utc).replace(tzinfo=None),
        ended_at_utc=datetime.combine(entry.work_date, end).replace(tzinfo=BERLIN)
        .astimezone(timezone.utc).replace(tzinfo=None),
        tz_name="Europe/Berlin", source="web",
    )
    db.add(row)
    db.commit()
    db.refresh(entry)
    return row


def active_rows(db):
    from app import models

    return db.query(models.TimeEntry).filter(
        models.TimeEntry.status.in_(["approved", "pending"])
    ).order_by(models.TimeEntry.work_date, models.TimeEntry.start_time).all()


def freeze(monkeypatch, moment):
    from app import crud, worktime

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return moment.astimezone(timezone.utc).replace(tzinfo=None)

    monkeypatch.setattr(crud, "datetime", Frozen)
    monkeypatch.setattr(worktime, "datetime", Frozen)


@pytest.mark.parametrize("day,start,end,expected", [
    (date(2026, 2, 10), time(8), time(16), 480),
    (date(2026, 2, 10), time(22), time(6), 480),
    (date(2026, 3, 28), time(22), time(6), 420),
    (date(2026, 10, 24), time(22), time(6), 540),
    (date(2026, 3, 29), time(1), time(4), 120),
    (date(2026, 10, 25), time(1), time(4), 240),
])
def test_legacy_duration_uses_local_next_date_before_utc_conversion(main, day, start, end, expected):
    from app import worktime

    legacy = SimpleNamespace(work_date=day, start_time=start, end_time=end,
                             is_open=False, tz_name="Europe/Berlin")
    assert worktime.gross_minutes(legacy) == expected


def test_repeated_hour_explicit_stamps_remain_authoritative(main):
    from app import database, worktime

    with database.SessionLocal() as db:
        entry = create(db, time(2, 30), time(2, 30), work_date=date(2026, 10, 25),
                       tz_name="Europe/Berlin", started_at_utc=datetime(2026, 10, 25, 0, 30),
                       ended_at_utc=datetime(2026, 10, 25, 1, 30))
        assert entry.gross_minutes == 60
        assert worktime.entry_bounds(entry)[1] - worktime.entry_bounds(entry)[0] == timedelta(hours=1)


def test_utc_input_is_not_reinterpreted_as_local(main):
    from app import crud

    assert crud._to_utc(datetime(2026, 6, 10, 6, tzinfo=timezone.utc)) == datetime(2026, 6, 10, 6)


@pytest.mark.parametrize("duration,recorded,required,legacy_required", [
    (360, 0, 0, 0), (361, 0, 30, 30), (480, 30, 30, 30),
    (540, 30, 30, 30), (541, 15, 30, 45),
    (390, 30, 0, 30), (570, 30, 30, 45), (571, 30, 45, 45),
])
@pytest.mark.parametrize("legacy", [False, True])
def test_actual_pause_is_distinct_from_legacy_automatic_deduction(main, duration, recorded, required, legacy_required, legacy):
    from app import database, models

    with database.SessionLocal() as db:
        end = (datetime.combine(DAY, time(8)) + timedelta(minutes=duration)).time()
        entry = create(db, end=end, break_minutes=recorded)
        entry.break_rule = models.BreakRule.LEGACY_AUTO if legacy else models.BreakRule.ACTUAL
        db.commit()
        expected = legacy_required if legacy else required
        assert entry.required_break_minutes == expected
        assert entry.total_break_minutes == recorded
        assert entry.worked_minutes == duration - (max(expected, recorded) if legacy else recorded)


def test_short_breaks_reduce_work_but_do_not_satisfy_statutory_minimum(main):
    from app import database

    with database.SessionLocal() as db:
        entry = create(db)
        pause(db, entry, time(10), time(10, 10))
        pause(db, entry, time(12), time(12, 10))
        assert entry.total_break_minutes == 20
        assert entry.worked_minutes == 460
        assert entry.countable_break_minutes == 0
        assert entry.break_shortfall_minutes == 30


def test_end_work_closes_running_pause_and_records_both_events(main):
    from app import crud, database, revisions

    with database.SessionLocal() as db:
        entry = crud.start_running_entry(db, user_id=_admin_id(), started_at=datetime.combine(DAY, time(8)))
        crud.start_break(db, entry, datetime.combine(DAY, time(15, 30)))
        crud.finish_running_entry(db, entry, datetime.combine(DAY, time(16)))
        assert not entry.is_open and entry.running_break is None
        assert entry.total_break_minutes == 30 and entry.worked_minutes == 450
        assert [r.action for r in revisions.history(db, entry.id)][-2:] == ["break_ended", "closed"]


def test_real_punch_actions_keep_order_end_separate_from_work_end(client):
    from app import crud, database, models, schemas

    _login(client)
    with database.SessionLocal() as db:
        company = crud.create_company(db, schemas.CompanyCreate(name="Regression GmbH"))
        company_id = company.id
    token = _csrf(client, "/dashboard")
    for action, at, extra in [
        ("start_work", "08:00", {}),
        ("start_company", "09:00", {"company_id": str(company_id)}),
        ("start_break", "12:00", {}), ("end_break", "12:30", {}),
        ("end_company", "15:00", {}), ("end_work", "16:00", {}),
    ]:
        response = client.post("/punch", headers={"Accept": "application/json"},
                               data={"csrf_token": token, "action": action,
                                     "event_time": f"{DAY}T{at}:00+01:00", **extra})
        assert response.status_code == 200 and response.json()["ok"], response.text
        if action == "end_company":
            with database.SessionLocal() as db:
                running = crud.get_open_time_entry(db, _admin_id())
                assert running and running.company_id is None
    with database.SessionLocal() as db:
        entries = active_rows(db)
        assert [(e.start_time, e.end_time, e.company_id) for e in entries] == [
            (time(8), time(9), None), (time(9), time(15), company_id), (time(15), time(16), None)]
        assert sum(e.worked_minutes for e in entries) == 450
        assert db.query(models.BreakInterval).one().minutes == 30
        assert crud.get_open_time_entry(db, _admin_id()) is None


@pytest.mark.parametrize("start,end", [(time(8), time(9)), (time(10), time(11)),
                                        (time(15), time(16)), (time(8), time(16))])
def test_manual_insert_boundaries_count_each_minute_once_and_await_approval(main, start, end):
    from app import crud, database, revisions, services

    with database.SessionLocal() as db:
        original = create(db)
        manual, split = crud.create_manual_time_entry(db, payload(start, end, status="pending", is_manual=True))
        assert split
        assert sum(e.worked_minutes for e in active_rows(db)) == 480
        assert manual.status == "pending"
        metrics = services.calculate_dashboard_metrics(db, _admin_id(), DAY)
        assert metrics.total_work_minutes == 480 - manual.worked_minutes
        assert revisions.history(db, original.id)[-1].before_json
        crud.set_time_entry_status(db, manual.id, "approved")
        assert services.calculate_dashboard_metrics(db, _admin_id(), DAY).total_work_minutes == 480


def test_cancelled_entry_is_not_split_by_new_manual_entry(main):
    from app import crud, database, revisions

    with database.SessionLocal() as db:
        original = create(db)
        crud.cancel_time_entry(db, original.id, actor=None, reason="Fehleingabe")
        count = len(revisions.history(db, original.id))
        manual, split = crud.create_manual_time_entry(db, payload(time(10), time(11), status="pending"))
        assert not split
        assert original.start_time == time(8) and original.end_time == time(16)
        assert len(revisions.history(db, original.id)) == count
        assert len(active_rows(db)) == 1 and active_rows(db)[0].id == manual.id


def test_locked_period_cannot_be_bypassed_with_contained_manual_entry(main):
    from app import crud, database, models

    with database.SessionLocal() as db:
        original = create(db)
        db.add(models.PayrollPeriod(period_start=DAY, period_end=DAY, status="locked"))
        db.commit()
        with pytest.raises(crud.PeriodLocked):
            crud.create_manual_time_entry(db, payload(time(10), time(11), status="pending"))
        db.rollback()
        assert db.query(models.TimeEntry).count() == 1
        assert db.get(models.TimeEntry, original.id).end_time == time(16)


def test_manual_split_preserves_location_source_zone_and_break_rule(main):
    from app import crud, database, models, schemas

    with database.SessionLocal() as db:
        company = crud.create_company(db, schemas.CompanyCreate(name="Standort GmbH"))
        location = models.CompanyLocation(company_id=company.id, name="Werkstatt")
        db.add(location); db.commit()
        original = create(db, company_id=company.id, location_id=location.id, source="terminal",
                          tz_name="Europe/London")
        original.break_rule = models.BreakRule.LEGACY_AUTO
        db.commit()
        crud.create_manual_time_entry(db, payload(time(10), time(11), status="pending"))
        remaining = [e for e in active_rows(db) if e.status == "approved"]
        assert len(remaining) == 2
        for row in remaining:
            assert (row.location_id, row.source, row.tz_name, row.break_rule) == (
                location.id, "terminal", "Europe/London", models.BreakRule.LEGACY_AUTO)


@pytest.mark.parametrize("start,end,remaining_breaks,net", [
    (time(8, 5), time(9), 30, 450),
    (time(12, 10), time(12, 20), 20, 460),
    (time(11), time(13), 0, 480),
])
def test_split_distributes_stamped_pauses_by_actual_time(main, start, end, remaining_breaks, net):
    from app import crud, database, revisions

    with database.SessionLocal() as db:
        original = create(db)
        pause(db, original)
        manual, _ = crud.create_manual_time_entry(db, payload(start, end, status="pending", is_manual=True))
        entries = active_rows(db)
        assert sum(e.total_break_minutes for e in entries) == remaining_breaks
        assert sum(e.worked_minutes for e in entries) == net
        for entry in entries:
            from app import worktime
            start_utc, end_utc = worktime.entry_bounds(entry)
            for interval in entry.breaks:
                if interval.minutes:
                    assert start_utc.replace(tzinfo=None) <= interval.started_at_utc
                    assert interval.ended_at_utc <= end_utc.replace(tzinfo=None)
        before = revisions.parse(revisions.history(db, original.id)[-1].before_json)
        assert before["breaks"][0]["minutes"] == 30


def test_manual_split_running_entry_preserves_pause_location_and_history(main, monkeypatch):
    from app import crud, database, models, revisions, schemas

    freeze(monkeypatch, datetime.combine(DAY, time(16)).replace(tzinfo=BERLIN))
    with database.SessionLocal() as db:
        company = crud.create_company(db, schemas.CompanyCreate(name="Laufende Firma"))
        location = models.CompanyLocation(company_id=company.id, name="Lager")
        db.add(location); db.commit()
        original = crud.start_running_entry(db, user_id=_admin_id(), started_at=datetime.combine(DAY, time(8)),
                                            company_id=company.id, location_id=location.id)
        pause(db, original)
        manual, _ = crud.create_manual_time_entry(db, payload(time(10), time(11), status="pending"))
        entries = active_rows(db)
        assert sum(e.worked_minutes for e in entries) == 450
        assert sum(e.total_break_minutes for e in entries) == 30
        assert crud.get_open_time_entry(db, _admin_id()).start_time == time(11)
        assert all(e.location_id == location.id for e in entries if e.id != manual.id)
        assert revisions.history(db, original.id)[-1].before_json
        assert all(revisions.history(db, e.id) for e in entries)


def test_overwrite_splits_running_entry_but_keeps_following_segment_open(main, monkeypatch):
    from app import crud, database

    freeze(monkeypatch, datetime.combine(DAY, time(16)).replace(tzinfo=BERLIN))
    with database.SessionLocal() as db:
        edited = create(db, time(7), time(7, 30))
        running = crud.start_running_entry(db, user_id=_admin_id(), started_at=datetime.combine(DAY, time(8)))
        pause(db, running)
        crud.update_time_entry(db, edited.id, payload(time(10), time(11)), overwrite=True, reason="Zwischenauftrag")
        open_entry = crud.get_open_time_entry(db, _admin_id())
        assert open_entry is not None and open_entry.start_time == time(11)
        assert sum(e.worked_minutes for e in active_rows(db)) == 450


def test_overwrite_night_segment_keeps_following_calendar_date(main):
    from app import crud, database, worktime

    with database.SessionLocal() as db:
        edited = create(db, time(20), time(21))
        create(db, time(22), time(6))
        crud.update_time_entry(db, edited.id, payload(time(1), time(2), work_date=DAY + timedelta(days=1)),
                               overwrite=True, reason="Zwischenauftrag nachts")
        entries = active_rows(db)
        assert sum(e.worked_minutes for e in entries) == 480
        tail = next(e for e in entries if e.start_time == time(2))
        assert tail.work_date == DAY + timedelta(days=1)
        bounds = sorted(worktime.entry_bounds(e) for e in entries)
        assert all(left[1] == right[0] for left, right in zip(bounds, bounds[1:]))


def test_failed_replacement_leaves_original_and_history_unchanged(main):
    from app import crud, database, models, revisions

    with database.SessionLocal() as db:
        original = create(db, time(8), time(10))
        create(db, time(11), time(12))
        count = len(revisions.history(db, original.id))
        with pytest.raises(ValueError, match="OVERLAPPING_TIME_ENTRY"):
            crud.replace_time_entry(db, original.id, payload(time(8), time(12)), actor=None, reason="Ende korrigieren")
        db.rollback()
        assert db.get(models.TimeEntry, original.id).status == "approved"
        assert len(revisions.history(db, original.id)) == count


def test_edit_cancel_and_restore_keep_reasoned_history(main):
    from app import crud, database, revisions

    with database.SessionLocal() as db:
        entry = create(db, time(8), time(12))
        crud.update_time_entry(db, entry.id, payload(time(8), time(13)), reason="Ende nachgetragen")
        revision = revisions.history(db, entry.id)[-1]
        assert revisions.parse(revision.before_json)["end_time"] == "12:00:00"
        assert revisions.parse(revision.after_json)["end_time"] == "13:00:00"
        crud.cancel_time_entry(db, entry.id, actor=None, reason="Zunächst zurücknehmen")
        assert entry.worked_minutes == 0
        crud.set_time_entry_status(db, entry.id, "approved", reason="Stornierung geprüft und rückgängig")
        assert entry.worked_minutes == 300
        assert len(revisions.history(db, entry.id)) == 4


def test_reasonless_overwrite_cannot_leave_dirty_changes(main):
    from app import crud, database, models, revisions

    with database.SessionLocal() as db:
        edited = create(db, time(7), time(8))
        conflict = create(db, time(8), time(16))
        with pytest.raises(revisions.ReasonRequired):
            crud.update_time_entry(db, edited.id, payload(time(10), time(11)), overwrite=True, reason=" ")
        db.commit()  # A rejected operation must not leave half-applied ORM state.
        assert db.get(models.TimeEntry, conflict.id).end_time == time(16)
        assert db.query(models.TimeEntry).count() == 2


def test_finished_pause_sum_remains_available_after_session_closes(main):
    from app import crud, database

    with database.SessionLocal() as db:
        entry = crud.start_running_entry(db, user_id=_admin_id(), started_at=datetime.combine(DAY, time(8)))
        crud.start_break(db, entry, datetime.combine(DAY, time(12)))
        crud.end_break(db, entry, datetime.combine(DAY, time(12, 30)))
        crud.finish_running_entry(db, entry, datetime.combine(DAY, time(16)))
        assert entry.break_minutes == 30
        db.expunge(entry)  # Export fallback must agree with the live interval relation.
        assert entry.total_break_minutes == 30 and entry.worked_minutes == 450


@pytest.mark.parametrize("kind", ["reversed", "outside", "overlap", "reasonless"])
def test_invalid_pause_correction_is_rejected_without_partial_change(main, kind):
    from app import crud, database, revisions

    with database.SessionLocal() as db:
        entry = create(db)
        interval = pause(db, entry)
        pause(db, entry, time(14), time(14, 30))
        before = (interval.started_at_utc, interval.ended_at_utc)
        changes = {
            "reversed": dict(ended_at=datetime.combine(DAY, time(11))),
            "outside": dict(started_at=datetime.combine(DAY, time(7))),
            "overlap": dict(ended_at=datetime.combine(DAY, time(14, 15))),
            "reasonless": dict(ended_at=datetime.combine(DAY, time(12, 45))),
        }[kind]
        with pytest.raises(revisions.ReasonRequired if kind == "reasonless" else ValueError):
            crud.correct_break(db, interval.id, actor=None, reason="" if kind == "reasonless" else "Korrektur", **changes)
        db.commit()
        assert (interval.started_at_utc, interval.ended_at_utc) == before
        assert entry.worked_minutes == 420


def test_pause_correction_and_cancellation_update_minutes_and_history(main):
    from app import crud, database, revisions

    with database.SessionLocal() as db:
        entry = create(db)
        interval = pause(db, entry)
        crud.correct_break(db, interval.id, actor=None, reason="Pause zu spät beendet",
                           ended_at=datetime.combine(DAY, time(12, 45)))
        assert entry.break_minutes == 45 and entry.worked_minutes == 435
        crud.cancel_break(db, interval.id, actor=None, reason="Pause irrtümlich erfasst")
        assert interval.minutes == 0 and entry.break_minutes == 0 and entry.worked_minutes == 480
        history = revisions.history(db, entry.id)
        assert [item.action for item in history][-2:] == ["break_corrected", "break_cancelled"]
        assert revisions.parse(history[-1].before_json)["breaks"][0]["minutes"] == 45


def test_manual_insert_across_multiple_entries_is_rejected_without_mutation(main):
    from app import crud, database, revisions

    with database.SessionLocal() as db:
        first = create(db, time(8), time(10))
        second = create(db, time(10), time(12))
        with pytest.raises(ValueError, match="OVERLAPPING_TIME_ENTRY"):
            crud.create_manual_time_entry(db, payload(time(9), time(11), status="pending"))
        db.commit()
        assert [(e.start_time, e.end_time) for e in active_rows(db)] == [(time(8), time(10)), (time(10), time(12))]
        assert sum(e.worked_minutes for e in active_rows(db)) == 240
        assert len(revisions.history(db, first.id)) == len(revisions.history(db, second.id)) == 1


def test_overwrite_across_multiple_entries_has_no_double_count_and_preserves_history(main):
    from app import crud, database, revisions

    with database.SessionLocal() as db:
        edited = create(db, time(6), time(7))
        first = create(db, time(8), time(10))
        middle = create(db, time(10), time(12))
        last = create(db, time(12), time(16))
        plan = crud.plan_time_entry_overwrite(db, edited.id, payload(time(9), time(13)))
        assert [item["action"] for item in plan] == ["shorten", "delete", "shorten"]
        crud.update_time_entry(db, edited.id, payload(time(9), time(13)), overwrite=True,
                               reason="Übergreifender Kundentermin")
        assert [(e.start_time, e.end_time) for e in active_rows(db)] == [
            (time(8), time(9)), (time(9), time(13)), (time(13), time(16))]
        assert sum(e.worked_minutes for e in active_rows(db)) == 480
        assert middle.status == "cancelled"
        assert all(revisions.history(db, entry.id)[-1].before_json for entry in [first, middle, last])


def test_closed_entry_same_minute_does_not_block_adjacent_start(main, monkeypatch):
    from app import crud, database

    freeze(monkeypatch, datetime.combine(DAY, time(10)).replace(tzinfo=BERLIN))
    with database.SessionLocal() as db:
        create(db, time(8), time(8))
        entry = crud.start_running_entry(db, user_id=_admin_id(), started_at=datetime.combine(DAY, time(8)))
        crud.finish_running_entry(db, entry, datetime.combine(DAY, time(9)))
        assert sum(e.worked_minutes for e in active_rows(db)) == 60


def test_entry_edit_cannot_silently_override_stamped_pause_sum(main):
    from app import crud, database

    with database.SessionLocal() as db:
        entry = create(db)
        pause(db, entry)
        with pytest.raises(ValueError, match="BREAK_INTERVALS_REQUIRE_EDIT"):
            crud.update_time_entry(db, entry.id, payload(break_minutes=15), reason="Pause korrigieren")
        db.commit()
        assert entry.total_break_minutes == 30 and entry.worked_minutes == 450
        # A normal comment/end-time edit with the true sum still works.
        crud.update_time_entry(db, entry.id, payload(end=time(17), break_minutes=30, notes="Länger gearbeitet"), reason="Ende korrigieren")
        assert entry.worked_minutes == 510 and entry.notes == "Länger gearbeitet"


def test_entry_edit_cannot_leave_stamped_pause_outside_new_bounds(main):
    from app import crud, database

    with database.SessionLocal() as db:
        entry = create(db)
        pause(db, entry)
        with pytest.raises(ValueError, match="BREAK_OUTSIDE_ENTRY"):
            crud.update_time_entry(db, entry.id, payload(end=time(11), break_minutes=30), reason="Ende korrigieren")
        db.commit()
        assert entry.end_time == time(16) and entry.total_break_minutes == 30


def test_break_correction_rejects_wrong_entry_and_locked_period(main):
    from app import crud, database, models

    with database.SessionLocal() as db:
        entry = create(db)
        interval = pause(db, entry)
        kwargs = dict(actor=None, reason="Prüfung", ended_at=datetime.combine(DAY, time(12, 45)))
        assert crud.correct_break(db, interval.id, entry_id=entry.id + 100, **kwargs) is None
        db.add(models.PayrollPeriod(period_start=DAY, period_end=DAY, status="locked"))
        db.commit()
        with pytest.raises(crud.PeriodLocked):
            crud.correct_break(db, interval.id, entry_id=entry.id, **kwargs)
        db.commit()
        assert interval.minutes == 30


def test_cancelled_break_does_not_block_valid_correction(main):
    from app import crud, database

    with database.SessionLocal() as db:
        entry = create(db)
        interval = pause(db, entry)
        cancelled = pause(db, entry, time(12, 40), time(12, 50))
        crud.cancel_break(db, cancelled.id, actor=None, reason="Doppelte Pause")
        crud.correct_break(db, interval.id, actor=None, reason="Tatsächliches Pausenende",
                           ended_at=datetime.combine(DAY, time(13)))
        assert entry.total_break_minutes == 60 and entry.worked_minutes == 420


def test_overwrite_cannot_touch_a_locked_previous_night(main):
    from app import crud, database, models

    with database.SessionLocal() as db:
        previous = create(db, time(22), time(6))
        edited = create(db, time(8), time(9), work_date=DAY + timedelta(days=1))
        db.add(models.PayrollPeriod(period_start=DAY, period_end=DAY, status="locked"))
        db.commit()
        with pytest.raises(crud.PeriodLocked):
            crud.update_time_entry(db, edited.id,
                                   payload(time(1), time(2), work_date=DAY + timedelta(days=1)),
                                   overwrite=True, reason="Übergreifende Korrektur")
        db.commit()
        assert previous.end_time == time(6) and edited.start_time == time(8)
        assert len(active_rows(db)) == 2


def test_failure_after_replacement_insert_rolls_back_cancellation_too(main, monkeypatch):
    from app import crud, database, models, revisions

    with database.SessionLocal() as db:
        original = create(db, time(8), time(10))
        actual_create = crud.create_time_entry

        def failed_create(*args, **kwargs):
            actual_create(*args, **kwargs)
            raise RuntimeError("Failure after replacement insert")

        monkeypatch.setattr(crud, "create_time_entry", failed_create)
        with pytest.raises(RuntimeError, match="Failure after"):
            crud.replace_time_entry(db, original.id, payload(time(8), time(11)), actor=None, reason="Endzeit")
        assert db.get(models.TimeEntry, original.id).status == "approved"
        assert db.query(models.TimeEntry).count() == 1
        assert len(revisions.history(db, original.id)) == 1


def test_manual_split_history_names_actual_actor_for_every_created_part(main):
    from app import crud, database, revisions

    with database.SessionLocal() as db:
        actor = crud.get_user_by_username(db, "admin")
        original = create(db)
        crud.create_manual_time_entry(db, payload(time(10), time(11), status="pending"), actor=actor)
        assert revisions.history(db, original.id)[-1].actor_id == actor.id
        assert all(revisions.history(db, e.id)[-1].actor_id == actor.id for e in active_rows(db))


def test_recent_manual_insert_uses_business_clock_when_host_runs_utc(main, monkeypatch):
    from app import crud, database, worktime

    class UTCServer(datetime):
        @classmethod
        def now(cls, tz=None):
            utc = datetime.combine(DAY, time(16)).replace(tzinfo=timezone.utc)
            return utc.astimezone(tz) if tz else utc.replace(tzinfo=None)

    monkeypatch.setattr(crud, "datetime", UTCServer)
    monkeypatch.setattr(worktime, "datetime", UTCServer)
    with database.SessionLocal() as db:
        crud.start_running_entry(db, user_id=_admin_id(), started_at=datetime.combine(DAY, time(8)))
        manual, split = crud.create_manual_time_entry(db, payload(time(16, 15), time(16, 30), status="pending"))
        assert split and manual.worked_minutes == 15
        assert sum(e.worked_minutes for e in active_rows(db)) == 540  # 08:00–17:00 Berlin.


@pytest.mark.parametrize("day,start,end,offset,expected", [
    (DAY, time(23), time(1), 0, 450),
    (DAY, time(1), time(2), 1, 450),
    (DAY, time(22), time(1), 0, 450),
    (date(2026, 3, 28), time(23), time(1), 0, 390),
    (date(2026, 10, 24), time(23), time(1), 0, 510),
])
def test_manual_night_insert_keeps_tail_date_pause_and_elapsed_minutes(main, day, start, end, offset, expected):
    from app import crud, database, models, worktime, revisions

    following = day + timedelta(days=1)
    with database.SessionLocal() as db:
        original = create(db, time(22), time(6), work_date=day)
        db.add(models.BreakInterval(entry_id=original.id,
                                    started_at_utc=worktime.to_utc_naive(datetime.combine(following, time(4)), "Europe/Berlin"),
                                    ended_at_utc=worktime.to_utc_naive(datetime.combine(following, time(4, 30)), "Europe/Berlin"),
                                    tz_name="Europe/Berlin", source="web"))
        db.commit(); db.refresh(original)
        manual, split = crud.create_manual_time_entry(db, payload(start, end, work_date=day + timedelta(days=offset), status="pending"))
        assert split and manual.status == "pending"
        entries = active_rows(db)
        assert sum(e.worked_minutes for e in entries) == expected
        assert sum(e.total_break_minutes for e in entries) == 30
        tail = next(e for e in entries if e.start_time == end and e.id != manual.id)
        assert tail.work_date == following and tail.end_time == time(6)
        assert tail.total_break_minutes == 30
        bounds = sorted(worktime.entry_bounds(e) for e in entries)
        assert all(left[1] == right[0] for left, right in zip(bounds, bounds[1:]))
        assert revisions.parse(revisions.history(db, original.id)[-1].before_json)["work_date"] == day.isoformat()


def test_manual_after_midnight_cannot_split_locked_previous_day(main):
    from app import crud, database, models

    with database.SessionLocal() as db:
        original = create(db, time(22), time(6))
        db.add(models.PayrollPeriod(period_start=DAY, period_end=DAY, status="locked"))
        db.commit()
        with pytest.raises(crud.PeriodLocked):
            crud.create_manual_time_entry(db, payload(time(1), time(2), work_date=DAY + timedelta(days=1), status="pending"))
        db.commit()
        assert original.work_date == DAY and original.start_time == time(22)
        assert len(active_rows(db)) == 1


def test_stamps_in_repeated_hour_use_utc_for_overlap_check(main):
    from app import crud, database

    day = date(2026, 10, 25)
    with database.SessionLocal() as db:
        create(db, time(2), time(2, 20), work_date=day,
               started_at_utc=datetime(2026, 10, 25, 0),
               ended_at_utc=datetime(2026, 10, 25, 0, 20), tz_name="Europe/Berlin")
        second = crud.start_running_entry(db, user_id=_admin_id(),
                                          started_at=datetime(2026, 10, 25, 2, 10, tzinfo=BERLIN, fold=1))
        crud.finish_running_entry(db, second, datetime(2026, 10, 25, 2, 40, tzinfo=BERLIN, fold=1))
        assert second.started_at_utc == datetime(2026, 10, 25, 1, 10)
        assert sum(e.worked_minutes for e in active_rows(db)) == 50


def test_pause_correction_preserves_known_second_occurrence_of_clock_hour(main):
    from app import crud, database, models

    with database.SessionLocal() as db:
        entry = create(db, time(22), time(6), work_date=date(2026, 10, 24))
        interval = models.BreakInterval(entry_id=entry.id, started_at_utc=datetime(2026, 10, 25, 1, 15),
                                        ended_at_utc=datetime(2026, 10, 25, 1, 35), tz_name="Europe/Berlin")
        db.add(interval); db.commit()
        crud.correct_break(db, interval.id, actor=None, reason="Pausenende nachgetragen",
                           started_at=datetime(2026, 10, 25, 2, 15), ended_at=datetime(2026, 10, 25, 2, 45))
        assert interval.started_at_utc == datetime(2026, 10, 25, 1, 15)
        assert interval.ended_at_utc == datetime(2026, 10, 25, 1, 45)
        assert entry.total_break_minutes == 30 and entry.worked_minutes == 510


def test_pause_correction_rejects_nonexistent_spring_clock_time(main):
    from app import crud, database, models

    with database.SessionLocal() as db:
        entry = create(db, time(1), time(4), work_date=date(2026, 3, 29))
        interval = models.BreakInterval(entry_id=entry.id, started_at_utc=datetime(2026, 3, 29, 0, 30),
                                        ended_at_utc=datetime(2026, 3, 29, 1, 30), tz_name="Europe/Berlin")
        db.add(interval); db.commit()
        with pytest.raises(ValueError, match="INVALID_BREAK_INTERVAL"):
            crud.correct_break(db, interval.id, actor=None, reason="Ungültige lokale Uhrzeit",
                               started_at=datetime(2026, 3, 29, 2, 15))
        db.commit()
        assert interval.started_at_utc == datetime(2026, 3, 29, 0, 30)


def test_manual_split_after_business_timezone_change_preserves_elapsed_coverage(main):
    from app import crud, database, worktime

    with database.SessionLocal() as db:
        original = create(db, time(8), time(16), tz_name="Europe/London")
        original_bounds = worktime.entry_bounds(original)
        # The new record uses Berlin; 10:00–11:00 there is 09:00–10:00 London.
        crud.create_manual_time_entry(db, payload(time(10), time(11), status="pending", tz_name="Europe/Berlin"))
        bounds = sorted(worktime.entry_bounds(e) for e in active_rows(db))
        assert bounds[0][0] == original_bounds[0] and bounds[-1][1] == original_bounds[1]
        assert all(left[1] == right[0] for left, right in zip(bounds, bounds[1:]))
        assert sum(e.worked_minutes for e in active_rows(db)) == 480


def test_start_only_correction_preserves_exact_end_in_second_clock_hour(main):
    from app import crud, database

    day = date(2026, 10, 25)
    with database.SessionLocal() as db:
        entry = create(db, time(1), time(2, 30), work_date=day, tz_name="Europe/Berlin",
                       started_at_utc=datetime(2026, 10, 24, 23),
                       ended_at_utc=datetime(2026, 10, 25, 1, 30))
        crud.update_time_entry(db, entry.id, payload(time(1, 30), time(2, 30), work_date=day),
                               reason="Beginn nachgetragen")
        assert entry.started_at_utc == datetime(2026, 10, 24, 23, 30)
        assert entry.ended_at_utc == datetime(2026, 10, 25, 1, 30)
        assert entry.worked_minutes == 120


def test_start_correction_that_changes_overnight_assignment_updates_end_date(main):
    from app import crud, database

    with database.SessionLocal() as db:
        entry = create(db, time(22), time(6))
        crud.update_time_entry(db, entry.id, payload(time(5), time(6)), reason="Tatsächlich Frühschicht")
        assert entry.ended_at_utc == datetime(2026, 2, 10, 5)
        assert entry.worked_minutes == 60


def test_pause_correction_cannot_overlap_a_currently_running_pause(main, monkeypatch):
    from app import crud, database

    freeze(monkeypatch, datetime.combine(DAY, time(16)).replace(tzinfo=BERLIN))
    with database.SessionLocal() as db:
        entry = crud.start_running_entry(db, user_id=_admin_id(), started_at=datetime.combine(DAY, time(8)))
        previous = pause(db, entry, time(10), time(10, 30))
        crud.start_break(db, entry, datetime.combine(DAY, time(12)))
        with pytest.raises(ValueError, match="BREAK_RUNNING"):
            crud.correct_break(db, previous.id, actor=None, reason="Pausenende",
                               ended_at=datetime.combine(DAY, time(12, 15)))
        db.commit()
        assert previous.minutes == 30 and entry.running_break is not None


@pytest.mark.parametrize("start,end,expected_start,expected_end,minutes", [
    (time(2, 20), time(2, 40), datetime(2026, 10, 25, 1, 20), datetime(2026, 10, 25, 1, 40), 20),
    (time(2, 10), time(2, 50), datetime(2026, 10, 25, 1, 10), datetime(2026, 10, 25, 1, 50), 40),
])
@pytest.mark.parametrize("earlier_booking", [False, True])
def test_boundary_edit_within_known_second_clock_hour_keeps_its_occurrence(
    main, start, end, expected_start, expected_end, minutes, earlier_booking,
):
    from app import crud, database

    day = date(2026, 10, 25)
    with database.SessionLocal() as db:
        if earlier_booking:
            earlier = create(db, time(2, 41), time(2, 59), work_date=day, tz_name="Europe/Berlin",
                             started_at_utc=datetime(2026, 10, 25, 0, 41),
                             ended_at_utc=datetime(2026, 10, 25, 0, 59))
        entry = create(db, time(2, 10), time(2, 40), work_date=day, tz_name="Europe/Berlin",
                       started_at_utc=datetime(2026, 10, 25, 1, 10),
                       ended_at_utc=datetime(2026, 10, 25, 1, 40))
        correction = payload(start, end, work_date=day)
        assert crud.plan_time_entry_overwrite(db, entry.id, correction) == []
        crud.update_time_entry(db, entry.id, correction,
                               reason="Zeit innerhalb der zweiten Stunde korrigieren")
        assert entry.started_at_utc == expected_start
        assert entry.ended_at_utc == expected_end
        assert entry.worked_minutes == minutes
        if earlier_booking:
            assert earlier.worked_minutes == 18 and earlier.status == "approved"


@pytest.mark.parametrize("field,value,expected,minutes", [
    ("start_time", time(2, 20), datetime(2026, 10, 25, 1, 20), 20),
    ("end_time", time(2, 50), datetime(2026, 10, 25, 1, 50), 40),
])
def test_mapper_retains_fold_when_only_one_boundary_is_changed(main, field, value, expected, minutes):
    from app import database

    with database.SessionLocal() as db:
        entry = create(db, time(2, 10), time(2, 40), work_date=date(2026, 10, 25),
                       tz_name="Europe/Berlin", started_at_utc=datetime(2026, 10, 25, 1, 10),
                       ended_at_utc=datetime(2026, 10, 25, 1, 40))
        setattr(entry, field, value)
        db.commit(); db.refresh(entry)
        assert getattr(entry, "started_at_utc" if field == "start_time" else "ended_at_utc") == expected
        assert entry.worked_minutes == minutes


def test_explicit_utc_correction_keeps_precedence_over_previous_fold(main):
    from app import crud, database

    day = date(2026, 10, 25)
    with database.SessionLocal() as db:
        entry = create(db, time(2, 10), time(2, 40), work_date=day, tz_name="Europe/Berlin",
                       started_at_utc=datetime(2026, 10, 25, 1, 10), ended_at_utc=datetime(2026, 10, 25, 1, 40))
        crud.update_time_entry(db, entry.id,
                               payload(time(2, 20), time(2, 40), work_date=day,
                                       started_at_utc=datetime(2026, 10, 25, 0, 20)),
                               reason="Erste Stunde ausdrücklich ausgewählt")
        assert entry.started_at_utc == datetime(2026, 10, 25, 0, 20)
        assert entry.ended_at_utc == datetime(2026, 10, 25, 1, 40)
        assert entry.worked_minutes == 80


@pytest.mark.parametrize("changed_day,changed_zone,start,end,expected", [
    (date(2027, 10, 31), "Europe/Berlin", time(2, 20), time(2, 40), datetime(2027, 10, 31, 0, 20)),
    (date(2026, 10, 25), "Europe/London", time(1, 20), time(1, 40), datetime(2026, 10, 25, 0, 20)),
])
def test_fold_is_not_inherited_when_date_or_timezone_changes(main, changed_day, changed_zone, start, end, expected):
    from app import crud, database

    with database.SessionLocal() as db:
        entry = create(db, time(2, 10), time(2, 40), work_date=date(2026, 10, 25),
                       tz_name="Europe/Berlin", started_at_utc=datetime(2026, 10, 25, 1, 10),
                       ended_at_utc=datetime(2026, 10, 25, 1, 40))
        crud.update_time_entry(db, entry.id, payload(start, end, work_date=changed_day, tz_name=changed_zone),
                               reason="Datum bzw. Betriebszeitzone korrigieren")
        assert entry.started_at_utc == expected and entry.worked_minutes == 20
