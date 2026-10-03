"""Audit, notification outbox and elapsed-time records in the caller transaction."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.work_orders.models import (
    OutboxEvent,
    WorkOrder,
    WorkOrderEvent,
    WorkOrderInterval,
)


_INTERVAL_KINDS = {
    "IN_PROGRESS": "active",
    "PAUSED": "pause",
    "SUBMITTED": "review",
    "AI_REVIEW": "review",
}


def snapshot(order: WorkOrder) -> dict:
    return {
        "status": order.status,
        "priority": order.priority,
        "assignee_id": str(order.assignee_id) if order.assignee_id else None,
        "brigade_id": str(order.brigade_id) if order.brigade_id else None,
        "responsible_id": str(order.responsible_id) if order.responsible_id else None,
        "version": order.version,
        "assignment_version": order.assignment_version,
        "queue_position": order.queue_position,
        "due_at": order.due_at.isoformat(),
    }


def record_transition(
    db: Session,
    order: WorkOrder,
    *,
    action: str,
    actor_id: UUID | None,
    reason: str | None,
    before: dict,
    now: datetime,
    submission_id: UUID | None = None,
) -> WorkOrderEvent:
    """Write after service locks, validates and updates order/version; never commit."""
    payload = {"before": dict(before), "after": snapshot(order)}
    if submission_id is not None:
        payload["submission_id"] = str(submission_id)
    event = WorkOrderEvent(
        id=uuid4(),
        work_order_id=order.id,
        actor_id=actor_id,
        action=action,
        version=order.version,
        assignment_version=order.assignment_version,
        reason=reason,
        payload=payload,
        occurred_at=now,
    )
    db.add(event)
    # Materialize the event FK before inserting its outbox row: these models
    # deliberately have no ORM relationships defining insert dependency order.
    db.flush()

    event_type = "work_order." + action
    db.add(OutboxEvent(
        event_id=event.id,
        work_order_id=order.id,
        version=order.version,
        assignment_version=order.assignment_version,
        type=event_type,
        payload={
            "event_id": str(event.id),
            "type": event_type,
            "work_order_id": str(order.id),
            "version": order.version,
            "assignment_version": order.assignment_version,
            "occurred_at": now.isoformat(),
        },
        occurred_at=now,
        published_at=None,
    ))

    old_kind = _INTERVAL_KINDS.get(before.get("status"))
    new_kind = _INTERVAL_KINDS.get(order.status)
    if old_kind != new_kind:
        current_interval = db.scalar(
            select(WorkOrderInterval)
            .where(
                WorkOrderInterval.work_order_id == order.id,
                WorkOrderInterval.end_at.is_(None),
            )
            .with_for_update()
        )
        if current_interval is not None:
            current_interval.end_at = now
            # Close the old interval before inserting the next, preserving the
            # unique open-interval invariant throughout the flush.
            db.flush()
        if new_kind is not None:
            db.add(WorkOrderInterval(
                work_order_id=order.id,
                kind=new_kind,
                start_at=now,
                end_at=None,
            ))

    db.flush()
    return event
