"""Add worker 2 to an existing prepared group, without reseeding or resetting it."""

import argparse
from getpass import getpass
from uuid import uuid5

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_engine
from app.core.security import hash_password
from app.judge_demo import NAMESPACE
from app.modules.auth.judges import prepared_cohort, validate_profiles
from app.modules.auth.models import User, UserArea
from app.modules.work_orders.models import AIReview, WorkOrder, Submission
from app.seed_demo import validate_target


def prepare_judge_profiles(db: Session, *, cohort: str, worker_password: str | None = None):
    """Caller commits. Reject altered accounts; never repair access or reset data."""
    validate_target(db.get_bind().url.render_as_string(hide_password=False))
    group = prepared_cohort(cohort)
    db.execute(text('SELECT pg_advisory_xact_lock(718018)'))
    logins = {'master': f'judge-{group}-master', 'worker-1': f'judge-{group}-worker',
              'worker-2': f'judge-{group}-worker-2'}
    users = {u.login: u for u in db.scalars(select(User).where(User.login.in_(logins.values())))}
    if any(logins[code] not in users for code in ('master', 'worker-1')):
        raise ValueError('Сначала подготовьте существующую группу prepared-v2')
    ids = {code: users[login].id for code, login in logins.items() if login in users}
    profiles = validate_profiles(db, cohort, ids)
    prepared = db.scalar(select(AIReview.id).join(Submission, Submission.id == AIReview.submission_id)
                         .join(WorkOrder, WorkOrder.id == Submission.work_order_id)
                         .where(WorkOrder.master_id == ids['master'],
                                AIReview.model == 't18-prepared-demo-provider-v2').limit(1))
    if not prepared:
        raise ValueError('Группа prepared-v2 не подготовлена')
    second_id = uuid5(NAMESPACE, f'judge-profile:{group}:worker-2')
    if 'worker-2' in ids:
        if ids['worker-2'] != second_id:
            raise ValueError('Коллизия существующего аккаунта; ничего не изменено')
        return 'unchanged', ids
    if db.get(User, second_id) is not None:
        raise ValueError('Коллизия существующего аккаунта; ничего не изменено')
    if not worker_password or not 12 <= len(worker_password) <= 128:
        raise ValueError('Пароль второго рабочего: 12–128 символов')
    first = profiles['worker-1']
    user = User(id=second_id, login=logins['worker-2'], display_name='Рабочий 2', role='worker',
                password_hash=hash_password(worker_password), specialty=first.specialty,
                grade=first.grade, brigade_id=first.brigade_id, shift_id=first.shift_id, is_active=True)
    db.add(user)
    db.flush()
    area_id = db.scalar(select(UserArea.area_id).where(UserArea.user_id == first.id))
    db.add(UserArea(user_id=user.id, area_id=area_id))
    db.flush()
    ids['worker-2'] = second_id
    validate_profiles(db, cohort, ids)
    return 'created', ids


def main():
    parser = argparse.ArgumentParser(description='Добавить второй профиль рабочего без сброса prepared-v2')
    parser.add_argument('--confirm-demo', action='store_true', required=True)
    parser.add_argument('--cohort', required=True)
    args = parser.parse_args()
    try:
        if not settings.database_url:
            raise ValueError('DATABASE_URL не задан')
        validate_target(settings.database_url.get_secret_value())
        group = prepared_cohort(args.cohort)
        with Session(get_engine()) as db:
            existing = db.scalar(select(User.id).where(User.login == f'judge-{group}-worker-2'))
            password = None if existing else getpass('Пароль второго рабочего (12–128 символов): ')
            result, ids = prepare_judge_profiles(db, cohort=args.cohort, worker_password=password)
            db.commit()
    except ValueError as exc:
        parser.error(str(exc))
    print(f'Judge profiles: {result}')
    print(f'JUDGE_COHORT={args.cohort}')
    for code, name in [('master', 'MASTER'), ('worker-1', 'WORKER_1'), ('worker-2', 'WORKER_2')]:
        print(f'JUDGE_{name}_USER_ID={ids[code]}')
    print('JUDGE_MODE_ENABLED=true')


if __name__ == '__main__':
    main()
