"""Outbox receipts: no acknowledged loss, atomic effects, review and migration."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from test_v0209 import client, main, _login, _csrf  # existing isolated fixture


def event(client, action='start_work', ident='offline-1', days=7, **extra):
    session = client.get('/api/mobile/session').json()
    payload = {'action': action, 'event_time': (datetime.now(timezone.utc)-timedelta(days=days)).isoformat(), **extra}
    return dict(protocol=1, owner_id=session['user']['id'], client_action_id=ident, kind='punch', payload=payload)


def send(client, payload):
    token = client.get('/api/mobile/session').json()['csrf_token']
    return client.post('/api/mobile/actions', json=payload, headers={'X-CSRF-Token': token})


def test_seven_days_offline_and_duplicate(client):
    _login(client)
    first = event(client)
    a = send(client, first)
    assert a.status_code == 200, a.text
    assert a.json()['status'] == 'applied', a.text
    assert send(client, first).json()['duplicate'] is True
    stop = event(client, 'end_work', 'offline-2')
    stop['payload']['event_time'] = (datetime.fromisoformat(first['payload']['event_time'])+timedelta(hours=8)).isoformat()
    assert send(client, stop).json()['status'] == 'applied'
    from app import database, models
    with database.SessionLocal() as db:
        entries = db.query(models.TimeEntry).all()
        assert len(entries) == 1 and not entries[0].is_open
        assert entries[0].started_at_utc.date() == datetime.fromisoformat(first['payload']['event_time']).date()
        assert db.query(models.MobileSyncReceipt).count() == 2


def test_same_id_different_payload_is_never_acknowledged(client):
    _login(client)
    data=event(client)
    assert send(client,data).json()['status']=='applied'
    data['payload']['action']='end_work'
    assert send(client,data).status_code==409


def test_parallel_delivery_has_one_effect(client):
    _login(client)
    data=event(client)
    token=client.get('/api/mobile/session').json()['csrf_token']
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies=list(pool.map(lambda _: client.post('/api/mobile/actions',json=data,headers={'X-CSRF-Token':token}),range(4)))
    assert all(r.status_code==200 and r.json()['status']=='applied' for r in replies), [r.text for r in replies]
    from app import database,models
    with database.SessionLocal() as db:
        assert db.query(models.TimeEntry).count()==1
        assert db.query(models.MobileSyncReceipt).count()==1


def test_conflict_survives_retry_and_can_be_rejected(client):
    _login(client)
    data=event(client,'end_work')
    reply=send(client,data).json()
    assert reply['status']=='conflict'
    assert send(client,data).json()['receipt_id']==reply['receipt_id']
    response=client.get('/admin/sync-conflicts')
    assert response.status_code==200 and 'Keine laufende Arbeitszeit' in response.text
    result=client.post(f"/admin/sync-conflicts/{reply['receipt_id']}",data={'decision':'reject','reason':'Auf anderem Gerät bereits erfasst','csrf_token':_csrf(client,'/admin/sync-conflicts')},follow_redirects=False)
    assert result.status_code==303
    resolved=send(client,data).json()
    assert resolved['status']=='rejected' and resolved['resolution_note']=='Auf anderem Gerät bereits erfasst'
    from app import database,models,paths
    with database.SessionLocal() as db:
        row=db.get(models.MobileSyncReceipt,reply['receipt_id'])
        assert json.loads(row.payload_json)==data['payload']
        assert row.resolved_by_id and row.resolved_at
    assert 'Synchronisationskonflikt entschieden' in (paths.LOGS_DIR/'audit.log').read_text()


def test_conflict_can_be_applied_after_prerequisite_arrives(client):
    _login(client)
    start=event(client)
    end=event(client,'end_work','offline-end')
    end['payload']['event_time']=(datetime.fromisoformat(start['payload']['event_time'])+timedelta(hours=2)).isoformat()
    conflict=send(client,end).json()
    assert conflict['status']=='conflict'
    assert send(client,start).json()['status']=='applied'
    response=client.post(f"/admin/sync-conflicts/{conflict['receipt_id']}",data={'decision':'retry','reason':'Fehlender Start wurde nachgeliefert','csrf_token':_csrf(client,'/admin/sync-conflicts')},follow_redirects=False)
    assert response.status_code==303
    assert send(client,end).json()['status']=='applied'


def test_failure_after_business_commit_rolls_back_everything(client, monkeypatch):
    _login(client)
    from app import database,models,crud
    original=crud.create_mobile_sync_action
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('Crash before acknowledgement')
    monkeypatch.setattr(crud,'create_mobile_sync_action',fail)
    with pytest.raises(RuntimeError,match='Crash before acknowledgement'):
        send(client,event(client))
    with database.SessionLocal() as db:
        assert db.query(models.TimeEntry).count()==0
        assert db.query(models.MobileSyncAction).count()==0
        assert db.query(models.MobileSyncReceipt).count()==0


def test_changed_account_and_expired_session(client):
    _login(client)
    data=event(client)
    data['owner_id']+=1
    assert send(client,data).status_code==403
    client.get('/logout')
    assert client.get('/api/mobile/session').status_code==401


def test_new_permission_is_separate_and_scoped(client):
    _login(client)
    from app import database,crud,models,permission_service
    with database.SessionLocal() as db:
        user=crud.get_user_by_username(db,'admin')
        role=crud.create_role(db,name='Nur Nachträge',permissions={'Time.Approve':'all'})
        user.roles=[role]; db.commit()
        assert not permission_service.has(user,'Time.Sync.Resolve')
    assert client.get('/admin/sync-conflicts').status_code==403
    with database.SessionLocal() as db:
        role=crud.get_role_by_name(db,'Nur Nachträge')
        crud._apply_role_permissions(db,role,{'Time.Sync.Resolve':'self'}); db.commit()
    assert client.get('/admin/sync-conflicts').status_code==200


def test_old_success_marker_is_recognised(client):
    _login(client)
    data=event(client)
    response=client.post('/punch', data={**data['payload'],'client_action_id':data['client_action_id'],'csrf_token':_csrf(client,'/mobile')},headers={'Accept':'application/json'})
    assert response.json()['ok']
    assert send(client,data).json()['status']=='applied'
    from app import database,models
    with database.SessionLocal() as db:
        assert db.query(models.TimeEntry).count()==1


def test_migration_is_additive_and_repeatable(main):
    from app import database,db_migrations,models
    with database.engine.begin() as connection:
        connection.execute(text('DROP TABLE mobile_sync_receipts'))
    db_migrations._add_mobile_sync_receipts(database.engine)
    db_migrations._add_mobile_sync_receipts(database.engine)
    with database.SessionLocal() as db:
        assert db.query(models.User).count()>0
        assert db.query(models.MobileSyncReceipt).count()==0


def test_legacy_rejection_is_saved_even_if_old_client_discards_its_queue(client):
    _login(client)
    data=event(client,'end_work','legacy-conflict')
    response=client.post('/punch',data={**data['payload'],'client_action_id':data['client_action_id'],'csrf_token':_csrf(client,'/mobile')},headers={'Accept':'application/json'})
    assert response.json()['retryable'] is True
    from app import database,models
    with database.SessionLocal() as db:
        row=db.query(models.MobileSyncReceipt).filter_by(client_action_id='legacy-conflict').one()
        assert row.status=='conflict'
    # A migrated client receives that very receipt, not a new/duplicate booking.
    migrated=send(client,data)
    assert migrated.status_code==200, migrated.text
    assert migrated.json()['status']=='conflict'


def test_failed_order_switch_rolls_back_its_already_closed_work(client,monkeypatch):
    _login(client)
    start=event(client)
    assert send(client,start).json()['status']=='applied'
    from app import database,models,crud,schemas
    with database.SessionLocal() as db:
        company=crud.create_company(db,schemas.CompanyCreate(name='Kunde'))
        company_id=company.id
    def reject(*args,**kwargs):
        raise ValueError('OVERLAPPING_TIME_ENTRY')
    monkeypatch.setattr(crud,'start_running_entry',reject)
    switch=event(client,'start_company','switch',company_id=str(company_id))
    switch['payload']['event_time']=(datetime.fromisoformat(start['payload']['event_time'])+timedelta(hours=1)).isoformat()
    assert send(client,switch).json()['status']=='conflict'
    with database.SessionLocal() as db:
        assert db.query(models.TimeEntry).one().is_open is True
        assert db.query(models.MobileSyncAction).count()==1


def test_summer_time_offsets_remain_distinct(client):
    _login(client)
    start=event(client)
    start['payload']['event_time']='2026-10-25T02:30:00+02:00'
    end=event(client,'end_work','dst-end')
    end['payload']['event_time']='2026-10-25T02:45:00+01:00'
    assert send(client,start).json()['status']=='applied'
    assert send(client,end).json()['status']=='applied'
    from app import database,models
    with database.SessionLocal() as db:
        row=db.query(models.TimeEntry).one()
        assert (row.ended_at_utc-row.started_at_utc).total_seconds()==75*60


def test_new_permission_scope_cannot_resolve_another_user(client):
    _login(client)
    from app import database,models,crud,schemas
    with database.SessionLocal() as db:
        other=crud.create_user(db,schemas.UserCreate(username='other',full_name='Andere Person',email='other@example.com',password='Other!12345'))
        row=models.MobileSyncReceipt(user_id=other.id,client_action_id='other-event',kind='punch',payload_json='{}',payload_hash='0'*64,status='conflict',message='Andere Person')
        db.add(row);db.commit();receipt_id=row.id
        role=crud.create_role(db,name='Eigene Konflikte',permissions={'Time.Sync.Resolve':'self'})
        crud.get_user_by_username(db,'admin').roles=[role];db.commit()
    response=client.get('/admin/sync-conflicts')
    assert response.status_code==200 and 'Andere Person' not in response.text
    response=client.post(f'/admin/sync-conflicts/{receipt_id}',data={'decision':'reject','reason':'Keine Berechtigung','csrf_token':client.get('/api/csrf').json()['csrf_token']})
    assert response.status_code==403
    with database.SessionLocal() as db:
        assert db.get(models.MobileSyncReceipt,receipt_id).status=='conflict'


def test_logical_backup_preserves_receipts_and_accepts_older_backups(client):
    _login(client)
    conflict=send(client,event(client,'end_work','backup-conflict')).json()
    from app import data_transfer,database,models
    backup=data_transfer.export_database(database.engine)
    assert len(backup['tables']['mobile_sync_receipts'])==1
    data_transfer.import_database(database.engine,backup)
    with database.SessionLocal() as db:
        assert db.get(models.MobileSyncReceipt,conflict['receipt_id']).status=='conflict'
    # Older formats contain no receipts; other business rows still restore.
    backup['tables'].pop('mobile_sync_receipts')
    data_transfer.import_database(database.engine,backup)
    with database.SessionLocal() as db:
        assert db.query(models.User).count()>0
        assert db.query(models.MobileSyncReceipt).count()==0
