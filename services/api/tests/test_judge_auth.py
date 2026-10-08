"""Judge mode preserves session security and cannot select arbitrary users."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.modules.auth.models import AuthSession, User, UserArea
from conftest import sign_in
from work_order_helpers import headers as action_headers, seed_order


def test_judge_mode_defaults_to_disabled_with_no_configured_users():
    from app.core.config import Settings
    config = Settings(_env_file=None)
    assert config.judge_mode_enabled is False
    assert config.judge_cohort is None
    assert config.judge_master_user_id is None
    assert config.judge_worker_1_user_id is None
    assert config.judge_worker_2_user_id is None


def test_enabled_unconfigured_mode_returns_generic_503_without_database(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.db import get_db
    monkeypatch.setattr(settings, 'judge_mode_enabled', True)
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.get('/api/v1/auth/judge-profiles')
            assert response.status_code == 503
            assert response.json()['error']['code'] == 'configuration_error'
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def judges(database, monkeypatch):
    db = database['session']
    master, worker = database['master'], database['worker']
    master.login = 'judge-jury-2026-prepared-v2-master'
    worker.login = 'judge-jury-2026-prepared-v2-worker'
    database['area'].name = '[T18 СИНТЕТИКА] Участок судей jury-2026-prepared-v2'
    database['brigade'].name = '[T18 СИНТЕТИКА] Бригада судей jury-2026-prepared-v2'
    second = User(login='judge-jury-2026-prepared-v2-worker-2', display_name='Рабочий 2',
                  role='worker', password_hash=worker.password_hash,
                  brigade_id=worker.brigade_id, shift_id=worker.shift_id, is_active=True)
    db.add(second)
    db.flush()
    db.add(UserArea(user_id=second.id, area_id=database['area'].id))
    db.commit()
    for name, value in dict(judge_mode_enabled=True, judge_cohort='jury-2026',
                           judge_master_user_id=master.id, judge_worker_1_user_id=worker.id,
                           judge_worker_2_user_id=second.id).items():
        monkeypatch.setattr(settings, name, value, raising=False)
    return master, worker, second


def judge_login(client, profile, token=None, **headers):
    if token is None:
        token = client.get('/api/v1/auth/csrf').json()['csrf_token']
    return client.post('/api/v1/auth/judge-login', json={'profile': profile},
                       headers={'Origin': 'http://localhost:5173', 'X-CSRF-Token': token, **headers})


def test_disabled_mode_hides_endpoints_and_preserves_password_login(client, monkeypatch):
    monkeypatch.setattr(settings, 'judge_mode_enabled', False, raising=False)
    assert client.get('/api/v1/auth/judge-profiles').status_code == 404
    assert client.post('/api/v1/auth/judge-login', json={'role': 'admin'}).status_code == 404
    sign_in(client)


def test_profiles_are_fixed_public_labels_without_ids_or_credentials(client, judges):
    response = client.get('/api/v1/auth/judge-profiles')
    assert response.status_code == 200
    assert response.json() == {'profiles': [
        {'code': 'master', 'display_name': 'Мастер', 'role': 'master'},
        {'code': 'worker-1', 'display_name': 'Рабочий 1', 'role': 'worker'},
        {'code': 'worker-2', 'display_name': 'Рабочий 2', 'role': 'worker'},
    ]}
    assert response.headers['cache-control'] == 'no-store'


def test_profile_switch_revokes_old_session_and_logout_revokes_new(client, judges, database):
    first = judge_login(client, 'master')
    assert first.status_code == 200
    old_cookie = client.cookies.get('qosthub_session')
    second = judge_login(client, 'worker-2', first.json()['csrf_token'])
    assert second.status_code == 200
    assert second.json()['user']['id'] == str(judges[2].id)
    assert second.json()['csrf_token'] != first.json()['csrf_token']
    assert client.cookies.get('qosthub_session') != old_cookie
    assert list(database['session'].scalars(select(AuthSession.user_id))) == [judges[2].id]
    new_cookie = client.cookies.get('qosthub_session')
    client.cookies.set('qosthub_session', old_cookie, domain='localhost.local', path='/')
    assert client.get('/api/v1/auth/me').status_code == 401
    client.cookies.set('qosthub_session', new_cookie, domain='localhost.local', path='/')
    token = second.json()['csrf_token']
    assert client.post('/api/v1/auth/logout', headers={
        'Origin': 'http://localhost:5173', 'X-CSRF-Token': token}).status_code == 204
    assert client.get('/api/v1/auth/me').status_code == 401


@pytest.mark.parametrize('headers', [{'Origin': 'https://evil.example'}, {'X-CSRF-Token': 'wrong'}, {'Origin': ''}])
def test_judge_login_requires_origin_and_csrf(client, judges, headers):
    assert judge_login(client, 'worker-1', **headers).status_code == 403
    assert client.get('/api/v1/auth/me').status_code == 401


@pytest.mark.parametrize('body', [{'profile': 'admin'}, {'profile': str(uuid4())},
                                {'profile': 'master', 'user_id': str(uuid4())},
                                {'profile': 'master', 'password': 'secret'},
                                {'profile': 'master', 'role': 'admin'}])
def test_judge_login_rejects_arbitrary_identity(client, judges, body):
    token = client.get('/api/v1/auth/csrf').json()['csrf_token']
    response = client.post('/api/v1/auth/judge-login', json=body,
                           headers={'Origin': 'http://localhost:5173', 'X-CSRF-Token': token})
    assert response.status_code == 422
    assert client.get('/api/v1/auth/me').status_code == 401


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'inactive', 'role', 'cohort', 'area', 'extra_area', 'brigade'])
def test_unsafe_server_profile_configuration_fails_closed(client, judges, database, monkeypatch, damage):
    db = database['session']
    if damage == 'missing':
        monkeypatch.setattr(settings, 'judge_worker_2_user_id', uuid4())
    elif damage == 'duplicate':
        monkeypatch.setattr(settings, 'judge_worker_2_user_id', judges[1].id)
    elif damage == 'inactive':
        judges[2].is_active = False
    elif damage == 'role':
        judges[2].role = 'admin'
    elif damage == 'cohort':
        judges[2].login = 'judge-other-prepared-v2-worker-2'
    elif damage == 'brigade':
        judges[2].brigade_id = None
    else:
        if damage == 'area':
            db.query(UserArea).filter_by(user_id=judges[2].id).delete()
        db.add(UserArea(user_id=judges[2].id, area_id=database['other_area'].id))
    db.commit()
    assert client.get('/api/v1/auth/judge-profiles').status_code == 503
    assert judge_login(client, 'master').status_code == 503
    assert client.get('/api/v1/auth/me').status_code == 401


def test_judge_login_uses_existing_pair_rate_limit(client, judges):
    for _ in range(5):
        assert judge_login(client, 'worker-1').status_code == 200
    response = judge_login(client, 'worker-1')
    assert response.status_code == 429
    assert int(response.headers['retry-after']) > 0


def test_judge_group_rejects_unrelated_member_of_its_brigade(client, judges, database):
    database['outsider'].brigade_id = database['brigade'].id
    database['session'].commit()
    assert client.get('/api/v1/auth/judge-profiles').status_code == 503
    assert judge_login(client, 'worker-1').status_code == 503


def test_worker_2_cannot_mutate_worker_1_order_or_master_actions(client, judges, database):
    order = seed_order(database)
    response = judge_login(client, 'worker-2')
    assert response.status_code == 200
    token = response.json()['csrf_token']
    response = client.post(f'/api/v1/work-orders/{order["id"]}/actions',
                           json={'action': 'accept', 'expected_version': order['version']},
                           headers=action_headers(token))
    assert response.status_code in (403, 404)
