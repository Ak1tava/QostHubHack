import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.fixture
def database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "Set TEST_DATABASE_URL to a dedicated qosthub_test PostgreSQL database"
        )
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or not (
        parsed.database or ""
    ).startswith("qosthub_test"):
        pytest.fail("Refusing destructive fixtures outside qosthub_test*")
    from app.core.db import Base
    from app.core.security import hash_password
    from app.modules.auth.models import Brigade, Shift, User, UserArea
    from app.modules.catalog.models import Area, Equipment, Material, WorkCode
    from app.modules.work_orders import (
        models,  # noqa: F401 — registers SQLAlchemy metadata
    )
    from app.modules.telegram import models as telegram_models  # noqa: F401

    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    area = Area(name="Первый участок")
    other_area = Area(name="Чужой участок")
    shift = Shift(start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=7))
    brigade = Brigade(name="Первая бригада")
    session.add_all([area, other_area, shift, brigade])
    session.flush()
    common = dict(
        password_hash=hash_password("0042"),
        specialty="Слесарь",
        grade=3,
        shift_id=shift.id,
    )
    master = User(login="master", display_name="Мастер", role="master", **common)
    worker = User(
        login="worker",
        display_name="Исполнитель",
        role="worker",
        brigade_id=brigade.id,
        **common,
    )
    outsider = User(login="outsider", display_name="Другой", role="worker", **common)
    session.add_all([master, worker, outsider])
    session.flush()
    session.add_all(
        [
            UserArea(user_id=master.id, area_id=area.id),
            UserArea(user_id=worker.id, area_id=area.id),
            UserArea(user_id=outsider.id, area_id=other_area.id),
        ]
    )
    eq = Equipment(name="Насос", area_id=area.id)
    eq2 = Equipment(name="Чужой насос", area_id=other_area.id)
    session.add_all(
        [eq, eq2, Material(name="Масло", unit="л"), WorkCode(code="M01", name="Ремонт")]
    )
    session.commit()
    yield dict(
        session=session,
        engine=engine,
        master=master,
        worker=worker,
        outsider=outsider,
        area=area,
        other_area=other_area,
        equipment=eq,
        brigade=brigade,
        shift=shift,
    )
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def app(database, monkeypatch):
    from app.core.config import settings
    from app.core.db import get_db
    from app.main import app

    monkeypatch.setattr(settings, "public_base_url", "http://localhost:5173")
    monkeypatch.setattr(settings, "session_cookie_secure", False)

    def db_override():
        yield database["session"]

    app.dependency_overrides[get_db] = db_override
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://localhost:5173") as client:
        yield client


def sign_in(client, login="worker", password="0042"):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/login",
        json={"login": login, "password": password},
        headers={"Origin": "http://localhost:5173", "X-CSRF-Token": token},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]
