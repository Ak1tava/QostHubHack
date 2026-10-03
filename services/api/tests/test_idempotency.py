"""Replay, real PostgreSQL races and rollback at the outbox boundary."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import UUID

import pytest
from conftest import sign_in
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from work_order_helpers import (
    BASE,
    ORIGIN,
    action,
    add_user,
    count_rows,
    create_body,
    headers,
    issue,
    seed_order,
    succeed,
)


@contextmanager
def independent_requests(app, database):
    """Each HTTP request owns its transaction, including concurrent requests."""
    from app.core.db import get_db

    previous = app.dependency_overrides[get_db]

    def separate_session():
        with Session(database["engine"], expire_on_commit=False, autoflush=False) as session:
            try:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text("SET LOCAL statement_timeout = '15s'"))
                yield session
            finally:
                session.rollback()

    app.dependency_overrides[get_db] = separate_session
    try:
        yield
    finally:
        app.dependency_overrides[get_db] = previous


def race_actions(app, database, client, token, requests):
    cookie = client.cookies.get("qosthub_session")
    ready = Barrier(len(requests))

    def send(spec):
        order, key, name = spec
        with TestClient(app, base_url=ORIGIN) as other:
            other.cookies.set("qosthub_session", cookie, domain="localhost.local", path="/")
            ready.wait(timeout=10)
            return action(other, token, order, name, key=key)

    with independent_requests(app, database):
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(send, requests))


def test_creation_replay_returns_exact_response_without_duplicate_rows(client, database):
    from app.modules.work_orders.models import IdempotencyRecord, OutboxEvent, WorkOrder, WorkOrderEvent

    token = sign_in(client, "master")
    body = create_body(database)
    first = client.post(BASE, json=body, headers=headers(token, "create-once"))
    second = client.post(BASE, json=body, headers=headers(token, "create-once"))
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    for model in (WorkOrder, WorkOrderEvent, OutboxEvent, IdempotencyRecord):
        assert count_rows(database["session"], model) == 1
    changed = client.post(BASE, json={**body, "description": "Другое задание"}, headers=headers(token, "create-once"))
    assert changed.status_code == 409


def test_action_replay_uses_original_snapshot_after_later_changes(client, database):
    from app.modules.work_orders.models import OutboxEvent, WorkOrderEvent

    order = issue(client, database)
    token = sign_in(client)
    first = action(client, token, order, "accept", key="accept-once")
    assert first.status_code == 200
    accepted = first.json()
    latest = succeed(client, token, accepted, "start")
    replay = action(client, token, order, "accept", key="accept-once")
    assert replay.status_code == 200 and replay.json() == accepted
    assert replay.json()["version"] < latest["version"]
    assert client.get(f"{BASE}/{order['id']}").json()["status"] == "IN_PROGRESS"
    assert count_rows(database["session"], WorkOrderEvent) == 3
    assert count_rows(database["session"], OutboxEvent) == 3
    assert action(client, token, accepted, "queue", key="accept-once").status_code == 409


def test_create_replay_returns_original_snapshot_after_order_changed(client, database):
    token = sign_in(client, "master")
    body = create_body(database)
    first = client.post(BASE, json=body, headers=headers(token, "original-create"))
    assert first.status_code == 201
    order = first.json()
    succeed(client, token, order, "reprioritize", priority="high")
    replay = client.post(BASE, json=body, headers=headers(token, "original-create"))
    assert replay.status_code == 201 and replay.json() == order


def test_failed_commands_leave_key_available_for_corrected_request(client, database):
    from app.modules.work_orders.models import IdempotencyRecord

    token = sign_in(client, "master")
    body = create_body(database)
    failed = client.post(BASE, json={**body, "assignee_id": str(database["outsider"].id)}, headers=headers(token, "fix-create"))
    assert failed.status_code == 422
    assert count_rows(database["session"], IdempotencyRecord) == 0
    created = client.post(BASE, json=body, headers=headers(token, "fix-create"))
    assert created.status_code == 201
    order = created.json()
    token = sign_in(client)
    failed = action(client, token, order, "start", key="fix-action")
    assert failed.status_code == 409
    assert count_rows(database["session"], IdempotencyRecord) == 1
    repaired = action(client, token, order, "accept", key="fix-action")
    assert repaired.status_code == 200
    assert count_rows(database["session"], IdempotencyRecord) == 2


def test_replay_rechecks_access_after_reassignment(client, database):
    successor = add_user(database)
    original = issue(client, database)
    token = sign_in(client)
    accepted = succeed(client, token, original, "accept", key="former-worker")
    token = sign_in(client, "master")
    order = succeed(client, token, accepted, "reassign", assignee_id=str(successor.id), reason="Передача смены")
    token = sign_in(client)
    assert action(client, token, original, "accept", key="former-worker").status_code == 404
    assert action(client, token, order, "accept").status_code == 404


def test_replay_rechecks_responsibility_for_brigade_member(client, database):
    successor = add_user(database, brigade_id=database["brigade"].id)
    original = issue(client, database, assignee_id=None, brigade_id=str(database["brigade"].id), responsible_id=str(database["worker"].id))
    token = sign_in(client)
    accepted = succeed(client, token, original, "accept", key="old-responsible")
    token = sign_in(client, "master")
    reassigned = succeed(client, token, accepted, "reassign", brigade_id=str(database["brigade"].id), responsible_id=str(successor.id), reason="Новый ответственный")
    token = sign_in(client)
    assert client.get(f"{BASE}/{reassigned['id']}").status_code == 200
    assert action(client, token, original, "accept", key="old-responsible").status_code == 403
    assert action(client, token, reassigned, "accept").status_code == 403


def test_two_commands_for_same_version_only_commit_once(app, client, database):
    from app.modules.work_orders.models import OutboxEvent, WorkOrderEvent

    order = seed_order(database, "ACCEPTED")
    token = sign_in(client)
    responses = race_actions(app, database, client, token, [(order, "start-left", "start"), (order, "start-right", "start")])
    assert sorted(response.status_code for response in responses) == [200, 409]
    with Session(database["engine"]) as reader:
        assert count_rows(reader, WorkOrderEvent) == count_rows(reader, OutboxEvent) == 1


def test_concurrent_same_key_returns_same_success_and_one_event(app, client, database):
    from app.modules.work_orders.models import IdempotencyRecord, OutboxEvent, WorkOrderEvent

    order = seed_order(database, "ACCEPTED")
    token = sign_in(client)
    responses = race_actions(app, database, client, token, [(order, "one-start", "start"), (order, "one-start", "start")])
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    with Session(database["engine"]) as reader:
        for model in (WorkOrderEvent, OutboxEvent, IdempotencyRecord):
            assert count_rows(reader, model) == 1


def test_two_orders_for_same_worker_cannot_start_concurrently(app, client, database):
    from app.modules.work_orders.models import OutboxEvent, WorkOrder, WorkOrderEvent

    first = seed_order(database, "ACCEPTED")
    second = seed_order(database, "ACCEPTED")
    token = sign_in(client)
    responses = race_actions(app, database, client, token, [(first, "first-order", "start"), (second, "second-order", "start")])
    assert sorted(response.status_code for response in responses) == [200, 409]
    with Session(database["engine"]) as reader:
        statuses = list(reader.scalars(select(WorkOrder.status)))
        assert sorted(statuses) == ["ACCEPTED", "IN_PROGRESS"]
        assert count_rows(reader, WorkOrderEvent) == count_rows(reader, OutboxEvent) == 1


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_creation_allocates_unique_numbers_or_replays(app, client, database, same_key):
    from app.modules.work_orders.models import IdempotencyRecord, OutboxEvent, WorkOrder, WorkOrderEvent

    token = sign_in(client, "master")
    cookie = client.cookies.get("qosthub_session")
    body = create_body(database)
    ready = Barrier(2)

    def create(index):
        key = "parallel-create" if same_key else f"parallel-create-{index}"
        with TestClient(app, base_url=ORIGIN) as other:
            other.cookies.set("qosthub_session", cookie, domain="localhost.local", path="/")
            ready.wait(timeout=10)
            return other.post(BASE, json=body, headers=headers(token, key))

    with independent_requests(app, database):
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(create, range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    expected = 1 if same_key else 2
    assert len({response.json()["number"] for response in responses}) == expected
    assert len({response.json()["id"] for response in responses}) == expected
    if same_key:
        assert responses[0].json() == responses[1].json()
    with Session(database["engine"]) as reader:
        for model in (WorkOrder, WorkOrderEvent, OutboxEvent, IdempotencyRecord):
            assert count_rows(reader, model) == expected


@pytest.mark.parametrize("operation", ["create", "start"])
def test_outbox_failure_rolls_back_order_audit_interval_and_idempotency(app, client, database, operation):
    from app.modules.work_orders.models import IdempotencyRecord, OutboxEvent, WorkOrder, WorkOrderEvent, WorkOrderInterval

    order = seed_order(database, "ACCEPTED") if operation == "start" else None
    token = sign_in(client, "worker" if order else "master")
    cookie = client.cookies.get("qosthub_session")

    def fail_outbox_flush(session, *_):
        if any(isinstance(row, OutboxEvent) for row in session.new):
            raise RuntimeError("Synthetic outbox failure")

    event.listen(Session, "before_flush", fail_outbox_flush)
    try:
        with independent_requests(app, database):
            with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as other:
                other.cookies.set("qosthub_session", cookie, domain="localhost.local", path="/")
                if order:
                    failed = action(other, token, order, "start", key="retry-after-rollback")
                else:
                    failed = other.post(BASE, json=create_body(database), headers=headers(token, "retry-after-rollback"))
                assert failed.status_code == 500
    finally:
        event.remove(Session, "before_flush", fail_outbox_flush)

    with Session(database["engine"]) as reader:
        assert count_rows(reader, WorkOrder) == (1 if order else 0)
        for model in (WorkOrderEvent, OutboxEvent, IdempotencyRecord, WorkOrderInterval):
            assert count_rows(reader, model) == 0
        if order:
            saved = reader.get(WorkOrder, UUID(order["id"]))
            assert saved.status == "ACCEPTED" and saved.version == 1
    if order:
        retry = action(client, token, order, "start", key="retry-after-rollback")
        assert retry.status_code == 200
    else:
        retry = client.post(BASE, json=create_body(database), headers=headers(token, "retry-after-rollback"))
        assert retry.status_code == 201
