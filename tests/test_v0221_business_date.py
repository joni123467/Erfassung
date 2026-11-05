"""Stempelung, Tagesansicht und Synchronisation teilen dieselbe Betriebszeit."""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from test_v0209 import client, main, _login


@pytest.mark.parametrize("instant_text", [
    "2026-11-04T23:10:00+00:00",  # Winter: UTC noch am Vortag
    "2026-06-30T22:10:00+00:00",  # Sommer und Monatswechsel
    "2026-12-31T23:10:00+00:00",  # Jahreswechsel
    "2026-11-01T23:10:00+00:00",  # Sonntag UTC, Montag im Betrieb
    "2026-11-04T12:10:00+00:00",  # Kontrollfall ohne Datumsunterschied
])
def test_punch_and_overviews_share_business_date(client, main, monkeypatch, instant_text):
    _login(client)
    csrf = client.get("/api/csrf").json()["csrf_token"]
    clock = {"instant": datetime.fromisoformat(instant_text)}

    class UtcHostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = clock["instant"]
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return clock["instant"].replace(tzinfo=None)

    class UtcHostDate(date):
        @classmethod
        def today(cls):
            return clock["instant"].date()

    monkeypatch.setattr(main, "datetime", UtcHostClock)
    monkeypatch.setattr(main, "date", UtcHostDate)
    local_day = clock["instant"].astimezone(ZoneInfo("Europe/Berlin")).date()
    hidden_button = r'id="mobile-notes-launch"[^>]*hidden'
    assert re.search(hidden_button, client.get("/mobile").text, re.S)

    def punch(action, **fields):
        response = client.post(
            "/punch", data={"action": action, "csrf_token": csrf, **fields},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 200 and response.json()["ok"] is True

    punch("start_work")
    clock["instant"] += timedelta(minutes=10)
    punch("end_work")
    mobile = client.get("/mobile")
    assert not re.search(hidden_button, mobile.text, re.S)
    assert mobile.context["last_finished_entry"].work_date == local_day
    assert mobile.context["overview_day"]["worked_minutes"] == 10
    punch("update_notes", notes="Kommentar nach Mitternacht")

    for url in ("/dashboard", "/mobile"):
        response = client.get(url)
        context = response.context
        assert context["today"] == local_day
        assert context["overview_reference_date"] == local_day
        assert context["metrics_month"] == local_day.replace(day=1)
        assert len(context["daily_entries"]) == 1
        assert context["daily_entries"][0].notes == "Kommentar nach Mitternacht"
        if url == "/dashboard":
            assert f'name="work_date" value="{local_day.isoformat()}"' in response.text
        days = client.get(url + "?overview=week").context["weekly_summary"]["days"]
        today_row, = [day for day in days if day["is_today"]]
        assert today_row["date"] == local_day
        assert today_row["worked_minutes"] == 10
        # Eine bewusst gewählte historische Ansicht bleibt wählbar.
        previous_day = local_day - timedelta(days=1)
        history = client.get(url + f"?date={previous_day}").context
        assert history["overview_reference_date"] == previous_day
        assert history["today"] == local_day

    snapshot = client.get("/mobile/sync-data?days=1").json()
    assert snapshot["period"]["from"] == (local_day - timedelta(days=1)).isoformat()
    assert snapshot["period"]["to"] == (local_day + timedelta(days=1)).isoformat()
    assert snapshot["metrics"]["worked_minutes"] - snapshot["metrics"]["holiday_minutes"] == 10
    entry, = snapshot["entries"]
    assert entry["work_date"] == local_day.isoformat()

    # Auch die Vorgaben der Buchungslisten/Exporte dürfen keinen Vortag wählen.
    for value in (None, "ungueltig"):
        assert main._resolve_month_period(value)[0] == local_day.replace(day=1)
        assert main._resolve_week_period(value)[0] == local_day - timedelta(days=local_day.weekday())
    assert main._resolve_range_period(None, None)[0] == local_day.replace(day=1)
