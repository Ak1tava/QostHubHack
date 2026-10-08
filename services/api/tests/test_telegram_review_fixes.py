"""Regressions for the independent T06 review findings."""

import asyncio
import time
from datetime import datetime, timezone
from threading import Event, Thread

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_deadlines import NOW, Transport, deliver, order_at, rows
from test_deadlines import ready as ready
from test_telegram_linking import start


def test_scheduler_refreshes_preloaded_assignment_under_lock(database):
    from app.modules.work_orders.models import WorkOrder
    from app.workers.notifications import schedule_notifications

    original = order_at(database)
    database["session"].commit()
    with Session(database["engine"], autoflush=False, expire_on_commit=False) as stale:
        old = stale.get(WorkOrder, original.id)
        with Session(database["engine"], autoflush=False) as current:
            changed = current.get(WorkOrder, original.id)
            changed.assignment_version = 2
            current.commit()
            schedule_notifications(changed, NOW, db=current)
            current.commit()
        assert old.assignment_version == 1
        schedule_notifications(old, NOW, db=stale)
        stale.commit()
        current_jobs = [job for job in rows(stale) if job.assignment_version == 2]
        assert current_jobs and all(job.status == "PENDING" for job in current_jobs)
        assert old.assignment_version == 2


def test_scheduler_preserves_local_changes_with_autoflush_disabled(database):
    from app.modules.work_orders.models import WorkOrder
    from app.workers.notifications import schedule_notifications

    original = order_at(database)
    database["session"].commit()
    with Session(database["engine"], autoflush=False) as db:
        order = db.get(WorkOrder, original.id)
        order.priority = "emergency"
        order.status = "QUEUED"
        schedule_notifications(order, NOW, db=db)
        db.commit()
        assert any(job.kind == "emergency_queued" for job in rows(db))
        assert not any(job.kind == "new" for job in rows(db))


def test_waiting_webhook_does_not_block_health_event_loop(app, database, monkeypatch):
    from app.core.config import settings
    from app.core.db import get_db
    from app.modules.auth.models import User
    from app.modules.telegram import service

    monkeypatch.setattr(
        settings, "telegram_webhook_secret", SecretStr("synthetic-secret")
    )
    token = service.issue_link_token(
        database["session"], database["worker"], datetime.now(timezone.utc)
    )
    database["session"].commit()
    entered, health_done = Event(), Event()
    original = service.handle_update

    def observed(*args):
        entered.set()
        return original(*args)

    monkeypatch.setattr(service, "handle_update", observed)

    def independent_db():
        with Session(database["engine"]) as db:
            yield db

    app.dependency_overrides[get_db] = independent_db
    lock_ready = Event()

    def holder():
        with Session(database["engine"]) as db:
            db.scalar(
                select(User).where(User.id == database["worker"].id).with_for_update()
            )
            lock_ready.set()
            health_done.wait(4)
            db.commit()

    holder_thread = Thread(target=holder)
    holder_thread.start()
    assert lock_ready.wait(2)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:5173"
        ) as client:
            pending = asyncio.create_task(
                client.post(
                    "/api/v1/telegram/webhook",
                    json=start(token),
                    headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"},
                )
            )
            began = time.monotonic()

            async def wait_entered():
                while not entered.is_set():
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_entered(), timeout=6)
            response = await client.get("/health/live")
            ordinary = await client.get("/api/v1/telegram/status")
            elapsed = time.monotonic() - began
            health_done.set()
            result = await asyncio.wait_for(pending, timeout=6)
            assert ordinary.status_code == 401
            assert response.status_code == 200
            assert elapsed < 2
            assert result.status_code == 200
            assert result.json()["result"] == "linked"
            assert result.json()["method"] == "sendMessage"

    try:
        asyncio.run(exercise())
    finally:
        health_done.set()
        holder_thread.join(5)


@pytest.mark.parametrize("failure_at", ["handle", "commit"])
def test_webhook_database_failure_rolls_back_and_is_safe_retryable(
    client, database, monkeypatch, caplog, failure_at
):
    from app.core.config import settings
    from app.modules.telegram import service
    from app.modules.telegram.models import TelegramBinding, TelegramUpdate

    monkeypatch.setattr(
        settings, "telegram_webhook_secret", SecretStr("synthetic-secret")
    )
    db = database["session"]
    token = service.issue_link_token(db, database["worker"], datetime.now(timezone.utc))
    db.commit()
    original_handle, original_commit = service.handle_update, db.commit
    marker = "SYNTHETIC_PRIVATE_PARAMETER"
    failure = OperationalError(
        "INSERT synthetic", {"private": marker}, Exception(marker)
    )
    if failure_at == "handle":

        def fail(*args):
            original_handle(*args)
            raise failure

        monkeypatch.setattr(service, "handle_update", fail)
    else:

        def fail():
            raise failure

        monkeypatch.setattr(db, "commit", fail)
    request = dict(
        json=start(token),
        headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"},
    )
    response = client.post("/api/v1/telegram/webhook", **request)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "telegram_unavailable"
    assert marker not in response.text + caplog.text
    assert db.get(TelegramBinding, database["worker"].id) is None
    assert not list(db.scalars(select(TelegramUpdate)))
    monkeypatch.setattr(service, "handle_update", original_handle)
    monkeypatch.setattr(db, "commit", original_commit)
    reply = client.post("/api/v1/telegram/webhook", **request).json()
    assert reply["result"] == "linked" and reply["method"] == "sendMessage"


@pytest.mark.parametrize(
    "kind,label",
    [
        ("new", "Новый наряд"),
        ("reminder", "До срока 30 минут"),
        ("unaccepted", "Наряд не принят"),
        ("overdue", "Срок истёк"),
        ("emergency_queued", "Аварийный наряд в очереди"),
    ],
)
def test_each_notification_kind_has_private_safe_distinct_label(
    database, ready, kind, label
):
    from datetime import timedelta

    from app.workers.notifications import schedule_notifications

    order = order_at(
        database,
        priority="emergency",
        status="QUEUED" if kind == "emergency_queued" else "ISSUED",
    )
    db = database["session"]
    schedule_notifications(order, NOW)
    db.commit()
    jobs = rows(db)
    selected = next(job for job in jobs if job.kind == kind)
    for job in jobs:
        if job.id != selected.id:
            job.status = "CANCELLED"
    db.commit()
    transport = Transport()
    at = selected.due_at + timedelta(microseconds=1)
    deliver(ready, at, client=transport)
    assert len(transport.messages) == 1
    summary = transport.messages[0][1]
    assert summary.startswith(f"{label} — {order.number}\n")
    assert "Приоритет: Аварийный" in summary
    assert "Оборудование: Насос" in summary
    assert "PWA" in summary


def test_rollback_failure_keeps_database_exception_chain_suppressed(monkeypatch):
    from app.core.security import AuthError
    from app.modules.telegram import service
    from app.modules.telegram.router import _webhook_transaction

    failure = OperationalError(
        "synthetic SQL", {}, Exception("synthetic private marker")
    )

    class BrokenSession:
        def rollback(self):
            raise failure

    def fail(*args):
        raise failure

    monkeypatch.setattr(service, "handle_update", fail)
    with pytest.raises(AuthError) as raised:
        _webhook_transaction(BrokenSession(), {})
    assert raised.value.status_code == 503
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
