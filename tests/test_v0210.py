"""SC800 push ingestion, enrollment, deduplication and offline batches."""
from __future__ import annotations

import sys
from datetime import datetime

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/db.sqlite")
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("TERMINAL_SUPPORT", "true")
    for name in [name for name in sys.modules if name.startswith("app")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    import app.main as main
    from app import database
    with TestClient(main.app) as client:
        yield client, database.SessionLocal


def _user(db, username="worker", active=True):
    from app import models
    user = models.User(username=username, full_name=username, email=f"{username}@test.invalid",
                       pin_code=str(abs(hash(username)) % 10000).zfill(4), is_active=active)
    db.add(user); db.commit(); db.refresh(user)
    return user


def _terminal(db, serial="SC-A", active=True):
    from app import models
    terminal = models.Terminal(name=serial, type="zkteco_sc800", manufacturer="ZKTeco",
        model="SC800", serial_number=serial, active=active,
        enrollment_status="approved", timezone="Europe/Berlin")
    db.add(terminal); db.commit(); db.refresh(terminal)
    return terminal


def _map(db, terminal, user, external="17", card=None):
    from app import models
    identity = models.TerminalIdentity(terminal_id=terminal.id, user_id=user.id,
                                       external_user_id=external)
    db.add(identity); db.flush()
    if card:
        db.add(models.TerminalCard(terminal_id=terminal.id, identity_id=identity.id,
                                   card_identifier=card))
    db.commit()


def test_unknown_device_is_pending_and_does_not_book(env):
    client, session = env
    response = client.post("/iclock/cdata?SN=NEW001&table=ATTLOG",
                           content=b"17\t2026-09-07 08:00:00\t0\t4\t")
    assert response.status_code == 200
    from app import models
    with session() as db:
        terminal = db.query(models.Terminal).filter_by(serial_number="NEW001").one()
        assert not terminal.active and terminal.enrollment_status == "pending"
        event = db.query(models.TerminalEvent).one()
        assert event.processing_status == "terminal_disabled"
        assert db.query(models.TimeEntry).count() == 0


def test_offline_batch_uses_event_time_and_duplicate_is_idempotent(env):
    client, session = env
    from app import models
    with session() as db:
        user = _user(db)
        terminal = _terminal(db)
        _map(db, terminal, user)
    body = b"17\t2026-09-07 12:00:00\t0\t4\t\n17\t2026-09-07 08:00:00\t0\t4\t"
    assert client.post("/iclock/cdata?SN=SC-A&table=ATTLOG", content=body).status_code == 200
    assert client.post("/iclock/cdata?SN=SC-A&table=ATTLOG", content=body).status_code == 200
    with session() as db:
        entries = db.query(models.TimeEntry).all()
        assert len(entries) == 1
        assert entries[0].start_time.strftime("%H:%M") == "08:00"
        assert entries[0].end_time.strftime("%H:%M") == "12:00"
        assert entries[0].source == "terminal"
        assert db.query(models.TerminalEvent).count() == 2


def test_user_states_cards_and_multiple_terminals(env):
    _, session = env
    from app import models, terminal_service
    from app.integrations.terminals.zkteco_sc800 import AttendanceEvent
    with session() as db:
        active = _user(db, "active")
        inactive = _user(db, "inactive", False)
        first = _terminal(db, "SC-1")
        second = _terminal(db, "SC-2")
        disabled = _terminal(db, "SC-OFF", False)
        _map(db, first, active, "11", "CARD-1")
        _map(db, second, active, "22")
        _map(db, disabled, active, "33")
        _map(db, first, inactive, "44")
        card_event = AttendanceEvent("unknown", datetime(2026, 9, 8, 8), card_identifier="CARD-1")
        assert terminal_service.ingest(db, first, card_event)[0].processing_status == "processed"
        assert terminal_service.ingest(db, second, AttendanceEvent("22", datetime(2026, 9, 8, 12)))[0].processing_status == "processed"
        assert terminal_service.ingest(db, first, AttendanceEvent("missing", datetime(2026, 9, 9, 8)))[0].processing_status == "unknown_user"
        assert terminal_service.ingest(db, first, AttendanceEvent("44", datetime(2026, 9, 9, 9)))[0].processing_status == "inactive_user"
        assert terminal_service.ingest(db, disabled, AttendanceEvent("33", datetime(2026, 9, 9, 10)))[0].processing_status == "terminal_disabled"
        unknown_card = AttendanceEvent("nobody", datetime(2026, 9, 9, 11), card_identifier="NO-CARD")
        assert terminal_service.ingest(db, first, unknown_card)[0].processing_status == "unknown_user"
