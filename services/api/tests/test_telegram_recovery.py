from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_deadlines import NOW, Transport, deliver, order_at, rows
from test_deadlines import ready as ready


@pytest.mark.parametrize("status", ["PENDING", "RETRY", "BLOCKED"])
def test_priority_edit_moves_unsent_semantic_due_without_erasing_backoff(
    database, status
):
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    order = order_at(database)
    schedule_notifications(order, NOW)
    job = next(j for j in rows(db) if j.kind == "unaccepted")
    job.status = status
    if status != "PENDING":
        job.next_attempt_at = NOW + timedelta(minutes=15)
    db.flush()
    order.priority = "emergency"
    schedule_notifications(order, NOW + timedelta(minutes=1))
    db.refresh(job)
    assert job.due_at == NOW + timedelta(minutes=3)
    assert job.next_attempt_at == NOW + timedelta(
        minutes=3 if status == "PENDING" else 15
    )


def test_live_clock_cancels_reminder_after_previous_slow_send(database, ready):
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    schedule_notifications(order_at(database), NOW)
    db.commit()
    current = [NOW + timedelta(minutes=30)]

    class Slow(Transport):
        def send_message(self, chat_id, message, url, *, language="ru"):
            super().send_message(chat_id, message, url)
            current[0] = NOW + timedelta(hours=1, seconds=1)

    deliver(ready, current[0], client=Slow(), clock=lambda: current[0])
    db.expire_all()
    assert next(j for j in rows(db) if j.kind == "reminder").status == "CANCELLED"
    assert all(j.status == "SENT" for j in rows(db) if j.kind == "overdue")


def test_expired_lease_during_transport_cannot_ack_sent(database, ready):
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    schedule_notifications(order_at(database), NOW)
    db.commit()
    current = [NOW]

    class Slow(Transport):
        def send_message(self, chat_id, message, url, *, language="ru"):
            current[0] = NOW + timedelta(seconds=61)

    deliver(ready, NOW, client=Slow(), clock=lambda: current[0], limit=1)
    db.expire_all()
    job = next(j for j in rows(db) if j.kind == "new")
    assert job.status == "LEASED" and job.sent_at is None


def test_sending_does_not_deadlock_against_actor_foreign_key_lock(database, ready):
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    schedule_notifications(order_at(database), NOW)
    db.commit()
    with ready() as command:
        command.execute(
            text("SELECT id FROM users WHERE id=:id FOR KEY SHARE"),
            {"id": database["worker"].id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(deliver, ready, NOW, client=Transport(), limit=1)
            try:
                assert task.result(timeout=3) == 1
            finally:
                command.rollback()
    db.expire_all()
    assert next(j for j in rows(db) if j.kind == "new").status == "SENT"


def test_concurrent_update_consumes_one_link_once(database):
    from app.modules.telegram.models import TelegramBinding, TelegramUpdate
    from app.modules.telegram.service import handle_update, issue_link_token
    from test_telegram_linking import start

    db = database["session"]
    token = issue_link_token(db, database["worker"], NOW)
    db.commit()
    barrier = Barrier(2)

    def consume():
        with Session(database["engine"]) as session:
            barrier.wait(timeout=5)
            result = handle_update(session, start(token), NOW)
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(consume) for _ in range(2)]
        assert sorted(t.result(timeout=10) for t in tasks) == ["duplicate", "linked"]
    db.expire_all()
    assert len(list(db.scalars(select(TelegramBinding)))) == 1
    assert len(list(db.scalars(select(TelegramUpdate)))) == 1


def test_concurrent_claims_never_lease_same_job(database, ready):
    from app.workers.jobs import claim_job
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    schedule_notifications(order_at(database), NOW)
    db.commit()
    barrier = Barrier(2)

    def claim():
        with ready() as session:
            barrier.wait(timeout=5)
            result = claim_job(session, NOW)
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(claim) for _ in range(2)]
        values = [t.result(timeout=10) for t in tasks]
    assert sum(v is not None for v in values) == 1
    db.expire_all()
    assert sum(j.status == "LEASED" for j in rows(db)) == 1


def test_retry_budget_is_persisted_and_exhausted(database, ready):
    from app.modules.telegram.client import TelegramError
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    schedule_notifications(order_at(database), NOW)
    db.commit()
    transport = Transport(TelegramError("timeout"))
    for seconds in [0, 5, 15, 35, 75, 300]:
        deliver(ready, NOW + timedelta(seconds=seconds), client=transport)
    db.expire_all()
    job = next(j for j in rows(db) if j.kind == "new")
    assert job.status == "FAILED" and job.attempts == 5 and job.last_error == "timeout"


