"""Role-scoped reads and server-derived views shared by commands and routes."""
from datetime import datetime, timezone

from sqlalchemy import func, or_, select

from app.core.security import AuthError, allowed_area_ids, can_access_order
from app.modules.work_orders.models import MaterialUsage, Photo, Submission, WorkOrder, WorkOrderEvent
from app.modules.work_orders.schemas import SubmissionView, WorkOrderDetail, WorkOrderEventView, WorkOrderList, WorkOrderView
from app.modules.work_orders.state_machine import allowed_actions


def responsible_id(order):
    return order.assignee_id or order.responsible_id


def is_responsible(order, actor):
    return actor.role == "worker" and (
        order.assignee_id == actor.id or (
            order.brigade_id is not None and order.brigade_id == actor.brigade_id
            and order.responsible_id == actor.id
        )
    )


def visible_orders(db, actor):
    query = select(WorkOrder)
    if actor.role == "worker":
        condition = WorkOrder.assignee_id == actor.id
        if actor.brigade_id:
            condition = or_(condition, WorkOrder.brigade_id == actor.brigade_id)
        return query.where(condition)
    return query.where(WorkOrder.area_id.in_(allowed_area_ids(db, actor)))


def busy_workers(db):
    return set(db.scalars(select(func.coalesce(WorkOrder.assignee_id, WorkOrder.responsible_id)).where(
        WorkOrder.status == "IN_PROGRESS"
    )))


def view(db, order, actor, *, busy=None, now=None):
    now = now or datetime.now(timezone.utc)
    busy = busy if busy is not None else busy_workers(db)
    values = {name: getattr(order, name) for name in WorkOrderView.model_fields
              if name not in {"is_overdue", "allowed_actions"}}
    return WorkOrderView(**values, is_overdue=(order.due_at < now and order.status not in {
        "SUBMITTED", "AI_REVIEW", "CLOSED", "CANCELLED"
    }), allowed_actions=allowed_actions(
        order.status, actor.role, is_responsible=is_responsible(order, actor),
        has_active_order=actor.id in busy,
    ))


def report_view(db, order, report):
    materials = list(db.scalars(select(MaterialUsage).where(MaterialUsage.submission_id == report.id)
                               .order_by(MaterialUsage.material_id)))
    photos = list(db.scalars(select(Photo).where(Photo.submission_id == report.id).order_by(Photo.id)))
    after = [p.id for p in photos if p.work_order_id == order.id and p.type == "after"]
    missing = []
    if not report.work_description.strip():
        missing.append("work_description")
    if not report.work_code_id:
        missing.append("fault_code_id")
    if not materials and not report.no_materials_used:
        missing.append("materials")
    if materials and report.no_materials_used:
        missing.append("materials_conflict")
    if order.work_type == "emergency" and not after:
        missing.append("after_photo")
    if len(after) != len(photos):
        missing.append("invalid_photos")
    return SubmissionView(
        id=report.id, work_order_id=order.id, revision=report.revision,
        assignment_version=report.assignment_version, worker_id=report.worker_id,
        work_description=report.work_description, fault_code_id=report.work_code_id,
        no_materials_used=report.no_materials_used,
        materials=[{"material_id": m.material_id, "quantity": m.quantity} for m in materials],
        after_photo_ids=after, comment=report.comment, submitted_at=report.submitted_at,
        missing_evidence=missing,
    )


def get_order(db, order_id, actor):
    order = db.get(WorkOrder, order_id)
    if order is None or not can_access_order(db, actor, order):
        raise AuthError(404, "not_found", "Объект не найден")
    report = db.scalar(select(Submission).where(Submission.work_order_id == order.id)
                       .order_by(Submission.revision.desc()).limit(1))
    history = db.scalars(select(WorkOrderEvent).where(WorkOrderEvent.work_order_id == order.id)
                         .order_by(WorkOrderEvent.version))
    return WorkOrderDetail(**view(db, order, actor).model_dump(),
                           events=[WorkOrderEventView.model_validate(e) for e in history],
                           submission=report_view(db, order, report) if report else None)


def list_orders(db, actor, *, offset=0, limit=50, **filters):
    query = visible_orders(db, actor)
    for name, value in filters.items():
        if value is None:
            continue
        if name == "assignee_id":
            query = query.where(func.coalesce(WorkOrder.assignee_id, WorkOrder.responsible_id) == value)
        else:
            query = query.where(getattr(WorkOrder, name) == value)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(WorkOrder.created_at.desc(), WorkOrder.id).offset(offset).limit(limit))
    busy, now = busy_workers(db), datetime.now(timezone.utc)
    return WorkOrderList(items=[view(db, row, actor, busy=busy, now=now) for row in rows],
                         total=total, offset=offset, limit=limit)
