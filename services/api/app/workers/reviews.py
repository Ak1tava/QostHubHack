"""Durable review stages; every external call happens after committing its lease."""
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_engine
from app.modules.ai_review.inputs import build_input, read_images
from app.modules.ai_review.jobs_models import ReviewJob, ReviewReceipt
from app.modules.work_orders.internal import apply_internal
from app.modules.work_orders import events
from app.modules.work_orders.models import AIReview, OutboxEvent, Submission, WorkOrder, WorkOrderEvent
from app.modules.work_orders.queries import responsible_id
from app.modules.work_orders.schemas import InternalActionCommand
from app.modules.work_orders.service import lock_order


def utcnow():
    return datetime.now(timezone.utc)


def process_outbox(db, now, *, limit=100):
    events = list(db.scalars(select(OutboxEvent).where(
        ~exists().where(ReviewReceipt.outbox_id == OutboxEvent.id))
        .order_by(OutboxEvent.occurred_at, OutboxEvent.id).limit(limit)
        .with_for_update(skip_locked=True)))
    for event in events:
        if event.type == 'work_order.submit':
            audit = db.get(WorkOrderEvent, event.event_id)
            report_id = audit.payload.get('submission_id') if audit else None
            report = db.get(Submission, UUID(report_id)) if report_id else None
            if report and report.work_order_id == event.work_order_id:
                db.execute(insert(ReviewJob).values(
                    submission_id=report.id, work_order_id=report.work_order_id,
                    submission_revision=report.revision, assignment_version=report.assignment_version,
                    order_version=event.version, next_attempt_at=now,
                ).on_conflict_do_nothing(index_elements=['submission_id']))
        db.add(ReviewReceipt(outbox_id=event.id, consumed_at=now))
    db.flush()
    return len(events)


def claim_job(db, now, *, lease_seconds=180):
    job = db.scalar(select(ReviewJob).where(or_(
        and_(ReviewJob.status.in_(['pending', 'blocked']), ReviewJob.next_attempt_at <= now),
        and_(ReviewJob.status == 'running', ReviewJob.lease_until <= now),
    )).order_by(ReviewJob.next_attempt_at, ReviewJob.id).limit(1)
        .with_for_update(skip_locked=True).execution_options(populate_existing=True))
    if job is None:
        return None
    job.status, job.lease_token = 'running', uuid4()
    job.lease_until = now + timedelta(seconds=lease_seconds)
    job.updated_at = now
    db.flush()
    return job.id, job.lease_token


def finish_job(db, claim, now, *, status, error=None, next_attempt_at=None):
    values = dict(status=status, last_error=error, updated_at=now, lease_token=None, lease_until=None)
    if next_attempt_at is not None:
        values['next_attempt_at'] = next_attempt_at
    result = db.execute(update(ReviewJob).where(
        ReviewJob.id == claim[0], ReviewJob.lease_token == claim[1],
        ReviewJob.status == 'running', ReviewJob.lease_until > now).values(**values))
    return result.rowcount == 1


def _finish_or_rollback(db, claim, now, **values):
    if not finish_job(db, claim, now, **values):
        db.rollback()
        return False
    return True


def _has_lease(job, claim, now):
    return (job.status == 'running' and job.lease_token == claim[1]
            and job.lease_until is not None and job.lease_until > now)


def _locked(db, claim, now, *, require_lease=True):
    original = db.get(ReviewJob, claim[0])
    if original is None:
        return None, None, None
    order = lock_order(db, original.work_order_id)
    job = db.scalar(select(ReviewJob).where(ReviewJob.id == claim[0]).with_for_update()
                    .execution_options(populate_existing=True))
    if require_lease and not _has_lease(job, claim, now):
        return None, None, None
    report = db.scalar(select(Submission).where(Submission.work_order_id == order.id)
                       .order_by(Submission.revision.desc()).limit(1))
    return order, job, report


def _fresh(order, job, report):
    return (order.status in {'SUBMITTED', 'AI_REVIEW'} and report is not None
            and report.id == job.submission_id and report.revision == job.submission_revision
            and report.assignment_version == job.assignment_version == order.assignment_version
            and report.worker_id == responsible_id(order))


def _reset_or_discard(db, order, job, report, claim, clock):
    if not _fresh(order, job, report):
        _finish_or_rollback(db, claim, clock(), status='discarded', error='superseded')
        return False
    if job.snapshot is not None and (order.version != job.order_version or
            build_input(db, order, report).model_dump(mode='json') != job.snapshot['base_input']):
        if job.snapshot_restarts >= settings.ai_review_snapshot_restarts:
            _finish_or_rollback(db, claim, clock(), status='discarded', error='snapshot_restart_limit')
        else:
            job.snapshot_restarts += 1
            job.snapshot, job.stage_outputs, job.stage = None, {}, 'prepare'
            job.order_version = order.version
            _finish_or_rollback(db, claim, clock(), status='pending', error='snapshot_changed', next_attempt_at=clock())
        return False
    return True