def test_configuration_block_does_not_consume_attempt_and_recovers(
    database, ready, monkeypatch
):
    from app.core.config import settings
    from app.workers.notifications import schedule_notifications
    from pydantic import SecretStr

    db = database["session"]
    schedule_notifications(order_at(database), NOW)
    db.commit()
    monkeypatch.setattr(settings, "telegram_bot_token", None)
    deliver(ready, NOW, client=Transport())
    db.expire_all()
    job = next(j for j in rows(db) if j.kind == "new")
    assert (job.status, job.last_error, job.attempts) == (
        "BLOCKED",
        "missing_configuration",
        0,
    )
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("synthetic-token"))
    deliver(ready, NOW + timedelta(minutes=1), client=Transport())
    db.expire_all()
    assert job.status == "SENT" and job.attempts == 1


def test_emergency_queue_is_separate_master_notification(database, ready):
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    order = order_at(database, priority="emergency", status="QUEUED")
    schedule_notifications(order, NOW)
    db.commit()
    deliver(ready, NOW, client=Transport())
    db.expire_all()
    queued = [j for j in rows(db) if j.kind == "emergency_queued"]
    assert (
        len(queued) == 1
        and queued[0].recipient_id == database["master"].id
        and queued[0].status == "SENT"
    )
    assert not any(j.kind in {"new", "unaccepted"} for j in rows(db))


def test_prepared_attempt_persists_and_api_lock_released_during_http(database, ready):
    from threading import Event

    from app.modules.telegram.models import Notification
    from app.modules.work_orders.models import WorkOrder
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    order = order_at(database)
    schedule_notifications(order, NOW)
    db.commit()
    sending, release = Event(), Event()

    class Waiting(Transport):
        def send_message(self, chat_id, message, url, *, language="ru"):
            sending.set()
            assert release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(deliver, ready, NOW, client=Waiting(), limit=1)
        try:
            assert sending.wait(timeout=3)
            with ready() as command:
                command.execute(text("SET LOCAL lock_timeout = '1s'"))
                persisted = command.scalar(
                    select(Notification).where(Notification.kind == "new")
                )
                assert persisted.attempts == 1 and persisted.status == "LEASED"
                command.execute(
                    text("UPDATE work_orders SET status='ACCEPTED' WHERE id=:id"),
                    {"id": order.id},
                )
                command.commit()
        finally:
            release.set()
        assert task.result(timeout=3) == 1
    db.expire_all()
    assert db.get(WorkOrder, order.id).status == "ACCEPTED"


def test_concurrent_different_update_ids_cannot_reuse_link_token(database):
    from app.modules.telegram.models import TelegramBinding, TelegramUpdate
    from app.modules.telegram.service import handle_update, issue_link_token
    from test_telegram_linking import start

    db = database["session"]
    token = issue_link_token(db, database["worker"], NOW)
    db.commit()
    barrier = Barrier(2)

    def consume(update_id):
        with Session(database["engine"]) as session:
            barrier.wait(timeout=5)
            result = handle_update(session, start(token, update_id), NOW)
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(consume, update_id) for update_id in [1, 2]]
        assert sorted(t.result(timeout=10) for t in tasks) == [
            "invalid_token",
            "linked",
        ]
    db.expire_all()
    assert len(list(db.scalars(select(TelegramBinding)))) == 1
    assert len(list(db.scalars(select(TelegramUpdate)))) == 2


@pytest.mark.parametrize(
    "priority,before,at", [("emergency", 179, 180), ("normal", 599, 600)]
)
def test_nonacceptance_sends_at_exact_managed_clock_boundary(
    database, ready, priority, before, at
):
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    schedule_notifications(order_at(database, priority=priority), NOW)
    db.commit()
    deliver(ready, NOW + timedelta(seconds=before), client=Transport())
    db.expire_all()
    job = next(j for j in rows(db) if j.kind == "unaccepted")
    assert job.status == "PENDING"
    deliver(ready, NOW + timedelta(seconds=at), client=Transport())
    db.expire_all()
    assert job.status == "SENT"


def test_reminder_sends_at_exact_thirty_minutes_and_lost_master_access_cancels(
    database, ready
):
    from app.modules.auth.models import UserArea
    from app.workers.notifications import schedule_notifications
    from sqlalchemy import delete

    db = database["session"]
    schedule_notifications(order_at(database), NOW)
    db.commit()
    db.execute(delete(UserArea).where(UserArea.user_id == database["master"].id))
    db.commit()
    deliver(ready, NOW + timedelta(minutes=29, seconds=59), client=Transport())
    db.expire_all()
    reminder = next(j for j in rows(db) if j.kind == "reminder")
    assert reminder.status == "PENDING"
    assert next(j for j in rows(db) if j.kind == "unaccepted").status == "CANCELLED"
    deliver(ready, NOW + timedelta(minutes=30), client=Transport())
    db.expire_all()
    assert reminder.status == "SENT"
