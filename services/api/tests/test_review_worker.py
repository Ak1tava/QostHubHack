from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.modules.work_orders.models import AIReview, Submission, WorkOrder
from app.modules.ai_review.jobs_models import ReviewJob, ReviewReceipt
from conftest import sign_in
from test_submissions import payload, send
from work_order_helpers import BASE, count_rows, seed_order


def submitted(client, database, **changes):
    order = seed_order(database, 'IN_PROGRESS', **changes)
    result = send(client, sign_in(client), order, payload(database))
    assert result.status_code == 201, result.text
    return order, result.json()


def test_outbox_receipt_and_submission_job_are_independent_and_unique(client, database):
    from app.workers.reviews import process_outbox
    order, report = submitted(client, database)
    db = database['session']
    now = datetime.now(timezone.utc)
    assert process_outbox(db, now) == 1
    db.commit()
    assert process_outbox(db, now) == 0
    assert count_rows(db, ReviewReceipt) == count_rows(db, ReviewJob) == 1
    job = db.scalar(select(ReviewJob))
    assert str(job.submission_id) == report['id']


def test_without_key_begin_review_and_blocked_without_fake_review(client, database):
    from app.workers.reviews import process_once
    order, report = submitted(client, database)
    assert process_once(database['engine'], provider=None, api_key=None)
    db = database['session']
    db.expire_all()
    assert db.get(WorkOrder, UUID(order['id'])).status == 'AI_REVIEW'
    assert db.scalar(select(ReviewJob)).status == 'blocked'
    assert count_rows(db, AIReview) == 0
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert detail['review_status'] == 'blocked'
    assert detail['allowed_decisions'] == []  # worker


def test_expired_lease_cannot_publish_after_reclaim(client, database):
    from app.workers.reviews import process_outbox, claim_job, finish_job
    submitted(client, database)
    db = database['session']
    now = datetime.now(timezone.utc)
    process_outbox(db, now)
    first = claim_job(db, now, lease_seconds=1)
    db.commit()
    second = claim_job(db, now + timedelta(seconds=2), lease_seconds=1)
    assert first[0] == second[0] and first[1] != second[1]
    assert not finish_job(db, first, now + timedelta(seconds=2), status='completed')
    assert finish_job(db, second, now + timedelta(seconds=2), status='discarded')


@pytest.mark.parametrize('status', ['CANCELLED', 'CLOSED', 'REWORK', 'IN_PROGRESS'])
def test_stale_status_discarded_before_provider(client, database, status):
    from app.workers.reviews import process_once
    order, report = submitted(client, database)
    db = database['session']
    db.get(WorkOrder, UUID(order['id'])).status = status
    db.commit()
    process_once(database['engine'], api_key=None)
    db.expire_all()
    assert db.scalar(select(ReviewJob)).status == 'discarded'
    assert count_rows(db, AIReview) == 0


class Provider:
    def __init__(self, callback=None, outcomes=None):
        self.callback, self.calls, self.outcomes = callback, [], outcomes or []

    def review(self, value, plan, *, images, previous=None):
        from app.modules.ai_review.schemas import Finding, ProviderOutcome, ReviewResult
        self.calls.append((value, plan, previous))
        if self.callback:
            self.callback()
        after_refs = [p['id'] for p in value.photo_refs if p.get('phase') == 'after' and p['id'] in images]
        return self.outcomes.pop(0) if self.outcomes else ProviderOutcome(
            result=ReviewResult(verdict='accepted', score=4,
                findings=[Finding(code='work_matches_problem',severity='info',
                                  message='Выполненная работа соответствует заявке',
                                  evidence_refs=['problem','work_description', *after_refs])],
                missing_evidence=[], limitations=[]),
            is_mock=True, usage={'input_tokens':10, 'output_tokens':5}, latency_ms=7,
            legible_refs=after_refs)


def drive(database, provider, *, ticks=8, clock=None, start=None):
    from app.workers.reviews import process_once
    now = [start or datetime.now(timezone.utc)]
    for _ in range(ticks):
        process_once(database['engine'], provider=provider, clock=clock or (lambda: now[0]))
        now[0] += timedelta(seconds=3601)
    database['session'].expire_all()


