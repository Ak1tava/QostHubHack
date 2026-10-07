from types import SimpleNamespace

import pytest

from app.core.security import AuthError


@pytest.mark.parametrize('decision,score,verdict,ai_score,reason,allowed', [
    ('accept', 4, 'accepted', 4, None, True),
    ('accept', 5, 'accepted', 4, None, False),
    ('accept', None, None, None, None, False),
    ('accept', None, None, None, 'Ручная проверка', True),
    ('accept', 3, 'requires_rework', 3, None, False),
    ('rework', None, 'accepted', 4, None, False),
    ('rework', None, 'accepted', 4, 'Недостаток', True),
])
def test_master_reason_policy(decision, score, verdict, ai_score, reason, allowed):
    from app.modules.ai_review.decisions import validate_reason
    command = SimpleNamespace(decision=decision, score=score, reason=reason)
    review = SimpleNamespace(verdict=verdict, result={'score': ai_score}) if verdict else None
    if allowed:
        validate_reason(command, review, 'AI_REVIEW')
    else:
        with pytest.raises(AuthError):
            validate_reason(command, review, 'AI_REVIEW')


def test_review_job_unique_submission_and_independent_receipt():
    from app.modules.ai_review.jobs_models import ReviewJob, ReviewReceipt
    assert ReviewJob.__table__.c.submission_id.unique
    assert ReviewReceipt.__tablename__ == 'review_receipts'
    assert ReviewReceipt.__table__.c.outbox_id.primary_key


@pytest.mark.parametrize('status,version,review_version,valid', [
    ('AI_REVIEW',3,3,True), ('AI_REVIEW',4,3,False),
    ('REWORK',4,3,True), ('REWORK',5,3,False), ('CLOSED',4,3,True),
])
def test_only_current_review_can_supply_master_recommendation(status,version,review_version,valid):
    from app.modules.ai_review.views import current_review
    order = SimpleNamespace(status=status,version=version,assignment_version=1)
    review = SimpleNamespace(order_version=review_version,assignment_version=1)
    assert current_review(order, review) is valid
