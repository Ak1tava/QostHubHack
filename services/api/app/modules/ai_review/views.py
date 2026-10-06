"""Current-submission review information; never expose provider input or images."""
from sqlalchemy import select

from app.modules.ai_review.jobs_models import ReviewJob
from app.modules.work_orders.models import AIReview, MasterDecision
from app.modules.work_orders.schemas import AIReviewView, MasterDecisionView


def current_review(order, review):
    if review is None or review.assignment_version != order.assignment_version:
        return False
    if order.status in {'CLOSED', 'CANCELLED'}:
        return True  # Historical result remains visible after the final transition.
    expected = order.version - (1 if order.status == 'REWORK' else 0)
    return review.order_version == expected


def review_detail(db, order, report, actor, report_view):
    if (report is None or report.assignment_version != order.assignment_version
            or report.worker_id != (order.assignee_id or order.responsible_id)):
        return {}
    review = db.scalar(select(AIReview).where(AIReview.submission_id == report.id))
    if not current_review(order, review):
        review = None
    job = db.scalar(select(ReviewJob).where(ReviewJob.submission_id == report.id))
    decision = db.scalar(select(MasterDecision).where(MasterDecision.submission_id == report.id)
                         .order_by(MasterDecision.decided_at.desc(), MasterDecision.id).limit(1))
    allowed = []
    if actor.role == "master":
        if order.status == "AI_REVIEW":
            allowed = ["rework"] if report_view.missing_evidence else ["accept", "rework"]
        elif order.status == "REWORK" and not report_view.missing_evidence:
            allowed = ["accept"]
    return dict(
        ai_review=AIReviewView(id=review.id, submission_id=review.submission_id,
                              verdict=review.verdict, result=review.result, model=review.model,
                              prompt_version=review.prompt_version, created_at=review.created_at,
                              is_mock=bool(review.usage.get("is_mock"))) if review else None,
        master_decision=MasterDecisionView.model_validate(decision) if decision else None,
        review_status=job.status if job else None, allowed_decisions=allowed,
    )