def test_real_pipeline_persists_result_and_never_closes(client, database):
    order, _ = submitted(client, database)
    provider = Provider()
    drive(database, provider)
    db = database['session']
    review = db.scalar(select(AIReview))
    assert review.verdict == 'accepted' and review.result['score'] == 4
    assert review.usage['is_mock'] is True and len(review.usage['calls']) == 1
    assert review.usage['calls'][0]['usage']['input_tokens'] == 10
    assert count_rows(db, AIReview) == 1
    assert db.get(WorkOrder, UUID(order['id'])).status == 'AI_REVIEW'
    assert db.scalar(select(ReviewJob)).status == 'completed'
    assert provider.calls[0][1].model == 'gpt-6-luna'
    assert any('текст' in limit for limit in review.result['limitations'])
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert detail['ai_review']['source'] == 'mock'
    assert 'usage' not in detail['ai_review']


def test_missing_emergency_photo_reworks_without_model_io(client, database):
    order, _ = submitted(client, database, work_type='emergency')
    provider = Provider()
    drive(database, provider)
    db = database['session']
    assert provider.calls == []
    assert db.get(WorkOrder, UUID(order['id'])).status == 'REWORK'
    assert db.scalar(select(AIReview)).verdict == 'requires_rework'


def test_provider_call_has_no_database_transaction_and_late_cancel_is_discarded(client, database):
    from sqlalchemy.orm import Session
    order, _ = submitted(client, database)
    def cancel():
        # A genuinely separate connection can acquire the order row while model I/O runs.
        with Session(database['engine']) as db:
            db.execute(__import__('sqlalchemy').text("SET LOCAL lock_timeout='500ms'"))
            saved = db.scalar(select(WorkOrder).where(WorkOrder.id == UUID(order['id'])).with_for_update())
            saved.status = 'CANCELLED'
            saved.version += 1
            db.commit()
    provider = Provider(callback=cancel)
    drive(database, provider)
    assert count_rows(database['session'], AIReview) == 0
    job = database['session'].scalar(select(ReviewJob))
    assert job.status == 'discarded' and len(job.calls) == 1


def test_snapshot_change_restarts_and_retains_prior_billed_usage(client, database):
    from sqlalchemy.orm import Session
    order, _ = submitted(client, database)
    def reprioritize_once():
        if len(provider.calls) != 1:
            return
        with Session(database['engine']) as db:
            saved = db.get(WorkOrder, UUID(order['id']))
            saved.priority = 'high'
            saved.version += 1
            db.commit()
    provider = Provider(callback=reprioritize_once)
    drive(database, provider)
    db = database['session']
    job = db.scalar(select(ReviewJob))
    assert job.status == 'completed' and job.snapshot_restarts == 1
    assert job.attempts == 2 and len(job.calls) == 2
    assert len(db.scalar(select(AIReview)).usage['calls']) == 2


def test_three_total_transient_attempts_and_retry_after_are_durable(client, database):
    from app.modules.ai_review.schemas import ProviderOutcome
    from app.workers.reviews import process_once
    submitted(client, database)
    provider = Provider(outcomes=[ProviderOutcome(error_code='api_error', retryable=True,
                                                 retry_after_seconds=100, usage={'input_tokens':1}) for _ in range(3)])
    now = [datetime.now(timezone.utc)]
    for _ in range(2):
        process_once(database['engine'], provider=provider, clock=lambda: now[0])
    db = database['session']
    db.expire_all()
    job = db.scalar(select(ReviewJob))
    assert job.next_attempt_at == now[0] + timedelta(seconds=100)
    assert job.attempts == 1
    process_once(database['engine'], provider=provider, clock=lambda: now[0]+timedelta(seconds=99))
    assert len(provider.calls) == 1
    drive(database, provider, start=now[0]+timedelta(seconds=10000))
    db.expire_all()
    assert len(provider.calls) == 3
    assert db.scalar(select(AIReview)).verdict == 'human_review'
    assert db.scalar(select(AIReview)).result['score'] is None
    assert db.scalar(select(ReviewJob)).attempts == 3


