"""All features work without activation; old licences do not affect upgrades."""
import json
import zipfile
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from test_v0209 import client, _fresh_app, _login, _csrf
from test_v0210 import event, send


@pytest.fixture(params=['absent', 'invalid', 'expired-blocked'])
def main(request, tmp_path, monkeypatch):
    config = tmp_path / 'config'
    config.mkdir()
    if request.param != 'absent':
        contents = 'not-json' if request.param == 'invalid' else json.dumps({
            'server_url': 'https://unused.invalid',
            'activation_key': 'OLD-KEY-MUST-NOT-BE-USED',
            'blocked_at': '2000-01-01T00:00:00Z', 'blocked_reason': 'revoked',
            'document': {'features': [], 'max_users': 1, 'expires_at': '2000-01-01'},
        })
        (config / 'license.json').write_text(contents)
    (config / 'logging.json').write_text(json.dumps({'level': 'WARNING', 'license_logging': True}))
    # Invalid retired settings must not interfere with startup either.
    monkeypatch.setenv('ERFASSUNG_LICENSE_CHECK_MINUTES', 'invalid-old-setting')
    monkeypatch.setenv('ERFASSUNG_LICENSE_PUBLIC_KEYS', 'invalid-old-setting')
    return _fresh_app(tmp_path, monkeypatch)


def test_features_and_navigation_work_without_activation(client):
    _login(client)
    from app import logging_setup, paths, app_config

    for path in ('/dashboard', '/mobile', '/records/vacations',
                 '/records/vacations/calendar', '/admin/companies',
                 '/admin/reports/time', '/admin/reports/users', '/admin/terminals'):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, (path, response.text)
        assert '/admin/system/license' not in response.text
        assert 'license-banner' not in response.text
    for path in ('/api/users/1/excel',):
        assert client.get(path).status_code == 200, path
    assert 'Kalender abonnieren' in client.get('/records/vacations/calendar').text
    assert 'license' not in logging_setup.CHANNELS
    assert not (paths.LOGS_DIR / 'license.log').exists()
    settings = app_config.load_logging_config()
    assert settings.level == 'WARNING'
    assert 'license_logging' not in settings.to_dict()
    for path in ('/admin/system/license', '/api/license'):
        assert client.get(path).status_code == 404
    token = _csrf(client, '/admin/system/settings')
    for action in ('activate', 'refresh', 'recheck', 'deactivate'):
        assert client.post(f'/admin/system/license/{action}', data={'csrf_token': token}).status_code == 404


def test_user_creation_has_no_license_limit_and_still_requires_permission(client):
    from app import crud, database, models

    _login(client)
    token = _csrf(client, '/admin/users/new')
    response = client.post('/admin/users/create', data={
        'csrf_token': token, 'username': 'web-user', 'full_name': 'Web User',
        'email': 'web@example.com', 'password': 'Worker!0000', 'password_confirm': 'Worker!0000',
        'standard_weekly_hours': '40', 'annual_vacation_days': '30',
    }, follow_redirects=False)
    assert response.status_code == 303, response.text
    with database.SessionLocal() as db:
        assert crud.get_user_by_username(db, 'web-user') is not None, response.headers
    payload = {'username': 'api-user', 'full_name': 'API User',
               'email': 'api@example.com', 'password': 'Worker!0000'}
    response = client.post('/api/users', json=payload, headers={'X-CSRF-Token': token})
    assert response.status_code == 200, response.text
    with database.SessionLocal() as db:
        worker = crud.get_user_by_username(db, 'api-user')
        worker.roles = []
        worker.must_change_password = False
        db.commit()
    client.cookies.clear()
    _login(client, 'api-user', 'Worker!0000')
    token = _csrf(client, '/dashboard')
    payload['username'] = 'forbidden'
    response = client.post('/api/users', json=payload, headers={'X-CSRF-Token': token})
    assert response.status_code == 403
    assert client.get('/api/users/1/excel').status_code == 403
    assert client.get('/admin/terminals', follow_redirects=False).status_code == 303
    assert client.get('/admin/companies', follow_redirects=False).status_code == 303
    with database.SessionLocal() as db:
        assert db.query(models.User).filter_by(username='forbidden').first() is None


def test_mobile_orders_locations_vacations_and_calendar_are_available(client):
    from app import crud, database, models, schemas

    _login(client)
    with database.SessionLocal() as db:
        company = crud.create_company(db, schemas.CompanyCreate(name='Auftrag ohne Aktivierung'))
        location = crud.create_company_location(db, company.id, schemas.CompanyLocationCreate(name='Standort'))
        company_id, location_id = company.id, location.id
        db.add(models.VacationRequest(user_id=1, start_date=date(date.today().year, 7, 6), end_date=date(date.today().year, 7, 7),
                                     status=models.VacationStatus.APPROVED, absence_type_key='vacation'))
        db.commit()
    snapshot = client.get('/mobile/sync-data').json()
    assert any(c['id'] == company_id for c in snapshot['companies'])
    assert any(loc['id'] == location_id for loc in snapshot['locations'])
    assert snapshot['vacations'] and snapshot['metrics']['vacation_summary']
    assert snapshot['permissions']['request_vacations'] is True
    action = event(client, 'start_company', company_id=str(company_id), work_location=str(location_id))
    receipt = send(client, action).json()
    assert receipt['status'] == 'applied', receipt
    assert send(client, action).json()['duplicate'] is True
    with database.SessionLocal() as db:
        entry = db.query(models.TimeEntry).filter_by(company_id=company_id).one()
        assert entry.location_id == location_id
    token = _csrf(client, '/records/vacations/calendar')
    response = client.post('/records/vacations/calendar/feed', data={'csrf_token': token, 'scope': 'self'}, follow_redirects=False)
    feed_url = parse_qs(urlparse(response.headers['location']).query)['feed_url'][0]
    feed = client.get(feed_url)
    assert feed.status_code == 200 and 'UID:absence-' in feed.text


def test_restore_legacy_backup_ignores_license_but_preserves_business_data(client, tmp_path):
    from app import backup_manager, database, models, paths, restore_manager

    original = backup_manager.create_safety_backup(prefix='legacy-license')
    archive_path = tmp_path / 'legacy.zip'
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(archive_path, 'w') as target:
        for member in source.infolist():
            if member.filename != 'config/license.json':
                target.writestr(member, source.read(member.filename))
        target.writestr('config/license.json', '{"activation_key":"ARCHIVED-KEY"}')
    license_path = paths.CONFIG_DIR / 'license.json'
    before = license_path.read_bytes() if license_path.exists() else None
    result = restore_manager.perform_restore(archive_path, username='test', token='license-removal')
    assert result['status'] == 'success', result['message']
    assert result['safety_backup']
    assert (license_path.read_bytes() if license_path.exists() else None) == before
    with database.SessionLocal() as db:
        assert db.query(models.User).filter_by(username='admin').one()
