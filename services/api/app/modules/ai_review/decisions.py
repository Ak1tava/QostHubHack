"""Master decisions are authorized, idempotent kernel commands."""
from uuid import UUID

from sqlalchemy import select, update

from app.core.security import AuthError
from app.modules.work_orders import queries
from app.modules.work_orders.internal import apply_internal
from app.modules.work_orders.models import AIReview, MasterDecision, Submission
from app.modules.work_orders.schemas import InternalActionCommand
from app.modules.work_orders.service import WorkOrderService, authorize, check_version, lock_order
from app.modules.ai_review.views import current_review
from app.modules.ai_review.jobs_models import ReviewJob


def validate_reason(command, review, status):
    recommended = review.result.get("score") if review else None
    needs_reason = (
        command.decision == "rework" or status == "REWORK"
        or (command.decision == "accept" and (
            review is None or review.verdict not in {"accepted", "accepted_with_notes"}
        )) or command.score != recommended
    )
    if needs_reason and not command.reason:
        raise AuthError(422, "reason_required", "Для решения или изменения оценки требуется объяснение")


class MasterDecisionService(WorkOrderService):
    def apply_master_decision(self, order_id, actor, command, key):
        try:
            record, replay = self._reserve(actor, f"POST /work-orders/{order_id}/decision", command, key)
            order = lock_order(self.db, order_id)
            # Role/access checks always precede replay, independent of mutable status.
            authorize(self.db, order, actor, "close")
            if replay:
                return self._replay(record)
            check_version(order, command.expected_version)
            if order.assignment_version != command.assignment_version:
                raise AuthError(409, "assignment_conflict", "Назначение наряда изменено")
            report = self.db.scalar(select(Submission).where(Submission.work_order_id == order.id)
                                    .order_by(Submission.revision.desc()).limit(1))
            if (report is None or report.id != command.submission_id
                    or report.assignment_version != order.assignment_version
                    or report.worker_id != queries.responsible_id(order)):
                raise AuthError(409, "submission_conflict", "Требуется актуальный отчёт")
            review = self.db.scalar(select(AIReview).where(AIReview.submission_id == report.id))
            if not current_review(order, review):
                review = None
            validate_reason(command, review, order.status)
            decision = MasterDecision(work_order_id=order.id, submission_id=report.id,
                                      master_id=actor.id, decision=command.decision,
                                      reason=command.reason, score=command.score)
            self.db.add(decision)
            self.db.flush()
            action = "request_rework" if command.decision == "rework" else (
                "override_close" if order.status == "REWORK" else "close")
            apply_internal(self.db, order.id, InternalActionCommand(
                action=action, expected_version=command.expected_version,
                assignment_version=command.assignment_version, submission_id=report.id,
                reason=command.reason, decision_id=decision.id,
            ), actor=actor)
            self.db.execute(update(ReviewJob).where(
                ReviewJob.submission_id == report.id,
                ReviewJob.status.in_(['pending', 'running', 'blocked']),
            ).values(status='discarded', last_error='master_decision',
                     lease_token=None, lease_until=None))
            return self._finish(record, order, actor, 200)
        except Exception:
            self.db.rollback()
            raise


def apply_master_decision(order_id: UUID, actor, decision, key, *, db):
    return MasterDecisionService(db).apply_master_decision(order_id, actor, decision, key)