def test_primary_stage_survives_worker_restart(client, database):
    from app.modules.ai_review.schemas import Finding, ProviderOutcome, ReviewResult
    from app.workers.reviews import process_once
    submitted(client, database, work_type='emergency')
    # Use planned with a trusted material anomaly to route Sol without mandatory photos.
    db = database['session']
    saved = db.scalar(select(WorkOrder))
    saved.work_type = 'planned'
    saved.description = 'Аварийная задача: проверить соединение'
    saved.due_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    first = Provider(outcomes=[ProviderOutcome(result=ReviewResult(verdict='human_review', score=None,
                     findings=[], missing_evidence=[], limitations=[]), unresolved_conflict=True,
                     conflict_refs=['problem','work_description'], is_mock=True)])
    process_once(database['engine'], provider=first)
    process_once(database['engine'], provider=first)
    db.expire_all()
    assert db.scalar(select(ReviewJob)).stage == 'escalation'
    second = Provider()
    drive(database, second)
    assert len(first.calls) == len(second.calls) == 1
    assert second.calls[0][1].model == 'gpt-6-astra' and second.calls[0][2] is not None
    assert len(db.scalar(select(AIReview)).usage['calls']) == 2


def test_skip_locked_prevents_second_worker_claim(client, database):
    from app.workers.reviews import process_outbox, claim_job
    from sqlalchemy.orm import Session
    submitted(client, database)
    now = datetime.now(timezone.utc)
    db = database['session']
    process_outbox(db, now)
    db.commit()
    with Session(database['engine']) as one, Session(database['engine']) as two:
        assert claim_job(one, now) is not None
        assert claim_job(two, now) is None


def test_new_report_during_network_supersedes_old_revision(client, database):
    from sqlalchemy.orm import Session
    order, _ = submitted(client, database)
    def supersede():
        with Session(database['engine']) as db:
            old = db.scalar(select(Submission))
            db.add(Submission(work_order_id=old.work_order_id, revision=2,
                              assignment_version=old.assignment_version, worker_id=old.worker_id,
                              work_description='Новый отчёт', work_code_id=old.work_code_id,
                              no_materials_used=True))
            db.commit()
    drive(database, Provider(callback=supersede))
    db = database['session']
    assert count_rows(db, AIReview) == 0
    assert db.scalar(select(ReviewJob)).status == 'discarded'


def test_changed_snapshot_restarts_are_bounded(client, database, monkeypatch):
    from app.core.config import settings
    from sqlalchemy.orm import Session
    order, _ = submitted(client, database)
    monkeypatch.setattr(settings, 'ai_review_snapshot_restarts', 1)
    def change():
        with Session(database['engine']) as db:
            saved = db.get(WorkOrder, UUID(order['id']))
            saved.version += 1
            db.commit()
    provider = Provider(callback=change)
    drive(database, provider)
    db = database['session']
    job = db.scalar(select(ReviewJob))
    assert job.status == 'discarded' and job.last_error == 'snapshot_restart_limit'
    assert len(provider.calls) == 2 and len(job.calls) == 2
    assert count_rows(db, AIReview) == 0


def test_private_photo_is_prepared_from_actual_submission_without_url(client, database, monkeypatch, tmp_path):
    import hashlib
    from io import BytesIO
    from PIL import Image
    from app.core.config import settings
    from app.modules.photos.storage import FileSystemPhotoStorage
    from app.modules.work_orders.models import Photo
    from test_submissions import add_photo
    order = seed_order(database, 'IN_PROGRESS', work_type='emergency')
    output = BytesIO()
    Image.new('RGB',(320,240),(80,100,120)).save(output,format='JPEG')
    content = output.getvalue()
    photo = add_photo(database, order)
    photo.storage_key = str(uuid4())+'.jpg'
    photo.content_hash = hashlib.sha256(content).hexdigest()
    database['session'].commit()
    FileSystemPhotoStorage(tmp_path).save(photo.storage_key, content)
    monkeypatch.setattr(settings, 'photo_storage_path', tmp_path)
    result = send(client, sign_in(client), order, payload(database, after_photo_ids=[str(photo.id)]))
    assert result.status_code == 201, result.text
    class ImageProvider(Provider):
        def review(self,value,plan,*,images,previous=None):
            assert list(images) == [f'photo:{photo.id}']
            assert images[f'photo:{photo.id}'].media_type == 'image/jpeg'
            assert images[f'photo:{photo.id}'].data.startswith(b'\xff\xd8')
            assert 'storage_key' not in str(value.model_dump()) and 'http' not in str(value.photo_refs)
            return super().review(value,plan,images=images,previous=previous)
    provider = ImageProvider()
    drive(database, provider)
    assert len(provider.calls) == 1
    assert database['session'].scalar(select(AIReview)).model == 'gpt-6.1-sol'


