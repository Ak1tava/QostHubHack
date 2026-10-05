"""Atomic PostgreSQL lease claims and token-fenced acknowledgements."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update

from app.modules.telegram.models import Notification

LEASE_SECONDS = 60
MAX_ATTEMPTS = 5


def claim_job(db, now):
    ready = or_(
        and_(
            Notification.status.in_(["PENDING", "RETRY", "BLOCKED"]),
            Notification.next_attempt_at <= now,
        ),
        and_(Notification.status == "LEASED", Notification.lease_until <= now),
    )
    semantic_due = or_(
        and_(Notification.kind == "overdue", Notification.due_at < now),
        and_(Notification.kind != "overdue", Notification.due_at <= now),
    )
    job = db.scalar(
        select(Notification)
        .where(ready, semantic_due)
        .order_by(Notification.next_attempt_at, Notification.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if job is None:
        return None
    job.status, job.lease_token = "LEASED", uuid4()
    job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    db.flush()
    return job.id, job.lease_token


def finish_job(
    db, job_id, lease_token, *, status, now, error=None, next_attempt_at=None
):
    values = dict(status=status, last_error=error, lease_token=None, lease_until=None)
    if next_attempt_at is not None:
        values["next_attempt_at"] = next_attempt_at
    if status == "SENT":
        values["sent_at"] = now
    result = db.execute(
        update(Notification)
        .where(
            Notification.id == job_id,
            Notification.status == "LEASED",
            Notification.lease_token == lease_token,
            Notification.lease_until > now,
        )
        .values(**values)
    )
    return result.rowcount == 1
