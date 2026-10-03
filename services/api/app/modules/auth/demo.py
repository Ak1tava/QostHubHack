"""Explicit local demo accounts, never created at application startup."""

import argparse
from datetime import datetime, timedelta, timezone
from getpass import getpass

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_engine
from app.core.security import hash_password
from app.modules.auth.models import Brigade, Shift, User, UserArea
from app.modules.auth.schemas import LoginRequest
from app.modules.catalog.models import Area


def validate_demo_target(url: str) -> None:
    target = make_url(url)
    if (
        target.get_backend_name() != "postgresql"
        or target.host not in {"localhost", "127.0.0.1", "::1", "db"}
        or not (target.database or "").startswith(("qosthub_demo", "qosthub_test"))
    ):
        raise ValueError(
            "Демоаккаунты разрешены только в локальной qosthub_demo* / qosthub_test* БД"
        )


def create_demo_accounts(
    db: Session,
    master_login: str,
    master_password: str,
    worker_login: str,
    worker_password: str,
):
    master_request = LoginRequest(login=master_login, password=master_password)
    worker_request = LoginRequest(login=worker_login, password=worker_password)
    logins = [master_request.login, worker_request.login]
    if len(set(logins)) != 2 or db.scalar(
        select(User.id).where(User.login.in_(logins)).limit(1)
    ):
        raise ValueError(
            "Указанные логины уже существуют или совпадают; пароли не изменены"
        )
    now = datetime.now(timezone.utc)
    area = db.scalar(select(Area).where(Area.name == "Демонстрационный участок"))
    if area is None:
        area = Area(name="Демонстрационный участок")
        db.add(area)
    brigade = db.scalar(
        select(Brigade).where(Brigade.name == "Демонстрационная бригада")
    )
    if brigade is None:
        brigade = Brigade(name="Демонстрационная бригада")
        db.add(brigade)
    shift = Shift(start_at=now, end_at=now + timedelta(hours=8))
    db.add(shift)
    db.flush()
    master = User(
        login=master_request.login,
        password_hash=hash_password(master_request.password),
        display_name="Демомастер",
        role="master",
        shift_id=shift.id,
    )
    worker = User(
        login=worker_request.login,
        password_hash=hash_password(worker_request.password),
        display_name="Демоисполнитель",
        role="worker",
        shift_id=shift.id,
        brigade_id=brigade.id,
    )
    db.add_all([master, worker])
    db.flush()
    db.add_all(
        [
            UserArea(user_id=master.id, area_id=area.id),
            UserArea(user_id=worker.id, area_id=area.id),
        ]
    )
    db.commit()


def main():
    parser = argparse.ArgumentParser(description="Создать два локальных демоаккаунта")
    parser.add_argument("--confirm-demo", action="store_true", required=True)
    parser.add_argument("--master-login", default="demo-master")
    parser.add_argument("--worker-login", default="demo-worker")
    args = parser.parse_args()
    if not settings.database_url:
        parser.error("DATABASE_URL не задан")
    try:
        validate_demo_target(settings.database_url.get_secret_value())
    except ValueError as exc:
        parser.error(str(exc))
    master_password = getpass("Пароль демомастера (не менее 8 символов): ")
    worker_password = getpass("Пароль демоисполнителя (не менее 8 символов): ")
    if min(len(master_password), len(worker_password)) < 8:
        parser.error("Задайте пароли не короче 8 символов")
    with Session(get_engine(), expire_on_commit=False) as db:
        try:
            create_demo_accounts(
                db,
                args.master_login,
                master_password,
                args.worker_login,
                worker_password,
            )
        except ValueError as exc:
            db.rollback()
            parser.error(str(exc))
    print("Демоаккаунты созданы. Пароли не сохранены в файлы и не напечатаны.")


if __name__ == "__main__":
    main()
