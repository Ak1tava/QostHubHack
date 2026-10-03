"""Small PostgreSQL/API helpers shared by the lifecycle behavior tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from conftest import sign_in
from sqlalchemy import func, select

from app.modules.auth.models import User, UserArea
from app.modules.work_orders.models import WorkOrder

BASE = "/api/v1/work-orders"
ORIGIN = "http://localhost:5173"


def headers(token, key=None):
    return {
        "Origin": ORIGIN,
        "X-CSRF-Token": token,
        "Idempotency-Key": key or str(uuid4()),
    }


def create_body(database, **changes):
    body = {
        "work_type": "planned",
        "description": "Проверить насос",
        "area_id": str(database["area"].id),
        "equipment_id": str(database["equipment"].id),
        "assignee_id": str(database["worker"].id),
        "due_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    }
    body.update(changes)
    return body


def issue(client, database, **changes):
    token = sign_in(client, "master")
    response = client.post(BASE, json=create_body(database, **changes), headers=headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def action(client, token, order, name, *, key=None, **changes):
    body = {"action": name, "expected_version": order["version"], **changes}
    return client.post(f"{BASE}/{order['id']}/actions", json=body, headers=headers(token, key))


def succeed(client, token, order, name, **changes):
    response = action(client, token, order, name, **changes)
    assert response.status_code == 200, response.text
    return response.json()


def add_user(database, login="second", role="worker", *, brigade_id=None, area=None):
    user = User(
        login=login,
        display_name="Тестовый сотрудник",
        password_hash=database["worker"].password_hash,
        role=role,
        brigade_id=brigade_id,
        shift_id=database["shift"].id,
    )
    session = database["session"]
    session.add(user)
    session.flush()
    session.add(UserArea(user_id=user.id, area_id=(area or database["area"]).id))
    session.commit()
    return user


def seed_order(database, status="ISSUED", **changes):
    values = {
        "number": "TEST-" + uuid4().hex,
        "work_type": "planned",
        "description": "Синтетический наряд",
        "area_id": database["area"].id,
        "equipment_id": database["equipment"].id,
        "assignee_id": database["worker"].id,
        "master_id": database["master"].id,
        "due_at": datetime.now(timezone.utc) + timedelta(hours=2),
        "status": status,
        **changes,
    }
    order = WorkOrder(**values)
    database["session"].add(order)
    database["session"].commit()
    return {"id": str(order.id), "version": order.version}


def count_rows(session, model):
    return session.scalar(select(func.count()).select_from(model))