def test_corrupted_photo_gives_human_review_without_provider(client,database,monkeypatch,tmp_path):
    from app.core.config import settings
    from test_submissions import add_photo
    order = seed_order(database,'IN_PROGRESS',work_type='emergency')
    photo = add_photo(database,order)
    # A real DB association with a missing/invalid private storage file.
    monkeypatch.setattr(settings,'photo_storage_path',tmp_path)
    result = send(client,sign_in(client),order,payload(database,after_photo_ids=[str(photo.id)]))
    assert result.status_code == 201
    provider=Provider()
    drive(database,provider)
    review=database['session'].scalar(select(AIReview))
    assert review.verdict=='human_review' and review.result['score'] is None
    assert provider.calls==[]


def test_completed_review_emits_realtime_event_and_keeps_review_interval(client,database):
    from app.modules.ai_review.views import current_review
    from app.modules.work_orders.models import OutboxEvent, WorkOrderEvent, WorkOrderInterval
    order,_=submitted(client,database)
    drive(database,Provider())
    db=database['session']
    saved=db.get(WorkOrder,UUID(order['id']))
    review=db.scalar(select(AIReview))
    event=db.scalar(select(WorkOrderEvent).where(WorkOrderEvent.action=='review_completed'))
    assert event is not None
    assert event.version==saved.version==review.order_version
    assert event.actor_id is None and event.payload['submission_id']==str(review.submission_id)
    assert db.scalar(select(OutboxEvent).where(OutboxEvent.event_id==event.id)).type=='work_order.review_completed'
    intervals=list(db.scalars(select(WorkOrderInterval).where(WorkOrderInterval.work_order_id==saved.id)))
    assert len(intervals)==1 and intervals[0].kind=='review' and intervals[0].end_at is None
    assert current_review(saved,review)


def test_assignment_change_during_model_discards_result(client,database):
    from sqlalchemy.orm import Session
    order,_=submitted(client,database)
    def reassign():
        with Session(database['engine']) as db:
            saved=db.get(WorkOrder,UUID(order['id']))
            saved.assignee_id=database['outsider'].id
            saved.assignment_version+=1
            saved.version+=1
            db.commit()
    drive(database,Provider(callback=reassign))
    db=database['session']
    assert db.scalar(select(ReviewJob)).status=='discarded'
    assert count_rows(db,AIReview)==0


def test_material_checks_use_only_comparable_server_norm(client,database):
    from app.modules.ai_review.inputs import build_input
    from app.modules.catalog.models import Equipment,Material,MaterialNorm
    from app.modules.work_orders.models import MaterialUsage
    from decimal import Decimal
    order,_=submitted(client,database)
    db=database['session']
    saved=db.get(WorkOrder,UUID(order['id']))
    report=db.scalar(select(Submission))
    material=db.scalar(select(Material))
    report.no_materials_used=False
    db.add(MaterialUsage(submission_id=report.id,material_id=material.id,quantity=Decimal('3')))
    # A norm on different equipment must not become an overuse accusation.
    other_equipment=db.scalar(select(Equipment.id).where(Equipment.id!=saved.equipment_id))
    db.add(MaterialNorm(equipment_id=other_equipment,work_code_id=report.work_code_id,
                        material_id=material.id,quantity=Decimal('2')))
    db.commit()
    value=build_input(db,saved,report)
    assert value.material_checks[0]['norm_quantity'] is None
    norm=db.scalar(select(MaterialNorm))
    norm.equipment_id=saved.equipment_id
    db.commit()
    value=build_input(db,saved,report)
    assert value.material_checks[0]['status']=='above_norm'
    db.delete(norm)
    db.commit()
    value=build_input(db,saved,report)
    assert value.material_checks[0]['norm_quantity'] is None
    assert value.material_checks[0]['status']=='no_norm'


def test_late_billed_response_preserves_usage_after_master_fence(client,database):
    from test_master_decision import decision
    order,report=submitted(client,database)
    def close():
        token=sign_in(client,'master')
        detail=client.get(f"{BASE}/{order['id']}").json()
        body=dict(decision='accept',submission_id=report['id'],expected_version=detail['version'],
                  assignment_version=1,score=None,reason='Проверено на месте')
        response=decision(client,token,order,body)
        assert response.status_code==200,response.text
    drive(database,Provider(callback=close))
    db=database['session']
    job=db.scalar(select(ReviewJob))
    assert job.status=='discarded' and len(job.calls)==1
    assert job.calls[0]['usage']['input_tokens']==10
    assert count_rows(db,AIReview)==0
    assert db.get(WorkOrder,UUID(order['id'])).status=='CLOSED'


