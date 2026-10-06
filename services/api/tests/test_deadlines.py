"""Persisted clock boundaries, stale cancellation and fenced delivery recovery."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from app.modules.work_orders.models import OutboxEvent, WorkOrder, WorkOrderEvent
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from work_order_helpers import seed_order

NOW = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)


def order_at(database, **changes):
    row = seed_order(
        database, created_at=NOW, due_at=NOW + timedelta(hours=1), **changes
    )
    return database["session"].get(WorkOrder, UUID(row["id"]))


def rows(db):
    from app.modules.telegram.models import Notification

    return list(
        db.scalars(
            select(Notification).order_by(Notification.kind, Notification.recipient_id)
        )
    )


def deliver(factory, now, **kwargs):
    from app.workers.notifications import send_due_notifications

    clock = kwargs.pop("clock", lambda: now)
    return send_due_notifications(now, session_factory=factory, clock=clock, **kwargs)


@pytest.fixture
def ready(database, monkeypatch):
    from app.core.config import settings
    from app.modules.telegram.models import TelegramBinding

    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("synthetic-token"))
    monkeypatch.setattr(settings, "public_base_url", "https://synthetic.invalid")
    for n, role in enumerate(["worker", "master"], 1):
        database["session"].add(
            TelegramBinding(
                user_id=database[role].id, telegram_user_id=n, private_chat_id=n
            )
        )
    database["session"].commit()
    return lambda: Session(database["engine"], expire_on_commit=False)


class Transport:
    def __init__(self, error=None):
        self.error = error
        self.messages = []

    def send_message(self, chat_id, text, url):
        self.messages.append((chat_id, text, url))
        if self.error:
            raise self.error


@pytest.mark.parametrize("priority,minutes", [("emergency", 3), ("normal", 10)])
def test_schedule_boundaries_and_persisted_dedup(database, priority, minutes):
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    order = order_at(database, priority=priority)
    schedule_notifications(order, NOW)
    schedule_notifications(order, NOW)
    db.commit()
    jobs = rows(db)
    assert len(jobs) == 5
    assert {j.due_at for j in jobs if j.kind == "unaccepted"} == {
        NOW + timedelta(minutes=minutes)
    }
    assert {j.due_at for j in jobs if j.kind == "reminder"} == {
        NOW + timedelta(minutes=30)
    }
    assert {j.due_at for j in jobs if j.kind == "overdue"} == {NOW + timedelta(hours=1)}


def test_past_reminder_not_created_and_overdue_is_strict(database, ready):
    from app.workers.notifications import schedule_notifications

    order = order_at(database)
    schedule_notifications(order, NOW + timedelta(minutes=31))
    database["session"].commit()
    assert not any(j.kind == "reminder" for j in rows(database["session"]))
    transport = Transport()
    deliver(ready, NOW + timedelta(hours=1), client=transport)
    database["session"].expire_all()
    assert all(
        j.status == "PENDING" for j in rows(database["session"]) if j.kind == "overdue"
    )
    deliver(ready, NOW + timedelta(hours=1, microseconds=1), client=transport)
    database["session"].expire_all()
    assert all(
        j.status == "SENT" for j in rows(database["session"]) if j.kind == "overdue"
    )


@pytest.mark.parametrize(
    "status", ["ACCEPTED", "QUEUED", "CANCELLED", "REJECTED", "CLOSED"]
)
def test_stale_nonacceptance_is_cancelled_before_send(database, ready, status):
    from app.workers.notifications import schedule_notifications

    order = order_at(database)
    schedule_notifications(order, NOW)
    order.status = status
    database["session"].commit()
    transport = Transport()
    deliver(ready, NOW + timedelta(minutes=10), client=transport)
    database["session"].expire_all()
    assert all(
        j.status == "CANCELLED"
        for j in rows(database["session"])
        if j.kind in {"new", "unaccepted"}
    )
    assert transport.messages == []


def test_reassignment_origin_and_priority_reschedule_without_replay(database):
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    order = order_at(database)
    schedule_notifications(order, NOW)
    order.assignment_version = 2
    event = WorkOrderEvent(
        work_order_id=order.id,
        action="reassign",
        version=2,
        assignment_version=2,
        occurred_at=NOW + timedelta(minutes=20),
        payload={},
    )
    db.add(event)
    db.flush()
    schedule_notifications(order, NOW + timedelta(minutes=20))
    order.priority = "emergency"
    schedule_notifications(order, NOW + timedelta(minutes=21))
    db.commit()
    current = [
        j for j in rows(db) if j.assignment_version == 2 and j.kind == "unaccepted"
    ]
    assert len(current) == 1 and current[0].due_at == NOW + timedelta(minutes=23)
    current[0].status = "SENT"
    order.priority = "normal"
    schedule_notifications(order, NOW + timedelta(minutes=24))
    assert current[0].status == "SENT"


@pytest.mark.parametrize(
    "code,want,retry",
    [
        ("bot_blocked", "FAILED", None),
        ("rate_limited", "RETRY", 120),
        ("timeout", "RETRY", None),
    ],
)
def test_delivery_errors_persist_safe_codes_and_retry_clock(
    database, ready, code, want, retry
):
    from app.modules.telegram.client import TelegramError
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    schedule_notifications(order_at(database), NOW)
    db.commit()
    deliver(ready, NOW, client=Transport(TelegramError(code, retry_after=retry)))
    db.expire_all()
    job = next(j for j in rows(db) if j.kind == "new")
    assert job.status == want and job.attempts == 1 and job.last_error == code
    if retry:
        assert job.next_attempt_at == NOW + timedelta(seconds=120)


def test_lease_recovery_fences_old_finish(database, ready):
    from app.workers.jobs import claim_job, finish_job
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    schedule_notifications(order_at(database), NOW)
    db.commit()
    with ready() as worker:
        first = claim_job(worker, NOW)
        worker.commit()
    with ready() as restarted:
        second = claim_job(restarted, NOW + timedelta(seconds=61))
        restarted.commit()
        assert first[0] == second[0] and first[1] != second[1]
        assert not finish_job(
            restarted, *first, status="SENT", now=NOW + timedelta(seconds=62)
        )
        assert finish_job(
            restarted, *second, status="SENT", now=NOW + timedelta(seconds=62)
        )
        restarted.commit()
    db.expire_all()
    assert next(j for j in rows(db) if j.kind == "new").status == "SENT"


def test_missing_binding_is_visible_and_linking_recovers(database, monkeypatch):
    from app.core.config import settings
    from app.modules.telegram.models import TelegramBinding
    from app.workers.notifications import schedule_notifications

    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("synthetic-token"))
    monkeypatch.setattr(settings, "public_base_url", "https://synthetic.invalid")
    db = database["session"]
    factory = lambda: Session(database["engine"], expire_on_commit=False)
    schedule_notifications(order_at(database), NOW)
    db.commit()
    deliver(factory, NOW, client=Transport())
    db.expire_all()
    job = next(j for j in rows(db) if j.kind == "new")
    assert (job.status, job.last_error, job.attempts) == (
        "BLOCKED",
        "missing_binding",
        0,
    )
    db.add(
        TelegramBinding(
            user_id=database["worker"].id, telegram_user_id=123, private_chat_id=123
        )
    )
    db.commit()
    transport = Transport()
    deliver(factory, NOW + timedelta(minutes=1), client=transport)
    db.expire_all()
    assert job.status == "SENT"
    assert "Синтетический" not in transport.messages[0][1]
    assert transport.messages[0][2].startswith("https://synthetic.invalid/orders/")


def test_outbox_consumer_has_independent_receipts(database):
    from app.modules.telegram.models import NotificationReceipt
    from app.workers.notifications import process_outbox

    db = database["session"]
    order = order_at(database)
    event = WorkOrderEvent(
        work_order_id=order.id,
        action="issue",
        version=1,
        assignment_version=1,
        occurred_at=NOW,
        payload={},
    )
    db.add(event)
    db.flush()
    outbox = OutboxEvent(
        event_id=event.id,
        work_order_id=order.id,
        version=1,
        assignment_version=1,
        type="work_order.issue",
        occurred_at=NOW,
        payload={},
    )
    db.add(outbox)
    db.commit()
    assert process_outbox(db, NOW) == 1
    assert process_outbox(db, NOW) == 0
    db.commit()
    assert outbox.published_at is None
    assert db.get(NotificationReceipt, outbox.id) is not None
    assert len(rows(db)) == 5
