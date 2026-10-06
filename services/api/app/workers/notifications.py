"""Outbox scheduling and fresh, permission-checked, persisted Telegram delivery."""

import time
from datetime import timedelta

from sqlalchemy import case, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import object_session, sessionmaker

from app.core.config import settings
from app.core.db import get_engine
from app.core.security import can_access_order
from app.modules.auth.models import User
from app.modules.telegram.client import TelegramClient, TelegramError, https_url
from app.modules.telegram.models import (
    Notification,
    NotificationReceipt,
    TelegramBinding,
)
from app.modules.work_orders.models import OutboxEvent, WorkOrder, WorkOrderEvent
from app.modules.work_orders.queries import responsible_id
from app.workers.jobs import MAX_ATTEMPTS, claim_job, finish_job

ONGOING = {"ISSUED", "ACCEPTED", "QUEUED", "IN_PROGRESS", "PAUSED", "REWORK"}
UNFINISHED = {"PENDING", "RETRY", "BLOCKED", "LEASED"}
KIND_LABELS = {
    "new": "Новый наряд",
    "reminder": "До срока 30 минут",
    "unaccepted": "Наряд не принят",
    "overdue": "Срок истёк",
    "emergency_queued": "Аварийный наряд в очереди",
}


def _fresh(db, order, job):
    if order is None or job.assignment_version != order.assignment_version:
        return False
    master_kind = job.kind in {"unaccepted", "emergency_queued"} or (
        job.kind == "overdue" and job.recipient_id == order.master_id
    )
    if job.recipient_id != (order.master_id if master_kind else responsible_id(order)):
        return False
    recipient = db.get(User, job.recipient_id)
    if (
        not recipient
        or not recipient.is_active
        or not can_access_order(db, recipient, order)
    ):
        return False
    if master_kind and recipient.role != "master":
        return False
    if job.kind in {"new", "unaccepted"}:
        return order.status == "ISSUED"
    if job.kind == "emergency_queued":
        return order.status == "QUEUED" and order.priority == "emergency"
    return order.status in ONGOING


def _origin(db, order):
    return (
        db.scalar(
            select(WorkOrderEvent.occurred_at)
            .where(
                WorkOrderEvent.work_order_id == order.id,
                WorkOrderEvent.assignment_version == order.assignment_version,
            )
            .order_by(WorkOrderEvent.version)
            .limit(1)
        )
        or order.created_at
    )


def _upsert(db, order, kind, recipient, due):
    key = f"{order.id}:{order.assignment_version}:{recipient}:{kind}"
    statement = insert(Notification).values(
        kind=kind,
        work_order_id=order.id,
        assignment_version=order.assignment_version,
        recipient_id=recipient,
        due_at=due,
        next_attempt_at=due,
        dedup_key=key,
        attempts=0,
        status="PENDING",
    )
    if kind == "unaccepted":
        statement = statement.on_conflict_do_update(
            index_elements=[Notification.dedup_key],
            set_={
                "due_at": due,
                "next_attempt_at": case(
                    (Notification.status == "PENDING", due),
                    else_=func.greatest(Notification.next_attempt_at, due),
                ),
            },
            where=Notification.status.in_(["PENDING", "RETRY", "BLOCKED"]),
        )
    else:
        statement = statement.on_conflict_do_nothing(
            index_elements=[Notification.dedup_key]
        )
    db.execute(statement)


def schedule_notifications(order, now, *, db=None):
    """Flush-only; caller commits. The order must be attached or db supplied."""
    db = db if db is not None else object_session(order)
    if db is None:
        raise ValueError("notification_session_required")
    # Preserve caller changes even when the production Session disables autoflush.
    # Then refresh the identity map from the row protected by the lock.
    db.flush()
    order = db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == order.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    origin = _origin(db, order)
    for job in db.scalars(
        select(Notification).where(
            Notification.work_order_id == order.id, Notification.status.in_(UNFINISHED)
        )
    ):
        if not _fresh(db, order, job) or (
            job.kind == "reminder" and now >= order.due_at
        ):
            job.status, job.lease_token, job.lease_until = "CANCELLED", None, None
    db.flush()
    if order.status not in ONGOING:
        return
    recipient = responsible_id(order)
    master = db.get(User, order.master_id)
    master_ok = (
        master and master.role == "master" and can_access_order(db, master, order)
    )
    if order.status == "ISSUED":
        _upsert(db, order, "new", recipient, origin)
        if master_ok:
            _upsert(
                db,
                order,
                "unaccepted",
                master.id,
                origin + timedelta(minutes=3 if order.priority == "emergency" else 10),
            )
    if order.status == "QUEUED" and order.priority == "emergency" and master_ok:
        _upsert(db, order, "emergency_queued", master.id, now)
    reminder_at = order.due_at - timedelta(minutes=30)
    if reminder_at > now:
        _upsert(db, order, "reminder", recipient, reminder_at)
    _upsert(db, order, "overdue", recipient, order.due_at)
    if master_ok:
        _upsert(db, order, "overdue", master.id, order.due_at)
    db.flush()


