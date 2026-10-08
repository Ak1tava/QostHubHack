"""Only explicit, isolated prepared judge accounts may bypass passwords."""

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import Brigade, User, UserArea
from app.modules.catalog.models import Area

PROFILE_LABELS = (
    ('master', 'Мастер', 'master'),
    ('worker-1', 'Рабочий 1', 'worker'),
    ('worker-2', 'Рабочий 2', 'worker'),
)


def prepared_cohort(cohort: str | None) -> str:
    if not cohort or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', cohort):
        raise ValueError('Некорректная группа судей')
    value = cohort + '-prepared-v2'
    if len(value) > 40:
        raise ValueError('Некорректная группа судей')
    return value


def validate_profiles(db: Session, cohort: str | None, ids: dict[str, UUID | None]) -> dict[str, User]:
    group = prepared_cohort(cohort)
    if not ids or any(not isinstance(value, UUID) for value in ids.values()) or len(set(ids.values())) != len(ids):
        raise ValueError('Аккаунты судей не настроены')
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids.values()))
                                       .execution_options(populate_existing=True))}
    if len(users) != len(ids):
        raise ValueError('Аккаунты судей не найдены')
    suffixes = {'master': 'master', 'worker-1': 'worker', 'worker-2': 'worker-2'}
    result = {}
    common_area = None
    for code, uid in ids.items():
        user = users[uid]
        if (code not in suffixes or not user.is_active or
                user.role != ('master' if code == 'master' else 'worker') or
                user.login != f'judge-{group}-{suffixes[code]}'):
            raise ValueError('Доступ судей изменён')
        areas = set(db.scalars(select(UserArea.area_id).where(UserArea.user_id == uid)))
        if len(areas) != 1 or (common_area is not None and areas != {common_area}):
            raise ValueError('Доступ судей изменён')
        common_area = next(iter(areas))
        result[code] = user
    area = db.get(Area, common_area)
    if not area or area.name != f'[T18 СИНТЕТИКА] Участок судей {group}':
        raise ValueError('Неизолированный участок судей')
    if set(db.scalars(select(UserArea.user_id).where(UserArea.area_id == common_area))) != set(ids.values()):
        raise ValueError('Неизолированный участок судей')
    workers = [u for code, u in result.items() if code != 'master']
    brigade_id = workers[0].brigade_id
    brigade = db.get(Brigade, brigade_id) if brigade_id else None
    if (not brigade or brigade.name != f'[T18 СИНТЕТИКА] Бригада судей {group}' or
            any(u.brigade_id != brigade_id for u in workers)):
        raise ValueError('Доступ судей изменён')
    if set(db.scalars(select(User.id).where(User.brigade_id == brigade_id))) != {u.id for u in workers}:
        raise ValueError('Неизолированная бригада судей')
    return result
