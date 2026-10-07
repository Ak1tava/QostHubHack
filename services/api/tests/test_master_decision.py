from uuid import UUID

import pytest
from sqlalchemy import select

from app.modules.work_orders.models import AIReview, IdempotencyRecord, MasterDecision, WorkOrder, WorkOrderEvent
from conftest import sign_in
from test_review_worker import submitted
from work_order_helpers import BASE, count_rows, headers


def ready(client, database, *, review=False, **changes):
    order, report = submitted(client, database, **changes)
    db = database['session']
    saved = db.get(WorkOrder, UUID(order['id']))
    saved.status = 'AI_REVIEW'
    saved.version += 1
    if review:
        db.add(AIReview(submission_id=UUID(report['id']), order_version=saved.version,
                        assignment_version=1, verdict='accepted',
                        result=dict(verdict='accepted', score=4, findings=[], missing_evidence=[], limitations=[]),
                        model='mock', prompt_version='test', usage={'is_mock': True}))
    db.commit()
    return order, dict(decision='accept', submission_id=report['id'], expected_version=saved.version,
                       assignment_version=1, score=4 if review else None, reason=None)


def decision(client, token, order, body, key='decision'):
    return client.post(f"{BASE}/{order['id']}/decision", json=body, headers=headers(token, key))


def test_manual_accept_requires_reason_then_is_atomic_and_replayable(client, database):
    order, body = ready(client, database)
    token = sign_in(client, 'master')
    assert decision(client, token, order, body).status_code == 422
    assert count_rows(database['session'], MasterDecision) == 0
    body['reason'] = 'Проверено мастером на месте'
    first = decision(client, token, order, body)
    assert first.status_code == 200, first.text
    assert first.json()['status'] == 'CLOSED'
    assert decision(client, token, order, body).json() == first.json()
    assert count_rows(database['session'], MasterDecision) == 1
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert detail['master_decision']['reason'] == body['reason']
    assert detail['allowed_decisions'] == []


@pytest.mark.parametrize('login,status', [('worker',403), ('outsider',404)])
def test_decision_permissions(client, database, login, status):
    order, body = ready(client, database, review=True)
    assert decision(client, sign_in(client, login), order, body).status_code == status
    assert count_rows(database['session'], MasterDecision) == 0


@pytest.mark.parametrize('change,status', [({'expected_version':1},409), ({'assignment_version':2},409),
                                        ({'score':5},422), ({'score':0},422), ({'score':6},422),
                                        ({'decision':'rework'},422)])
def test_invalid_decision_leaves_no_artifacts(client, database, change, status):
    order, body = ready(client, database, review=True)
    before = count_rows(database['session'], WorkOrderEvent)
    body.update(change)
    result = decision(client, sign_in(client, 'master'), order, body)
    assert result.status_code == status, result.text
    assert count_rows(database['session'], MasterDecision) == 0
    assert count_rows(database['session'], WorkOrderEvent) == before


def test_incomplete_emergency_report_cannot_close_even_with_reason(client, database):
    order, body = ready(client, database, work_type='emergency')
    body['reason'] = 'Ручная проверка'
    assert decision(client, sign_in(client, 'master'), order, body).status_code == 409
    assert count_rows(database['session'], MasterDecision) == 0


def test_rework_requires_reason_and_current_master_access_not_authorship(client, database):
    from work_order_helpers import add_user
    second = add_user(database, 'othermaster', role='master')
    order, body = ready(client, database, review=True)
    body.update(decision='rework', reason='Исправить соединение')
    response = decision(client, sign_in(client, 'othermaster'), order, body)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'REWORK'
    assert database['session'].scalar(select(MasterDecision)).master_id == second.id


def test_decision_replay_rechecks_revoked_area_access(client, database):
    from app.modules.auth.models import UserArea
    order, body = ready(client, database, review=True)
    token = sign_in(client, 'master')
    assert decision(client, token, order, body).status_code == 200
    db = database['session']
    db.delete(db.get(UserArea, (database['master'].id, database['area'].id)))
    db.commit()
    assert decision(client, token, order, body).status_code == 404


def test_decision_requires_csrf(client, database):
    order, body = ready(client, database, review=True)
    sign_in(client, 'master')
    result = client.post(f"{BASE}/{order['id']}/decision", json=body,
                         headers={'Idempotency-Key':'no-csrf'})
    assert result.status_code == 403
    assert count_rows(database['session'], MasterDecision) == 0


def test_decision_failure_rolls_back_kernel_and_idempotency(client, database, monkeypatch):
    import app.modules.ai_review.decisions as module
    original = module.apply_internal
    def fail_after_transition(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('forced rollback')
    order, body = ready(client, database, review=True)
    db = database['session']
    events, keys = count_rows(db, WorkOrderEvent), count_rows(db, IdempotencyRecord)
    monkeypatch.setattr(module, 'apply_internal', fail_after_transition)
    with pytest.raises(RuntimeError, match='forced rollback'):
        decision(client, sign_in(client, 'master'), order, body)
    assert count_rows(db, MasterDecision) == 0
    assert count_rows(db, WorkOrderEvent) == events
    assert count_rows(db, IdempotencyRecord) == keys
    assert db.get(WorkOrder, UUID(order['id']), populate_existing=True).status == 'AI_REVIEW'


def test_master_decision_fences_running_job_immediately(client, database):
    from app.modules.ai_review.jobs_models import ReviewJob
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    order, body = ready(client, database, review=True)
    db = database['session']
    job = ReviewJob(work_order_id=UUID(order['id']), submission_id=UUID(body['submission_id']),
                    order_version=body['expected_version'], assignment_version=1,
                    submission_revision=1, status='running', lease_token=uuid4(),
                    lease_until=datetime.now(timezone.utc)+timedelta(seconds=180))
    db.add(job)
    db.commit()
    assert decision(client, sign_in(client, 'master'), order, body).status_code == 200
    db.refresh(job)
    assert job.status == 'discarded' and job.lease_token is None