def process_outbox(db, now, *, limit=100):
    """Dedicated receipts preserve published_at for other future consumers."""
    events = list(
        db.scalars(
            select(OutboxEvent)
            .where(~exists().where(NotificationReceipt.outbox_id == OutboxEvent.id))
            .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for event in events:
        order = db.get(WorkOrder, event.work_order_id)
        if order:
            schedule_notifications(order, now, db=db)
        db.add(NotificationReceipt(outbox_id=event.id, processed_at=now))
    db.flush()
    return len(events)


def _prepare(db, claim, clock):
    job_id, token = claim
    job = db.get(Notification, job_id)
    # Consistent lock order: order -> job -> recipient. NO KEY UPDATE permits
    # actor FK KEY SHARE held by lifecycle commands before they lock the order.
    order = db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == job.work_order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    job = db.scalar(
        select(Notification)
        .where(Notification.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    recipient = db.scalar(
        select(User)
        .where(User.id == job.recipient_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    now = clock()  # Locks may have waited; do not use a captured batch timestamp.
    if job.status != "LEASED" or job.lease_token != token or job.lease_until <= now:
        return None
    if not _fresh(db, order, job) or (job.kind == "reminder" and now >= order.due_at):
        finish_job(db, *claim, status="CANCELLED", now=now)
        return None
    if job.kind == "unaccepted":
        due = _origin(db, order) + timedelta(
            minutes=3 if order.priority == "emergency" else 10
        )
        job.due_at = due
        if now < due:
            finish_job(
                db,
                *claim,
                status="RETRY" if job.attempts else "PENDING",
                now=now,
                next_attempt_at=max(due, job.next_attempt_at),
            )
            return None
    binding = db.get(TelegramBinding, recipient.id)
    blocked = "missing_binding" if binding is None else None
    if not settings.telegram_bot_token:
        blocked = "missing_configuration"
    elif not https_url(settings.public_base_url):
        blocked = "invalid_public_url"
    if blocked:
        finish_job(
            db,
            *claim,
            status="BLOCKED",
            now=now,
            error=blocked,
            next_attempt_at=now + timedelta(seconds=60),
        )
        return None
    if job.attempts >= MAX_ATTEMPTS:
        finish_job(db, *claim, status="FAILED", now=now, error="retry_exhausted")
        return None
    job.attempts += 1
    db.flush()
    url = settings.public_base_url.rstrip("/") + f"/orders/{order.id}"
    summary = f"{KIND_LABELS[job.kind]}\n{order.number} | {order.priority} | {order.due_at.isoformat()}"
    return binding.private_chat_id, summary, url, job.attempts


def send_due_notifications(
    now, *, session_factory=None, client=None, limit=100, clock=None
):
    """Recoverable at-least-once I/O, with no database locks held over network.

    Tests can freeze/advance clock; production uses elapsed time from business now.
    Attempts are committed before I/O. A timeout or process crash can still mean
    Telegram accepted a message; external delivery cannot be exactly-once.
    """
    started = time.monotonic()
    clock = clock or (lambda: now + timedelta(seconds=time.monotonic() - started))
    session_factory = session_factory or sessionmaker(
        get_engine(), expire_on_commit=False
    )
    client = client or TelegramClient()
    processed = 0
    for _ in range(limit):
        with session_factory() as db:
            claim = claim_job(db, clock())
            db.commit()
            if claim is None:
                break
            prepared = _prepare(db, claim, clock)
            db.commit()  # Release API locks and persist attempt before external I/O.
        if prepared is not None:
            chat, summary, url, attempts = prepared
            failure = None
            try:
                client.send_message(chat, summary, url)
            except TelegramError as error:
                failure = error
            with session_factory() as db:
                completed_at = clock()
                if failure is None:
                    finish_job(db, *claim, status="SENT", now=completed_at)
                else:
                    terminal = (
                        failure.code
                        in {"bot_blocked", "telegram_rejected", "invalid_response"}
                        or attempts >= MAX_ATTEMPTS
                    )
                    delay = failure.retry_after or min(300, 5 * 2 ** (attempts - 1))
                    finish_job(
                        db,
                        *claim,
                        status="FAILED" if terminal else "RETRY",
                        now=completed_at,
                        error=failure.code,
                        next_attempt_at=completed_at + timedelta(seconds=delay),
                    )
                db.commit()
        processed += 1
    return processed