def _save_final(db, order, job, report, claim, clock, result, plan=None, *, outcome=None, call_id=None):
    from app.modules.ai_review.rules import RULES_VERSION
    if not _has_lease(job, claim, clock()):
        db.rollback()
        return False
    now = clock()
    if plan and plan.model == settings.ai_light_model:
        result = result.model_copy(update={'limitations': [*result.limitations,
                                  'Проверен только текст; визуальное подтверждение не выполнялось.']})
    review = db.scalar(select(AIReview).where(AIReview.submission_id == report.id))
    if review is None:
        calls = job.calls or []
        is_mock = outcome.is_mock if outcome is not None else any(c.get('is_mock', False) for c in calls)
        final_outcome = dict(call_id=call_id,
                             response_id=outcome.response_id if outcome is not None else None,
                             error_code=outcome.error_code if outcome is not None else None,
                             is_mock=is_mock)
        review = AIReview(submission_id=report.id, order_version=order.version,
                          assignment_version=order.assignment_version, verdict=result.verdict,
                          result=result.model_dump(mode='json'), model=plan.model if plan else 'rules',
                          prompt_version=plan.prompt_version if plan else 'rules-v1',
                          latency_ms=sum(call.get('latency_ms') or 0 for call in calls),
                          usage={'calls': calls, 'is_mock': is_mock, 'final_outcome': final_outcome,
                                 'rules_version': RULES_VERSION, 'snapshot_restarts': job.snapshot_restarts})
        db.add(review)
        db.flush()
    if result.verdict == 'requires_rework':
        reason = '; '.join(f.message for f in result.findings)[:4000] or 'Требуется дополнить доказательства'
        apply_internal(db, order.id, InternalActionCommand(
            action='request_rework', expected_version=order.version,
            assignment_version=order.assignment_version, submission_id=report.id,
            review_id=review.id, reason=reason))
    else:
        before = events.snapshot(order)
        order.version += 1
        review.order_version = order.version
        events.record_transition(db, order, action='review_completed', actor_id=None,
                                 reason=None, before=before, now=now, submission_id=report.id)
    job.stage = 'final'
    # Kernel worker locks and flushes can block beyond the lease. Roll back every
    # business artifact unless the final SQL fence still succeeds at commit time.
    return _finish_or_rollback(db, claim, clock(), status='completed')


