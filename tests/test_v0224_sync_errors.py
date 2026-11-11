"""Sync-Konflikte nennen den Fehler auch bei gleichzeitigem Erfolgstext."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta

import pytest

from test_v0209 import client, main, _login, _csrf
from test_v0210 import event, send


@pytest.mark.parametrize("action,blocked", [
    ("start_company", "overlap"),
    ("start_company", "locked"),
    ("end_company", "overlap"),
])
def test_sync_and_review_show_actual_error_without_changing_bookings(client, action, blocked):
    _login(client)
    from app import crud, database, models, schemas, worktime

    data = event(client, action, "conflicting-order")
    day = datetime.fromisoformat(data["payload"]["event_time"]).astimezone(worktime.zone()).date()
    moment = datetime.combine(day, time(11, 35), tzinfo=worktime.zone())
    data["payload"]["event_time"] = moment.isoformat()
    with database.SessionLocal() as db:
        company = crud.create_company(db, schemas.CompanyCreate(name="Testauftrag"))
        data["payload"]["company_id"] = str(company.id)
        if action == "end_company":
            crud.start_running_entry(db, user_id=data["owner_id"], company_id=company.id,
                                     started_at=moment - timedelta(hours=1))
        if blocked == "overlap":
            db.add(models.TimeEntry(
                user_id=data["owner_id"], work_date=day,
                start_time=time(10, 52) if action == "start_company" else time(12),
                end_time=time(2, 14) if action == "start_company" else time(13),
                is_open=False, break_minutes=0,
                status=models.TimeEntryStatus.APPROVED,
            ))
        else:
            db.add(models.PayrollPeriod(period_start=day, period_end=day, status=models.PeriodStatus.LOCKED))
        db.commit()

    def bookings():
        with database.SessionLocal() as db:
            return [
                (row.id, row.company_id, row.started_at_utc, row.ended_at_utc, row.is_open)
                for row in db.query(models.TimeEntry).order_by(models.TimeEntry.id)
            ], db.query(models.TimeEntryRevision).count()

    before = bookings()
    response = send(client, data)
    assert response.status_code == 200
    receipt = response.json()
    expected = "Zeitraum überschneidet sich mit einer vorhandenen Buchung." if blocked == "overlap" else "abgerechnet"
    assert receipt["status"] == "conflict"
    assert expected in receipt["message"]
    assert "läuft bereits" not in receipt["message"]
    assert send(client, data).json()["message"] == receipt["message"]
    assert bookings() == before

    # Bereits gespeicherte Meldungen einer alten Version werden bei der
    # ausdrücklich angeforderten erneuten Prüfung ebenfalls korrigiert.
    with database.SessionLocal() as db:
        row = db.get(models.MobileSyncReceipt, receipt["receipt_id"])
        row.message = "Auftrag bei Testauftrag läuft bereits."
        original = row.payload_json, row.payload_hash
        db.commit()
    reviewed = client.post(
        f"/admin/sync-conflicts/{receipt['receipt_id']}",
        data={"decision": "retry", "reason": "Ursache erneut prüfen",
              "csrf_token": _csrf(client, "/admin/sync-conflicts")},
        follow_redirects=False,
    )
    assert reviewed.status_code == 303
    assert expected in client.get(reviewed.headers["location"]).text
    assert bookings() == before
    with database.SessionLocal() as db:
        row = db.get(models.MobileSyncReceipt, receipt["receipt_id"])
        assert row.status == "conflict" and row.message == receipt["message"]
        assert (row.payload_json, row.payload_hash) == original
        assert json.loads(row.payload_json) == data["payload"]
        assert row.resolved_at is None
        assert db.query(models.MobileSyncAction).count() == 0

    if action == "start_company" and blocked == "overlap":
        entry_id = before[0][0][0]
        corrected = client.post(
            f"/admin/time-entries/{entry_id}/update",
            data={"user_id": data["owner_id"], "work_date": day.isoformat(),
                  "start_time": "10:52", "end_time": "11:35",
                  "change_reason": "Allgemeine Arbeitszeit endete beim Auftragswechsel",
                  "csrf_token": _csrf(client, f"/admin/time-entries/{entry_id}/edit")},
            follow_redirects=False,
        )
        assert corrected.status_code == 303
        assert "error=" not in corrected.headers["location"]
        reviewed = client.post(
            f"/admin/sync-conflicts/{receipt['receipt_id']}",
            data={"decision": "retry", "reason": "Überschneidung nach Prüfung korrigiert",
                  "csrf_token": _csrf(client, "/admin/sync-conflicts")},
            follow_redirects=False,
        )
        assert reviewed.status_code == 303
        assert send(client, data).json()["status"] == "applied"
        stop = event(client, "end_work", "following-stop")
        stop["payload"]["event_time"] = moment.replace(hour=13, minute=0).isoformat()
        assert send(client, stop).json()["status"] == "applied"
        with database.SessionLocal() as db:
            entries = db.query(models.TimeEntry).order_by(models.TimeEntry.id).all()
            assert len(entries) == 2 and all(not row.is_open for row in entries)
            assert entries[0].start_time == time(10, 52)
            assert entries[0].end_time == entries[1].start_time == time(11, 35)
            assert entries[1].end_time == time(13)
            assert entries[0].company_id is None
            assert str(entries[1].company_id) == data["payload"]["company_id"]
            row = db.get(models.MobileSyncReceipt, receipt["receipt_id"])
            assert (row.payload_json, row.payload_hash) == original
            assert row.resolved_at is not None and row.resolved_by_id is not None


def _correction(client):
    from app import database, models
    _login(client)
    start = event(client, "start_work", "forgotten-start", days=1)
    assert send(client, start).json()["status"] == "applied"
    moment = datetime.fromisoformat(start["payload"]["event_time"])
    correction = event(client, "correct_end_work", "actual-end", days=1)
    with database.SessionLocal() as db:
        entry_id = db.query(models.TimeEntry).one().id
    correction["payload"].update(
        event_time=(moment + timedelta(hours=8)).isoformat(),
        expected_started_at=moment.isoformat(), entry_id=str(entry_id),
        correction_reason="Ausstempeln vergessen; tatsächliches Ende nachgetragen",
    )
    return correction, entry_id


def test_actual_end_is_saved_once_with_reason_and_original_start(client):
    from app import database, models, worktime
    correction, entry_id = _correction(client)
    response = send(client, correction).json()
    assert response["status"] == "applied"
    assert send(client, correction).json()["duplicate"] is True
    with database.SessionLocal() as db:
        entry = db.get(models.TimeEntry, entry_id)
        assert not entry.is_open and db.query(models.TimeEntry).count() == 1
        assert worktime.entry_bounds(entry)[1] == datetime.fromisoformat(correction["payload"]["event_time"]).replace(microsecond=0)
        revisions = db.query(models.TimeEntryRevision).filter_by(action=models.RevisionAction.CLOSED).all()
        assert len(revisions) == 1
        assert revisions[0].actor_id == correction["owner_id"]
        assert revisions[0].reason == correction["payload"]["correction_reason"]
    snapshot = client.get("/mobile/sync-data").json()
    assert snapshot["active_entry"] is None
    assert datetime.fromisoformat(snapshot["entries"][0]["started_at"]) == datetime.fromisoformat(correction["payload"]["expected_started_at"]).replace(microsecond=0)


@pytest.mark.parametrize("invalid", ["reason", "start", "entry", "future", "before_start", "pause", "closed"])
def test_actual_end_rejects_stale_or_invalid_corrections_without_changing_data(client, invalid):
    from app import crud, database, models
    correction, entry_id = _correction(client)
    payload = correction["payload"]
    if invalid == "reason":
        payload["correction_reason"] = " "
    elif invalid == "start":
        payload["expected_started_at"] = (datetime.fromisoformat(payload["expected_started_at"]) - timedelta(hours=1)).isoformat()
    elif invalid == "entry":
        payload["entry_id"] = str(entry_id + 1)
    elif invalid == "future":
        payload["event_time"] = (datetime.now().astimezone() + timedelta(minutes=1)).isoformat()
    elif invalid == "before_start":
        payload["event_time"] = (datetime.fromisoformat(payload["expected_started_at"]) - timedelta(minutes=1)).isoformat()
    with database.SessionLocal() as db:
        entry = db.get(models.TimeEntry, entry_id)
        if invalid == "pause":
            crud.start_break(db, entry, datetime.fromisoformat(payload["event_time"]) + timedelta(hours=1))
        elif invalid == "closed":
            crud.finish_running_entry(db, entry, datetime.fromisoformat(payload["event_time"]))
        before = entry.is_open, entry.ended_at_utc, entry.break_started_at, db.query(models.TimeEntryRevision).count()
    response = send(client, correction).json()
    assert response["status"] == "conflict"
    with database.SessionLocal() as db:
        entry = db.get(models.TimeEntry, entry_id)
        assert (entry.is_open, entry.ended_at_utc, entry.break_started_at, db.query(models.TimeEntryRevision).count()) == before
        assert db.query(models.MobileSyncAction).filter_by(client_action_id=correction["client_action_id"]).count() == 0
        receipt = db.get(models.MobileSyncReceipt, response["receipt_id"])
        assert json.loads(receipt.payload_json) == payload


@pytest.mark.parametrize("stale_action", ["end_work", "start_break", "end_break", "start_company"])
def test_another_device_cannot_apply_a_stale_action_to_a_new_session(client, stale_action):
    from app import database, models
    correction, entry_id = _correction(client)
    old_start = correction["payload"]["expected_started_at"]
    assert send(client, correction).json()["status"] == "applied"
    new_start = event(client, "start_work", "second-device-start", days=0)
    assert send(client, new_start).json()["status"] == "applied"
    stale = event(client, stale_action, "first-device-stale", days=0)
    stale["payload"].update(expected_state="working", expected_started_at=old_start,
                            expected_entry_id=str(entry_id))
    response = send(client, stale).json()
    assert response["status"] == "conflict"
    assert "anderen Gerät" in response["message"]
    with database.SessionLocal() as db:
        active = db.query(models.TimeEntry).filter_by(is_open=True).one()
        assert active.id != entry_id and active.break_started_at is None
        assert db.query(models.TimeEntry).count() == 2
        assert json.loads(db.get(models.MobileSyncReceipt, response["receipt_id"]).payload_json) == stale["payload"]


def test_second_device_start_and_pause_races_preserve_first_device_state(client):
    from app import database, models
    correction, entry_id = _correction(client)
    stale = event(client, "start_work", "stale-idle-start", days=0)
    stale["payload"]["expected_state"] = "idle"
    assert send(client, stale).json()["status"] == "conflict"
    pause = event(client, "start_break", "device-pause", days=0)
    pause["payload"].update(expected_state="working",
                            expected_started_at=correction["payload"]["expected_started_at"])
    assert send(client, pause).json()["status"] == "applied"
    stale_stop = event(client, "end_work", "stale-stop-before-pause", days=0)
    stale_stop["payload"].update(expected_state="working",
                                 expected_started_at=correction["payload"]["expected_started_at"])
    assert send(client, stale_stop).json()["status"] == "conflict"
    with database.SessionLocal() as db:
        entry = db.get(models.TimeEntry, entry_id)
        assert entry.is_open and entry.break_started_at is not None
        assert db.query(models.TimeEntry).count() == 1


def test_simultaneous_device_starts_have_one_effect_and_keep_both_originals(client):
    from app import database, models
    _login(client)
    actions = [event(client, "start_work", f"device-{device}", days=0) for device in (1, 2)]
    for action in actions:
        action["payload"]["expected_state"] = "idle"
    token = client.get('/api/mobile/session').json()['csrf_token']
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda action: client.post('/api/mobile/actions', json=action,
                              headers={'X-CSRF-Token': token}).json(), actions))
    assert sorted(response["status"] for response in responses) == ["applied", "conflict"]
    with database.SessionLocal() as db:
        assert db.query(models.TimeEntry).count() == 1
        receipts = db.query(models.MobileSyncReceipt).all()
        assert len(receipts) == 2
        assert {row.client_action_id for row in receipts} == {action['client_action_id'] for action in actions}


def test_old_pause_end_cannot_close_a_newer_pause_on_the_same_booking(client):
    from app import database, models, worktime
    correction, entry_id = _correction(client)
    started = datetime.fromisoformat(correction["payload"]["expected_started_at"])
    for action, ident, hours in [("start_break", "first-pause", 1), ("end_break", "first-pause-end", 2), ("start_break", "second-pause", 3)]:
        stamp = event(client, action, ident)
        stamp["payload"]["event_time"] = (started + timedelta(hours=hours)).isoformat()
        assert send(client, stamp).json()["status"] == "applied"
    stale = event(client, "end_break", "old-phone-pause-end")
    stale["payload"].update(event_time=(started + timedelta(hours=4)).isoformat(),
                            expected_state="break", expected_started_at=started.isoformat(),
                            expected_entry_id=str(entry_id),
                            expected_break_started_at=(started + timedelta(hours=1)).isoformat())
    assert send(client, stale).json()["status"] == "conflict"
    with database.SessionLocal() as db:
        entry = db.get(models.TimeEntry, entry_id)
        assert worktime.from_utc_column(entry.running_break.started_at_utc) == (started + timedelta(hours=3)).replace(microsecond=0)
        assert len(entry.breaks) == 2
