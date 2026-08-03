"""Regressionstests für die Oberflächenkorrekturen in Version 0.20.6."""
import re
import sys
import pytest
import licensed_env

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ERFASSUNG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ERFASSUNG_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ERFASSUNG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/erfassung.db")
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ERFASSUNG_DISABLE_SCHEDULER", "1")
    for name in [name for name in sys.modules if name.startswith("app")]: del sys.modules[name]
    import app.main as main
    licensed_env.activate()
    from app import crud, database, security
    from fastapi.testclient import TestClient
    with TestClient(main.app) as test_client:
        db = database.SessionLocal(); admin = crud.get_user_by_username(db, "admin")
        admin.password_hash = security.hash_password("Admin!0000"); admin.must_change_password = False; db.commit(); db.close()
        token = re.search(r'name="csrf_token" value="([^"]+)"', test_client.get("/login").text).group(1)
        test_client.post("/login", data={"username":"admin", "password":"Admin!0000", "csrf_token":token})
        test_client.main = main; test_client.db = database.SessionLocal()
        yield test_client
        test_client.db.close()


def test_calendar_tabs_and_month_change(client):
    page = client.get("/records/vacations/calendar?scope=self&view=month&month=2026-08")
    assert page.status_code == 200
    tabs = re.search(r'<nav class="vacation-tabs".*?</nav>', page.text, re.S).group(0)
    assert tabs.count('is-active') == 1
    assert 'class="is-active" aria-current="page" href="/records/vacations/calendar?scope=self"' in tabs
    assert "this.form.submit()" in page.text
    assert "August 2026" in page.text


def test_week_uses_selected_month_and_keeps_it_in_navigation(client):
    page = client.get("/records/vacations/calendar?scope=self&view=week&month=2026-08")
    assert page.status_code == 200
    assert "Woche 31" in page.text
    assert "view=week&month=2026-08&anchor=" in page.text


def test_work_schedules_are_in_accessible_modal(client):
    user = client.main.crud.get_user_by_username(client.db, "admin")
    page = client.get(f"/admin/users/{user.id}")
    assert page.status_code == 200
    assert 'id="work-schedules-modal"' in page.text and 'role="dialog" aria-modal="true"' in page.text
    assert 'name="valid_from"' in page.text and 'id="work-schedules-open"' in page.text
    assert "event.key === 'Escape'" in page.text
    assert "trigger.focus()" in page.text


def test_deactivation_is_structured(client):
    user = client.main.crud.get_user_by_username(client.db, "admin")
    page = client.get(f"/admin/users/{user.id}")
    assert "Folgen der Deaktivierung" in page.text
    assert "Administrativ deaktiviert" in page.text
    assert "Arbeitszeiten und gesetzliche Nachweisdaten bleiben vollständig erhalten" in page.text
