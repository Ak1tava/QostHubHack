"""QR card permissions and history against real PostgreSQL."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from conftest import sign_in
from work_order_helpers import add_user, seed_order
from app.core.config import settings
from app.modules.catalog.models import Equipment


def endpoint(database):
    return f"/api/v1/equipment/{database['equipment'].id}"


def test_equipment_requires_login(client, database):
    assert client.get(endpoint(database)).status_code == 401


@pytest.mark.parametrize('role', ['worker', 'master', 'manager', 'admin'])
def test_equipment_existing_fields_and_canonical_https(client, database, monkeypatch, role):
    if role in {'manager', 'admin'}:
        add_user(database, login=role, role=role)
    sign_in(client, role)
    monkeypatch.setattr(settings, 'public_base_url', 'https://plant.example/')
    r = client.get(endpoint(database), headers={'X-Forwarded-Host': 'attacker.example'})
    assert r.status_code == 200
    assert r.json() == {
        'id': str(database['equipment'].id), 'name': 'Насос',
        'area_id': str(database['area'].id),
        'area': {'id': str(database['area'].id), 'name': 'Первый участок'},
        'public_url': f"https://plant.example/equipment/{database['equipment'].id}",
        'timezone': settings.app_timezone, 'recent_work_orders': [],
    }
    assert r.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('role', ['worker', 'master', 'manager', 'admin'])
def test_foreign_and_missing_equipment_are_indistinguishable(client, database, role):
    if role in {'manager', 'admin'}:
        add_user(database, login=role, role=role)
    sign_in(client, role)
    other = database['session'].scalar(select(Equipment).where(Equipment.area_id == database['other_area'].id))
    foreign = client.get(f'/api/v1/equipment/{other.id}')
    missing = client.get(f'/api/v1/equipment/{uuid4()}')
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_history_filters_assignment_before_limit_and_keeps_brigade_orders(client, database):
    other = add_user(database)
    now = datetime.now(timezone.utc)
    own = [seed_order(database, created_at=now - timedelta(days=2, minutes=i)) for i in range(12)]
    brigade = seed_order(database, assignee_id=None, brigade_id=database['brigade'].id,
                         responsible_id=other.id, created_at=now - timedelta(days=1))
    hidden = [seed_order(database, assignee_id=other.id, created_at=now + timedelta(minutes=i)) for i in range(15)]
    sign_in(client)
    r = client.get(endpoint(database))
    assert r.status_code == 200
    items = r.json()['recent_work_orders']
    assert [i['id'] for i in items] == [brigade['id']] + [o['id'] for o in own[:9]]
    assert not {o['id'] for o in hidden}.intersection(i['id'] for i in items)
    for item in items:
        assert item['detail_url'] == f"/orders/{item['id']}"
        assert client.get(f"/api/v1/work-orders/{item['id']}").status_code == 200
    assert client.get(f"/api/v1/work-orders/{hidden[0]['id']}").status_code == 404


def test_master_history_equipment_filter_stable_order_and_summary(client, database):
    now = datetime.now(timezone.utc)
    second = Equipment(name='Другой насос', area_id=database['area'].id)
    database['session'].add(second); database['session'].commit()
    seed_order(database, equipment_id=second.id, description='Не это оборудование', created_at=now + timedelta(days=1))
    for i in reversed(range(1, 13)):
        seed_order(database, id=UUID(int=i), created_at=now, description='Работа ' + 'я' * 300)
    sign_in(client, 'master')
    r = client.get(endpoint(database))
    assert r.status_code == 200
    items = r.json()['recent_work_orders']
    assert [i['id'] for i in items] == [str(UUID(int=i)) for i in range(1, 11)]
    assert all(len(i['description']) <= 240 and i['status'] == 'ISSUED' and i['number'] for i in items)


@pytest.mark.parametrize('origin', ['http://localhost:5173', 'https://user:secret@plant.example',
                                    'https://plant.example/?secret=value', 'https://plant.example/path'])
def test_noncanonical_configuration_does_not_generate_misleading_qr(client, database, monkeypatch, origin):
    sign_in(client)
    monkeypatch.setattr(settings, 'public_base_url', origin)
    r = client.get(endpoint(database))
    assert r.status_code == 200
    assert r.json()['public_url'] is None
