"""Online-Stempelung nutzt die Betriebszeit auch auf einem UTC-Host."""
from datetime import datetime, time, timezone

import pytest

from test_v0209 import client, main, _login


@pytest.mark.parametrize("month,local_hour", [(1, 13), (7, 14)])
@pytest.mark.parametrize("event_time", [None, "ungueltige-geraetezeit"])
def test_event_time_fallback_uses_business_timezone_on_utc_host(client, main, monkeypatch, month, local_hour, event_time):
    _login(client)
    csrf = client.get("/api/csrf").json()["csrf_token"]
    instant = datetime(2026, month, 15, 12, 10, 20, tzinfo=timezone.utc)

    class UtcHostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    monkeypatch.setattr(main, "datetime", UtcHostClock)
    expected_local = datetime(2026, month, 15, local_hour, 10, 20)
    assert main._parse_event_time(event_time) == expected_local
    assert main._parse_event_time("2099-01-01T00:00:00") == expected_local
    assert main._parse_event_time(instant.isoformat()) == expected_local
    payload = {"action": "start_work", "csrf_token": csrf}
    if event_time is not None:
        payload["event_time"] = event_time
    response = client.post("/punch", data=payload, headers={"Accept": "application/json"})
    assert response.status_code == 200 and response.json()["ok"] is True
    from app import database, models

    with database.SessionLocal() as db:
        entry = db.query(models.TimeEntry).one()
        assert entry.work_date == instant.date()
        assert entry.start_time == time(local_hour, 10, 20)
        assert entry.started_at_utc == instant.replace(tzinfo=None)
