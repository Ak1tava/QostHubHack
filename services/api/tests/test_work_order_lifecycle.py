"""T03 API contracts, access boundaries and lifecycle behavior on PostgreSQL."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from conftest import sign_in
from sqlalchemy import select

from work_order_helpers import (
    BASE,
    action,
    add_user,
    count_rows,
    create_body,
    headers,
    issue,
    seed_order,
    succeed,
)


def test_work_order_routes_are_registered_without_database():
    from app.main import app

    paths = app.openapi()["paths"]
    assert {"get", "post"} <= paths[BASE].keys()
    assert "get" in paths[f"{BASE}/{{order_id}}"]
    assert "post" in paths[f"{BASE}/{{order_id}}/actions"]


def test_creation_sets_server_fields_and_atomic_audit(client, database):
    from app.modules.work_orders.models import OutboxEvent, WorkOrderEvent

    order = issue(client, database, priority="emergency", work_type="emergency")
    assert order["status"] == "ISSUED"
    assert order["version"] == order["assignment_version"] == 1
    assert order["number"] and UUID(order["id"])
    assert order["master_id"] == str(database["master"].id)
    assert order["is_overdue"] is False
    assert {"reassign", "cancel", "reprioritize"} <= set(order["allowed_actions"])
    session = database["session"]
    events = list(session.scalars(select(WorkOrderEvent)))
    assert len(events) == count_rows(session, OutboxEvent) == 1
    assert events[0].action == "create" and events[0].version == 1
    assert events[0].actor_id == database["master"].id
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert detail["submission"] is None
    assert [event["action"] for event in detail["events"]] == ["create"]
    token = sign_in(client)
    assert {"accept", "queue", "reject"} <= set(client.get(f"{BASE}/{order['id']}").json()["allowed_actions"])
    assert action(client, token, order, "start").status_code == 409


@pytest.mark.parametrize(
    "changes",
    [
        {"assignee_id": None},
        {"work_type": "unexpected"},
        {"priority": "urgent"},
        {"description": "   "},
        {"due_at": "2026-10-03T12:00:00"},
        {"status": "CLOSED"},
        {"number": "FORGED"},
        {"master_id": str(uuid4())},
    ],
)
def test_creation_rejects_invalid_or_server_owned_fields(client, database, changes):
    from app.modules.work_orders.models import WorkOrder, WorkOrderEvent

    token = sign_in(client, "master")
    response = client.post(BASE, json=create_body(database, **changes), headers=headers(token))
    assert response.status_code == 422, response.text
    assert count_rows(database["session"], WorkOrder) == 0
    assert count_rows(database["session"], WorkOrderEvent) == 0


def test_assignment_checks_equipment_area_and_worker_eligibility(client, database):
    from app.modules.catalog.models import Equipment

    other_equipment = database["session"].scalar(
        select(Equipment).where(Equipment.area_id == database["other_area"].id)
    )
    token = sign_in(client, "master")
    cases = [
        {"equipment_id": str(other_equipment.id)},
        {"equipment_id": str(uuid4())},
        {"assignee_id": str(database["outsider"].id)},
        {"assignee_id": str(database["master"].id)},
        {"brigade_id": str(database["brigade"].id), "responsible_id": str(database["worker"].id)},
        {"assignee_id": None, "brigade_id": str(database["brigade"].id)},
        {"assignee_id": None, "brigade_id": str(database["brigade"].id), "responsible_id": str(database["outsider"].id)},
    ]
    for changes in cases:
        response = client.post(BASE, json=create_body(database, **changes), headers=headers(token))
        assert response.status_code == 422, (changes, response.text)


def test_inactive_worker_cannot_receive_assignment(client, database):
    database["worker"].is_active = False
    database["session"].commit()
    token = sign_in(client, "master")
    response = client.post(BASE, json=create_body(database), headers=headers(token))
    assert response.status_code == 422


def test_mutations_require_session_csrf_and_origin(client, database):
    order = seed_order(database)
    endpoints = [(BASE, create_body(database)), (f"{BASE}/{order['id']}/actions", {"action": "accept", "expected_version": 1})]
    assert client.get(BASE).status_code == 401
    assert client.get(f"{BASE}/{order['id']}").status_code == 401
    for path, body in endpoints:
        assert client.post(path, json=body, headers=headers("invalid")).status_code == 401
    token = sign_in(client, "master")
    for path, body in endpoints:
        for removed in ("X-CSRF-Token", "Origin"):
            request_headers = headers(token)
            del request_headers[removed]
            assert client.post(path, json=body, headers=request_headers).status_code == 403
        request_headers = {**headers(token), "Origin": "https://evil.example"}
        assert client.post(path, json=body, headers=request_headers).status_code == 403


@pytest.mark.parametrize("key", [None, "", "x" * 129])
def test_mutations_require_valid_idempotency_key(client, database, key):
    order = seed_order(database)
    token = sign_in(client, "master")
    request_headers = headers(token)
    if key is None:
        del request_headers["Idempotency-Key"]
    else:
        request_headers["Idempotency-Key"] = key
    for path, body in [(BASE, create_body(database)), (f"{BASE}/{order['id']}/actions", {"action": "cancel", "expected_version": 1, "reason": "Отмена"})]:
        assert client.post(path, json=body, headers=request_headers).status_code == 422


def test_foreign_orders_are_hidden_from_list_read_and_actions(client, database):
    own = seed_order(database)
    foreign = seed_order(database, assignee_id=database["outsider"].id)
    token = sign_in(client)
    listing = client.get(BASE).json()
    assert listing["total"] == 1
    assert [item["id"] for item in listing["items"]] == [own["id"]]
    assert client.get(f"{BASE}/{foreign['id']}").status_code == 404
    assert action(client, token, foreign, "accept").status_code == 404
    assert client.get(f"{BASE}/{uuid4()}").status_code == 404
    assert client.post(BASE, json=create_body(database), headers=headers(token)).status_code == 403


def test_master_cannot_access_another_area(client, database):
    from app.modules.catalog.models import Equipment

    equipment = database["session"].scalar(select(Equipment).where(Equipment.area_id == database["other_area"].id))
    foreign = seed_order(database, area_id=database["other_area"].id, equipment_id=equipment.id, assignee_id=database["outsider"].id)
    token = sign_in(client, "master")
    assert client.get(BASE).json()["total"] == 0
    assert client.get(f"{BASE}/{foreign['id']}").status_code == 404
    assert action(client, token, foreign, "cancel", reason="Отмена").status_code == 404
    response = client.post(BASE, json=create_body(database, area_id=str(database["other_area"].id), equipment_id=str(equipment.id), assignee_id=str(database["outsider"].id)), headers=headers(token))
    assert response.status_code == 403


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_manager_and_admin_can_read_but_cannot_mutate(client, database, role):
    add_user(database, login=role, role=role)
    order = issue(client, database)
    token = sign_in(client, role)
    assert client.get(BASE).json()["total"] == 1
    detail = client.get(f"{BASE}/{order['id']}")
    assert detail.status_code == 200 and detail.json()["allowed_actions"] == []
    assert action(client, token, order, "cancel", reason="Отмена").status_code == 403
    assert client.post(BASE, json=create_body(database), headers=headers(token)).status_code == 403


def test_brigade_members_read_only_responsible_can_act(client, database):
    member = add_user(database, brigade_id=database["brigade"].id)
    order = issue(client, database, assignee_id=None, brigade_id=str(database["brigade"].id), responsible_id=str(database["worker"].id))
    token = sign_in(client, member.login)
    assert client.get(BASE).json()["total"] == 1
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert detail["allowed_actions"] == []
    assert action(client, token, order, "accept").status_code == 403
    token = sign_in(client)
    assert succeed(client, token, order, "accept")["status"] == "ACCEPTED"


def test_visible_order_still_enforces_master_and_worker_actions(client, database):
    order = issue(client, database)
    token = sign_in(client, "master")
    assert action(client, token, order, "accept").status_code == 403
    token = sign_in(client)
    assert action(client, token, order, "cancel", reason="Попытка отмены").status_code == 403
    assert action(client, token, order, "reprioritize", priority="high").status_code == 403
    assert client.get(f"{BASE}/{order['id']}").json()["version"] == 1


@pytest.mark.parametrize("name", ["submit", "begin_review", "request_rework", "close", "override_close"])
def test_public_action_endpoint_cannot_bypass_submission_or_review(client, database, name):
    order = seed_order(database, "AI_REVIEW")
    token = sign_in(client, "master")
    assert action(client, token, order, name).status_code == 422
    assert name not in client.get(f"{BASE}/{order['id']}").json()["allowed_actions"]


def test_accept_start_pause_resume_audit_and_intervals(client, database):
    from app.modules.work_orders.models import OutboxEvent, WorkOrderEvent, WorkOrderInterval

    order = issue(client, database)
    token = sign_in(client)
    for name, status, extra in [("accept", "ACCEPTED", {}), ("start", "IN_PROGRESS", {}), ("pause", "PAUSED", {"reason": "Нет запчастей"}), ("resume", "IN_PROGRESS", {})]:
        before = order
        order = succeed(client, token, order, name, **extra)
        assert order["status"] == status and order["version"] == before["version"] + 1
    token = sign_in(client, "master")
    order = succeed(client, token, order, "cancel", reason="Работа остановлена")
    session = database["session"]
    events = list(session.scalars(select(WorkOrderEvent).order_by(WorkOrderEvent.version)))
    assert [event.action for event in events] == ["create", "accept", "start", "pause", "resume", "cancel"]
    assert count_rows(session, OutboxEvent) == len(events) == 6
    assert events[3].reason == "Нет запчастей"
    assert events[3].actor_id == database["worker"].id
    assert events[3].payload["before"]["status"] == "IN_PROGRESS"
    assert events[3].payload["after"]["status"] == "PAUSED"
    assert all(event.occurred_at.tzinfo is not None for event in events)
    intervals = list(session.scalars(select(WorkOrderInterval).order_by(WorkOrderInterval.start_at)))
    assert [interval.kind for interval in intervals] == ["active", "pause", "active"]
    assert all(interval.end_at is not None and interval.end_at >= interval.start_at for interval in intervals)
    assert all(left.end_at <= right.start_at for left, right in zip(intervals, intervals[1:]))
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert [event["version"] for event in detail["events"]] == list(range(1, 7))
    assert detail["allowed_actions"] == []


@pytest.mark.parametrize("name,status,login", [("reject", "ISSUED", "worker"), ("pause", "IN_PROGRESS", "worker"), ("cancel", "ISSUED", "master"), ("reassign", "REJECTED", "master")])
def test_reasons_are_required_and_blank_reasons_rejected(client, database, name, status, login):
    from app.modules.work_orders.models import WorkOrderEvent

    order = seed_order(database, status)
    token = sign_in(client, login)
    extra = {"assignee_id": str(database["worker"].id)} if name == "reassign" else {}
    for reason in (None, "", " \n "):
        response = action(client, token, order, name, reason=reason, **extra)
        assert response.status_code == 422, response.text
    assert count_rows(database["session"], WorkOrderEvent) == 0
    assert client.get(f"{BASE}/{order['id']}").json()["version"] == 1


def test_queue_has_order_and_accept_clears_position(client, database):
    first, second = issue(client, database), issue(client, database)
    token = sign_in(client)
    first = succeed(client, token, first, "queue")
    second = succeed(client, token, second, "accept")
    second = succeed(client, token, second, "queue")
    assert 0 < first["queue_position"] < second["queue_position"]
    first = succeed(client, token, first, "accept")
    assert first["queue_position"] is None
    first = succeed(client, token, first, "queue")
    assert first["queue_position"] > second["queue_position"]


def test_reject_reassign_resets_assignment_and_revokes_former_worker(client, database):
    successor = add_user(database)
    order = issue(client, database)
    token = sign_in(client)
    order = succeed(client, token, order, "queue")
    order = succeed(client, token, order, "reject", reason="Нужна другая специальность")
    token = sign_in(client, "master")
    order = succeed(client, token, order, "reassign", assignee_id=str(successor.id), reason="Назначен специалист")
    assert order["status"] == "ISSUED" and order["assignment_version"] == 2
    assert order["queue_position"] is None
    assert order["assignee_id"] == str(successor.id)
    assert order["brigade_id"] is None and order["responsible_id"] is None
    token = sign_in(client)
    assert client.get(f"{BASE}/{order['id']}").status_code == 404
    assert action(client, token, order, "accept").status_code == 404
    token = sign_in(client, successor.login)
    assert succeed(client, token, order, "accept")["status"] == "ACCEPTED"


def test_invalid_reassignment_preserves_current_worker_and_audit(client, database):
    from app.modules.work_orders.models import OutboxEvent, WorkOrderEvent

    order = issue(client, database)
    token = sign_in(client, "master")
    response = action(client, token, order, "reassign", assignee_id=str(database["outsider"].id), reason="Другой участок")
    assert response.status_code == 422
    saved = client.get(f"{BASE}/{order['id']}").json()
    assert saved["assignee_id"] == order["assignee_id"]
    assert saved["version"] == saved["assignment_version"] == 1
    assert count_rows(database["session"], WorkOrderEvent) == 1
    assert count_rows(database["session"], OutboxEvent) == 1


def test_stale_version_and_invalid_transition_do_not_write(client, database):
    from app.modules.work_orders.models import OutboxEvent, WorkOrderEvent

    order = issue(client, database)
    token = sign_in(client)
    accepted = succeed(client, token, order, "accept")
    assert action(client, token, order, "queue").status_code == 409
    assert action(client, token, accepted, "resume").status_code == 409
    assert count_rows(database["session"], WorkOrderEvent) == 2
    assert count_rows(database["session"], OutboxEvent) == 2
    assert client.get(f"{BASE}/{order['id']}").json()["version"] == accepted["version"]


@pytest.mark.parametrize("status", ["CLOSED", "CANCELLED"])
def test_terminal_orders_reject_all_public_mutations(client, database, status):
    from app.modules.work_orders.models import WorkOrderEvent

    order = seed_order(database, status)
    for login, names in [("master", ("cancel", "reassign", "reprioritize")), ("worker", ("accept", "queue", "reject", "start", "pause", "resume", "restart"))]:
        token = sign_in(client, login)
        assert client.get(f"{BASE}/{order['id']}").json()["allowed_actions"] == []
        for name in names:
            extra = {"reason": "Причина"} if name in {"cancel", "reassign", "reject", "pause"} else {}
            if name == "reassign":
                extra["assignee_id"] = str(database["worker"].id)
            if name == "reprioritize":
                extra["priority"] = "high"
            assert action(client, token, order, name, **extra).status_code == 409
    assert count_rows(database["session"], WorkOrderEvent) == 0


@pytest.mark.parametrize("status", ["SUBMITTED", "AI_REVIEW", "CLOSED", "CANCELLED", "REWORK", "PAUSED", "ISSUED"])
def test_overdue_excludes_review_and_terminal_states(client, database, status):
    order = seed_order(database, status, due_at=datetime.now(timezone.utc) - timedelta(hours=1))
    sign_in(client)
    result = client.get(f"{BASE}/{order['id']}").json()
    assert result["is_overdue"] is (status in {"REWORK", "PAUSED", "ISSUED"})


def test_busy_worker_cannot_start_resume_or_restart_another_order(client, database):
    seed_order(database, "IN_PROGRESS")
    token = sign_in(client)
    for status, name in [("ACCEPTED", "start"), ("PAUSED", "resume"), ("REWORK", "restart")]:
        order = seed_order(database, status)
        assert action(client, token, order, name).status_code == 409
        assert name not in client.get(f"{BASE}/{order['id']}").json()["allowed_actions"]


def test_restart_from_rework_and_reprioritize_preserve_state(client, database):
    order = seed_order(database, "REWORK")
    token = sign_in(client)
    order = succeed(client, token, order, "restart")
    assert order["status"] == "IN_PROGRESS"
    token = sign_in(client, "master")
    changed = succeed(client, token, order, "reprioritize", priority="high")
    assert changed["priority"] == "high" and changed["status"] == "IN_PROGRESS"
    assert changed["version"] == order["version"] + 1


def test_list_filters_and_pagination_keep_total_and_scope(client, database):
    from app.modules.catalog.models import Equipment

    second_worker = add_user(database)
    second_equipment = Equipment(name="Второй насос", area_id=database["area"].id)
    database["session"].add(second_equipment)
    database["session"].commit()
    target = seed_order(database, "QUEUED", priority="high", queue_position=1)
    seed_order(database, "ACCEPTED", equipment_id=second_equipment.id, assignee_id=second_worker.id)
    seed_order(database, "REJECTED")
    sign_in(client, "master")
    filters = {"area_id": str(database["area"].id), "equipment_id": str(database["equipment"].id), "assignee_id": str(database["worker"].id), "priority": "high", "status": "QUEUED"}
    response = client.get(BASE, params=filters)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [target["id"]]
    for name, expected in [("area_id", 3), ("equipment_id", 2), ("assignee_id", 2), ("priority", 1), ("status", 1)]:
        assert client.get(BASE, params={name: filters[name]}).json()["total"] == expected
    pages = [client.get(BASE, params={"offset": offset, "limit": 1}).json() for offset in range(4)]
    assert all(page["total"] == 3 and page["limit"] == 1 and page["offset"] == offset for offset, page in enumerate(pages))
    assert len({page["items"][0]["id"] for page in pages[:3]}) == 3
    assert pages[-1]["items"] == []
    for params in ({"offset": -1}, {"limit": 0}, {"status": "UNKNOWN"}, {"priority": "urgent"}):
        assert client.get(BASE, params=params).status_code == 422
