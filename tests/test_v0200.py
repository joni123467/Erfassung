"""Regressionstests 0.20.0 – Jahres-Sonntage und Nachtarbeit."""
from __future__ import annotations

import sys
import re
from datetime import date, time

import pytest

import licensed_env


@pytest.fixture()
def main(tmp_path, monkeypatch):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    for key in ("DB_TYPE", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER",
                "DB_PASSWORD", "DB_SSL", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    for name in [name for name in sys.modules if name.startswith("app")]:
        del sys.modules[name]
    import app.main as module
    licensed_env.activate()
    from fastapi.testclient import TestClient
    with TestClient(module.app):
        pass
    return module


def _admin(main):
    from app import crud, database
    with database.SessionLocal() as db:
        return crud.get_user_by_username(db, "admin").id


def _entry(main, day, start, end):
    from app import database, models
    with database.SessionLocal() as db:
        row = models.TimeEntry(
            user_id=_admin(main), work_date=day, start_time=start, end_time=end,
            status=models.TimeEntryStatus.APPROVED, break_minutes=0,
            break_rule=models.BreakRule.ACTUAL, tz_name="Europe/Berlin",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def test_version(main):
    assert main.APP_VERSION == "0.20.3"


def test_night_work_over_eight_hours_is_flagged(main):
    from app import compliance, database, models
    day = date(2026, 1, 5)
    _entry(main, day, time(21, 0), time(6, 0))
    with database.SessionLocal() as db:
        findings = compliance.evaluate_day(db, _admin(main), day)
    finding = next(item for item in findings
                   if item["code"] == compliance.NIGHT_WORK_OVER_8H)
    assert "23:00–06:00" in finding["detail"]
    assert finding["severity"] == compliance.SEVERITY_WARNING


def test_short_evening_work_is_not_night_work(main):
    from app import compliance, database, models
    day = date(2026, 1, 6)
    _entry(main, day, time(14, 0), time(22, 30))
    with database.SessionLocal() as db:
        codes = {item["code"] for item in compliance.evaluate_day(db, _admin(main), day)}
    assert compliance.NIGHT_WORK_OVER_8H not in codes


def test_annual_report_counts_free_and_worked_sundays(main):
    from app import compliance, database
    _entry(main, date(2026, 1, 4), time(9, 0), time(10, 0))
    with database.SessionLocal() as db:
        report = compliance.annual_compliance_report(
            db, _admin(main), 2026, reference_date=date(2026, 1, 11)
        )
    assert report["worked_sundays"] == 1
    assert report["free_sundays"] == 1
    assert report["required_free_sundays"] == 15


def test_saturday_night_counts_as_sunday_work(main):
    from app import compliance, database
    _entry(main, date(2026, 1, 3), time(23, 0), time(2, 0))
    with database.SessionLocal() as db:
        report = compliance.annual_compliance_report(
            db, _admin(main), 2026, reference_date=date(2026, 1, 4)
        )
    assert report["worked_sundays"] == 1
    assert report["free_sundays"] == 0


def test_too_few_free_sundays_creates_annual_finding(main):
    """Seit 0.20.2 setzt ein Verstoß einen bekannten Beschäftigungsbeginn voraus.

    Ohne Eintrittsdatum lässt sich nicht sagen, welche Sonntage überhaupt in
    das Beschäftigungsverhältnis fallen – dann behauptet die Anwendung weder
    einen Verstoß noch die Einhaltung. Der Test hinterlegt deshalb einen
    Beginn; geprüft wird weiterhin die revisionssichere Feststellung.
    """
    from app import compliance, database, models
    with database.SessionLocal() as db:
        person = db.query(models.User).filter(
            models.User.id == _admin(main)
        ).first()
        person.employment_start_date = date(2026, 1, 1)
        db.commit()
    # Im Gesamtjahr an 40 Sonntagen arbeiten: höchstens 12 bleiben frei.
    sundays = compliance._sundays_between(date(2026, 1, 1), date(2026, 12, 31))
    for day in sundays[:40]:
        _entry(main, day, time(9, 0), time(10, 0))
    with database.SessionLocal() as db:
        reports = compliance.refresh_annual_compliance(
            db, reference_date=date(2026, 12, 31), user_ids=[_admin(main)]
        )
        flag = db.query(models.ComplianceFlag).filter(
            models.ComplianceFlag.code == compliance.FREE_SUNDAYS_UNDER_15
        ).one()
    assert reports[0]["sunday_rule_impossible"] is True
    assert flag.state == models.ComplianceState.DETECTED
    assert flag.severity == compliance.SEVERITY_CRITICAL


def test_annual_finding_needs_a_known_employment_start(main):
    """Ohne Eintrittsdatum entsteht keine Feststellung (ab 0.20.2)."""
    from app import compliance, database, models
    sundays = compliance._sundays_between(date(2026, 1, 1), date(2026, 12, 31))
    for day in sundays[:40]:
        _entry(main, day, time(9, 0), time(10, 0))
    with database.SessionLocal() as db:
        reports = compliance.refresh_annual_compliance(
            db, reference_date=date(2026, 12, 31), user_ids=[_admin(main)]
        )
        assert db.query(models.ComplianceFlag).filter(
            models.ComplianceFlag.code == compliance.FREE_SUNDAYS_UNDER_15
        ).count() == 0
    assert reports[0]["employment_period_known"] is False
    assert reports[0]["sunday_rule_impossible"] is False
    assert reports[0]["sunday_rule_met"] is False


def test_compliance_page_contains_annual_overview(main):
    from fastapi.testclient import TestClient
    from app import database, security, crud
    with database.SessionLocal() as db:
        admin = crud.get_user_by_username(db, "admin")
        admin.password_hash = security.hash_password("Admin!0000")
        db.commit()
    with TestClient(main.app) as client:
        login_page = client.get("/login").text
        token = re.search(r'name="csrf_token" value="([^"]+)"', login_page).group(1)
        client.post("/login", data={"username": "admin", "password": "Admin!0000",
                                    "csrf_token": token})
        html = client.get("/admin/compliance").text
    assert "Jahresprüfung Sonn- und Nachtarbeit" in html
    assert "Freie Sonntage" in html
    assert "Nachtarbeitstage" in html