def test_lost_lease_keeps_usage_without_overwriting_reclaimed_job(client,database):
    from app.workers.reviews import claim_job,process_once
    from sqlalchemy.orm import Session
    order,_=submitted(client,database)
    claimed=[]
    now=datetime.now(timezone.utc)
    def reclaim():
        with Session(database['engine']) as db:
            claim=claim_job(db,now+timedelta(seconds=181))
            assert claim is not None
            claimed.append(claim)
            db.commit()
    provider=Provider(callback=reclaim)
    assert process_once(database['engine'],provider=provider,clock=lambda:now)
    assert process_once(database['engine'],provider=provider,clock=lambda:now)
    db=database['session']
    db.expire_all()
    job=db.scalar(select(ReviewJob))
    assert job.status=='running' and job.lease_token==claimed[0][1]
    assert job.stage=='primary' and job.stage_outputs=={}
    assert len(job.calls)==1 and job.calls[0]['status']=='completed'
    assert job.calls[0]['usage']['input_tokens']==10
    assert count_rows(db,AIReview)==0
    assert db.get(WorkOrder,UUID(order['id'])).status=='AI_REVIEW'


def test_expiring_lease_during_prepare_rolls_back_final_business_writes(client,database,monkeypatch):
    import app.workers.reviews as worker
    order,_=submitted(client,database,work_type='emergency')
    now=[datetime.now(timezone.utc)]
    original=worker.read_images
    def slow(*args,**kwargs):
        result=original(*args,**kwargs)
        now[0]+=timedelta(seconds=181)
        return result
    monkeypatch.setattr(worker,'read_images',slow)
    provider=Provider()
    worker.process_once(database['engine'],provider=provider,clock=lambda:now[0])
    db=database['session']
    db.expire_all()
    assert db.get(WorkOrder,UUID(order['id'])).status=='SUBMITTED'
    assert count_rows(db,AIReview)==0
    job=db.scalar(select(ReviewJob))
    assert job.stage=='prepare' and job.snapshot is None
    assert provider.calls==[]


def test_invalid_final_stage_is_discarded_without_model_call(client,database):
    from app.workers.reviews import process_once,process_outbox
    order,_=submitted(client,database)
    db=database['session']
    process_outbox(db,datetime.now(timezone.utc))
    job=db.scalar(select(ReviewJob))
    job.stage='final'
    db.commit()
    provider=Provider()
    process_once(database['engine'],provider=provider)
    db.expire_all()
    assert provider.calls==[]
    assert db.get(ReviewJob,job.id).status=='discarded'


def test_expiry_after_kernel_flush_rolls_back_business_but_keeps_paid_metadata(client,database,monkeypatch):
    import app.workers.reviews as worker
    from app.modules.ai_review.schemas import Finding,ProviderOutcome,ReviewResult
    order,_=submitted(client,database)
    now=[datetime.now(timezone.utc)]
    original=worker.apply_internal
    def slow_kernel(db,order_id,command,**kwargs):
        result=original(db,order_id,command,**kwargs)
        if command.action=='request_rework':
            now[0]+=timedelta(seconds=181)
        return result
    monkeypatch.setattr(worker,'apply_internal',slow_kernel)
    outcome=ProviderOutcome(result=ReviewResult(verdict='requires_rework',score=2,
        findings=[Finding(code='work_problem_mismatch',severity='error',message='Работы не соответствуют заявке',
                          evidence_refs=['problem','work_description'])],missing_evidence=[],limitations=[]),
        usage={'input_tokens':10},is_mock=True)
    provider=Provider(outcomes=[outcome])
    worker.process_once(database['engine'],provider=provider,clock=lambda:now[0])
    worker.process_once(database['engine'],provider=provider,clock=lambda:now[0])
    db=database['session']
    db.expire_all()
    assert db.get(WorkOrder,UUID(order['id'])).status=='AI_REVIEW'
    assert count_rows(db,AIReview)==0
    job=db.scalar(select(ReviewJob))
    assert job.stage=='primary' and job.stage_outputs=={}
    assert job.calls[0]['usage']['input_tokens']==10
