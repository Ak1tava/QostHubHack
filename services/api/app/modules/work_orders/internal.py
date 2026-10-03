"""Trusted T05/T07 integration entrypoint; flushes, never commits.

The caller creates a submission/review/decision and invokes this kernel in the
same Session transaction, committing all artifacts together or rolling back.
No HTTP route accepts InternalActionCommand or a system actor.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthError
from app.modules.auth.models import User
from app.modules.work_orders import events, queries
from app.modules.work_orders.models import AIReview, MasterDecision, Submission, WorkOrder, WorkOrderEvent
from app.modules.work_orders.schemas import InternalActionCommand
from app.modules.work_orders.service import authorize, check_version, lock_order, lock_workers
from app.modules.work_orders.state_machine import require_action_role, transition


def apply_internal(db: Session, order_id: UUID, command: InternalActionCommand, *, actor: User | None = None) -> WorkOrder:
    order = lock_order(db, order_id)
    lock_workers(db, queries.responsible_id(order))
    role = actor.role if actor is not None else "system"
    if actor is not None:
        authorize(db, order, actor, command.action)
    else:
        require_action_role(command.action, role)
    check_version(order, command.expected_version)
    if order.assignment_version != command.assignment_version:
        raise AuthError(409, "assignment_conflict", "Назначение наряда изменено")
    target = transition(order.status, command.action, role, command.reason)
    # Includes artifacts just written by the calling service, inside its transaction.
    db.flush()
    report = db.scalar(select(Submission).where(Submission.work_order_id == order.id)
                       .order_by(Submission.revision.desc()).limit(1))
    if (report is None or report.id != command.submission_id
            or report.assignment_version != order.assignment_version
            or report.worker_id != queries.responsible_id(order)):
        raise AuthError(409, "submission_conflict", "Отчёт не соответствует текущему назначению")
    if command.action == "submit":
        consumed = db.scalar(select(WorkOrderEvent.id).where(
            WorkOrderEvent.work_order_id == order.id, WorkOrderEvent.action == "submit",
            WorkOrderEvent.payload["submission_id"].as_string() == str(report.id),
        ).limit(1))
        if consumed:
            raise AuthError(409, "submission_conflict", "Требуется новая версия отчёта")
    if role == "system" and command.action == "request_rework":
        review = db.get(AIReview, command.review_id) if command.review_id else None
        if (review is None or review.submission_id != report.id
                or review.order_version != order.version
                or review.assignment_version != order.assignment_version
                or review.verdict != "requires_rework"
                or not review.result.get("findings")):
            raise AuthError(409, "review_conflict", "Нет актуального обоснованного результата проверки")
    if command.action in {"close", "override_close"} or (
        command.action == "request_rework" and role == "master"
    ):
        decision = db.get(MasterDecision, command.decision_id) if command.decision_id else None
        expected = "rework" if command.action == "request_rework" else "accept"
        if (decision is None or decision.work_order_id != order.id
                or decision.submission_id != report.id or decision.master_id != actor.id
                or decision.decision != expected):
            raise AuthError(422, "invalid_decision", "Требуется решение мастера по текущему отчёту")
        if command.action in {"request_rework", "override_close"} and decision.reason != command.reason:
            raise AuthError(422, "invalid_decision", "Причина должна совпадать с решением мастера")
        if command.action in {"close", "override_close"} and queries.report_view(db, order, report).missing_evidence:
            raise AuthError(409, "missing_evidence", "Для закрытия недостаточно доказательств")
    before = events.snapshot(order)
    order.status = target
    order.version += 1
    order.queue_position = None
    events.record_transition(db, order, action=command.action, actor_id=actor.id if actor else None,
                             reason=command.reason, before=before, now=datetime.now(timezone.utc),
                             submission_id=report.id)
    db.flush()
    return order
