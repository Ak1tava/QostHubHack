"""Adding a second worker never resets judge data or expands existing access."""

from datetime import date
import os
import subprocess
import sys

import pytest
from sqlalchemy import func, select

from app.judge_demo import setup_judge_demo
from app.modules.auth.models import User, UserArea
from app.modules.work_orders.models import WorkOrder, WorkOrderEvent


def test_profiles_cli_help_does_not_require_database():
    env = dict(os.environ)
    env.pop('DATABASE_URL', None)
    env['PYTHONUTF8'] = '1'
    result = subprocess.run([sys.executable, '-m', 'app.judge_profiles', '--help'],
                            capture_output=True, env=env)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert b'--cohort' in result.stdout and b'--confirm-demo' in result.stdout


def prepare(database, tmp_path):
    setup_judge_demo(database['session'], cohort='jury-2026', as_of=date(2026, 10, 8),
                     master_password='judge-master-test-only', worker_password='judge-worker-test-only',
                     photo_root=tmp_path, scenario_set='prepared-v2')
    database['session'].commit()


def test_second_worker_is_idempotent_and_legacy_setup_remains_unchanged(database, tmp_path):
    prepare(database, tmp_path)
    from app.judge_profiles import prepare_judge_profiles
    db = database['session']
    users = list(db.scalars(select(User)))
    old = {u.id: (u.login, u.password_hash) for u in users}
    order = db.scalar(select(WorkOrder))
    order.description = 'Сохранённое действие судьи'
    db.commit()
    assignments = list(db.execute(select(WorkOrder.id, WorkOrder.assignee_id, WorkOrder.responsible_id)))
    event_count = db.scalar(select(func.count()).select_from(WorkOrderEvent))
    result, profiles = prepare_judge_profiles(db, cohort='jury-2026', worker_password='second-worker-test-only')
    db.commit()
    assert result == 'created'
    assert set(profiles) == {'master', 'worker-1', 'worker-2'}
    worker = db.get(User, profiles['worker-2'])
    assert worker.login == 'judge-jury-2026-prepared-v2-worker-2' and worker.role == 'worker'
    first = db.get(User, profiles['worker-1'])
    assert worker.id != first.id and worker.password_hash != first.password_hash
    assert worker.brigade_id == first.brigade_id and worker.shift_id == first.shift_id
    assert set(db.scalars(select(UserArea.area_id).where(UserArea.user_id == worker.id))) == set(
        db.scalars(select(UserArea.area_id).where(UserArea.user_id == first.id)))
    original_hash = worker.password_hash
    repeat, repeated = prepare_judge_profiles(db, cohort='jury-2026', worker_password='replacement-password')
    db.commit()
    assert repeat == 'unchanged' and repeated == profiles
    assert worker.password_hash == original_hash
    assert {u.id: (u.login, u.password_hash) for u in users} == old
    assert list(db.execute(select(WorkOrder.id, WorkOrder.assignee_id, WorkOrder.responsible_id))) == assignments
    assert db.scalar(select(func.count()).select_from(WorkOrderEvent)) == event_count
    assert order.description == 'Сохранённое действие судьи'
    assert setup_judge_demo(db, cohort='jury-2026', as_of=date(2026, 10, 8),
                           master_password='new-master-password', worker_password='new-worker-password',
                           photo_root=tmp_path, scenario_set='prepared-v2') == 'unchanged'


def test_profiles_preparation_refuses_unprepared_group(database):
    from app.judge_profiles import prepare_judge_profiles
    with pytest.raises(ValueError):
        prepare_judge_profiles(database['session'], cohort='jury-2026', worker_password='second-worker-test-only')


@pytest.mark.parametrize('damage', ['wrong_role', 'extra_area', 'inactive'])
def test_repeat_refuses_altered_access_without_repair(database, tmp_path, damage):
    prepare(database, tmp_path)
    from app.judge_profiles import prepare_judge_profiles
    db = database['session']
    _, profiles = prepare_judge_profiles(db, cohort='jury-2026', worker_password='second-worker-test-only')
    db.commit()
    user = db.get(User, profiles['worker-2'])
    if damage == 'wrong_role':
        user.role = 'admin'
    elif damage == 'inactive':
        user.is_active = False
    else:
        db.add(UserArea(user_id=user.id, area_id=database['other_area'].id))
    db.commit()
    old_hash = user.password_hash
    with pytest.raises(ValueError):
        prepare_judge_profiles(db, cohort='jury-2026', worker_password='replacement-password')
    db.rollback()
    assert user.password_hash == old_hash
    assert not user.is_active if damage == 'inactive' else user.role == ('admin' if damage == 'wrong_role' else 'worker')