def process_once(engine, *, provider=None, api_key=None, clock=utcnow):
    """Process one persisted stage. Inject provider for genuine integration tests."""
    from app.modules.ai_review.rules import RULES_VERSION, assess_rules, RuleAssessment
    from app.modules.ai_review.schemas import ProviderOutcome, ReviewInput, StagePlan
    from app.modules.ai_review.service import can_escalate, escalation_plan, evaluate_stage, finalize_result, select_primary
    from app.modules.ai_review.provider import OpenAIReviewProvider

    with Session(engine, expire_on_commit=False) as db:
        process_outbox(db, clock())
        claim = claim_job(db, clock(), lease_seconds=settings.ai_review_lease_seconds)
        db.commit()
        if claim is None:
            return False
        order, job, report = _locked(db, claim, clock())
        if job is None:
            db.commit()
            return True
        if not _has_lease(job, claim, clock()):
            db.rollback()
            return True
        if not _reset_or_discard(db, order, job, report, claim, clock):
            db.commit()
            return True
        if order.status == 'SUBMITTED':
            apply_internal(db, order.id, InternalActionCommand(
                action='begin_review', expected_version=order.version,
                assignment_version=order.assignment_version, submission_id=report.id))
            job.order_version = order.version
        if provider is None and not api_key:
            _finish_or_rollback(db, claim, clock(), status='blocked', error='api_key_missing',
                       next_attempt_at=clock() + timedelta(seconds=30))
            db.commit()
            return True
        if job.stage == 'prepare':
            base = build_input(db, order, report)
            review_input, _ = read_images(db, report, base, settings.photo_storage_path)
            rules = assess_rules(review_input)
            plan = select_primary(review_input, rules)
            job.snapshot = {'base_input': base.model_dump(mode='json'),
                            'input': review_input.model_dump(mode='json'),
                            'rules': rules.model_dump(mode='json'), 'plan': plan.model_dump(mode='json')}
            job.order_version = order.version
            job.stage = 'primary'
            if rules.result is not None:
                _save_final(db, order, job, report, claim, clock, rules.result)
            else:
                _finish_or_rollback(db, claim, clock(), status='pending', next_attempt_at=clock())
            db.commit()
            return True
        if job.stage not in {'primary', 'escalation'} or job.snapshot is None:
            _finish_or_rollback(db, claim, clock(), status='discarded', error='invalid_stage')
            db.commit()
            return True
        review_input = ReviewInput.model_validate(job.snapshot['input'])
        rules = RuleAssessment.model_validate(job.snapshot['rules'])
        primary = StagePlan.model_validate(job.snapshot['plan'])
        plan = primary if job.stage == 'primary' else escalation_plan()
        previous = ProviderOutcome.model_validate(job.stage_outputs['primary']) if job.stage == 'escalation' else None
        if job.attempts >= 3:
            outcome = ProviderOutcome(result=None, error_code='attempt_limit')
            _save_final(db, order, job, report, claim, clock,
                        finalize_result(review_input, rules, outcome), plan, outcome=outcome)
            db.commit()
            return True
        current_input, images = read_images(db, report, review_input, settings.photo_storage_path)
        current_rules = assess_rules(current_input)
        if current_rules.result is not None:
            _save_final(db, order, job, report, claim, clock, current_rules.result)
            db.commit()
            return True
        if not _has_lease(job, claim, clock()):
            db.rollback()
            return True
        job.attempts += 1  # Persist before I/O: crashes cannot cause unbounded billed calls.
        stage = job.stage
        call_id = str(uuid4())
        job.calls = [*job.calls, dict(call_id=call_id, lease_token=str(claim[1]), status='started',
                                    stage=stage, model=plan.model, reasoning=plan.reasoning,
                                    prompt_version=plan.prompt_version, rules_version=RULES_VERSION,
                                    snapshot_restart=job.snapshot_restarts)]
        db.commit()
        if not _has_lease(job, claim, clock()):
            return True
    if provider is None:
        provider = OpenAIReviewProvider(api_key, timeout=settings.ai_request_timeout_seconds,
                                        max_output_tokens=settings.ai_max_output_tokens,
                                        complex_max_output_tokens=settings.ai_complex_max_output_tokens)
    outcome = evaluate_stage(review_input, provider, plan, images=images, previous=previous)
    with Session(engine, expire_on_commit=False) as db:
        order, job, report = _locked(db, claim, clock(), require_lease=False)
        if job is None:
            db.commit()
            return True
        # A lost lease may only finish its own pre-reserved cost trace. Business
        # stage/status/output writes remain fenced by the current token below.
        job.calls = [dict(call, status='completed', **outcome.model_dump(
            mode='json', exclude={'result', 'conflict_refs'}))
            if call.get('call_id') == call_id and call.get('lease_token') == str(claim[1]) else call
            for call in job.calls]
        # Costs survive a later business rollback when locks/flushes outlive the
        # lease. The next transaction rechecks current authority and snapshot.
        db.commit()
        order, job, report = _locked(db, claim, clock())
        if job is None:
            db.commit()
            return True
        if not _has_lease(job, claim, clock()):
            db.commit()
            return True
        if not _reset_or_discard(db, order, job, report, claim, clock):
            db.commit()
            return True
        job.stage_outputs = {**job.stage_outputs, stage: outcome.model_dump(mode='json')}
        if outcome.retryable and job.attempts < 3:
            delay = max(2 ** job.attempts, outcome.retry_after_seconds or 0)
            _finish_or_rollback(db, claim, clock(), status='pending', error=outcome.error_code,
                       next_attempt_at=clock() + timedelta(seconds=delay))
        elif (stage == 'primary' and primary.model == settings.ai_model
              and job.attempts < 3 and can_escalate(review_input, outcome)):
            job.stage = 'escalation'
            _finish_or_rollback(db, claim, clock(), status='pending', next_attempt_at=clock())
        else:
            diagnostics = {}
            result = finalize_result(review_input, rules, outcome, diagnostics=diagnostics)
            # Rejected provider output produces a server fallback, even if the request succeeded.
            final_call_id = call_id if not diagnostics['rejection_reasons'] else None
            _save_final(db, order, job, report, claim, clock, result, plan,
                        outcome=outcome, call_id=final_call_id)
        db.commit()
    return True


def main():
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    engine = get_engine()
    while True:
        process_once(engine, api_key=key)
        time.sleep(settings.ai_review_poll_seconds)


if __name__ == '__main__':
    main()
