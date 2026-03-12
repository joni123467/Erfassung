from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud, models, schemas
from app.database import get_db, Base
from app.main import app
from app.sync import apply_punch_operation


def build_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal


def seed_user(db):
    group = crud.create_group(db, schemas.GroupCreate(name="Admin", is_admin=True))
    user = crud.create_user(
        db,
        schemas.UserCreate(
            username="tester",
            full_name="Tester",
            email="tester@example.com",
            standard_weekly_hours=40,
            group_id=group.id,
            pin_code="1234",
        ),
    )
    company = crud.create_company(db, schemas.CompanyCreate(name="Firma A", description=""))
    return user, company


def test_apply_punch_operation_conflict_without_active_entry():
    Session = build_session()
    db = Session()
    user, _ = seed_user(db)

    result = apply_punch_operation(
        db,
        user,
        {"operation_id": "op-1", "payload": {"action": "end_work", "notes": ""}},
    )

    assert result.status == "conflict"


def test_apply_punch_operation_start_and_end():
    Session = build_session()
    db = Session()
    user, _ = seed_user(db)

    start = apply_punch_operation(
        db,
        user,
        {"operation_id": "op-start", "payload": {"action": "start_work", "notes": "Offline"}},
    )
    end = apply_punch_operation(
        db,
        user,
        {"operation_id": "op-end", "payload": {"action": "end_work", "notes": ""}},
    )

    assert start.status == "synced"
    assert end.status == "synced"


def test_mobile_sync_idempotent_requests():
    Session = build_session()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    db = Session()
    seed_user(db)
    db.close()

    login = client.post('/login', data={'pin_code': '1234'}, follow_redirects=False)
    assert login.status_code == 303

    payload = {
        'operations': [
            {
                'operation_id': 'repeat-1',
                'type': 'punch',
                'created_at': datetime.utcnow().isoformat(),
                'payload': {'action': 'start_work', 'notes': 'A'},
            }
        ]
    }

    first = client.post('/api/mobile/sync', json=payload)
    second = client.post('/api/mobile/sync', json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    first_result = first.json()['results'][0]
    second_result = second.json()['results'][0]
    assert first_result['operation_id'] == second_result['operation_id']

    app.dependency_overrides.clear()


def test_api_ping_no_cache_headers():
    Session = build_session()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get('/api/ping')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'
    assert 'no-store' in response.headers.get('cache-control', '')

    app.dependency_overrides.clear()
