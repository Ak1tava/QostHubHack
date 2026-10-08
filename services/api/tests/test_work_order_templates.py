"""Fixed template snapshots and strict admission preserve legacy commands."""
import hashlib
import json
from uuid import UUID

import pytest
from sqlalchemy import select

from conftest import sign_in
from work_order_helpers import BASE, create_body, headers, seed_order, count_rows
from test_submissions import add_photo, payload, send
from app.modules.work_orders.models import (
    IdempotencyRecord, MaterialUsage, OutboxEvent, Photo, Submission, WorkOrder, WorkOrderEvent,
)


def test_static_template_route_precedes_order_id():
    from app.modules.work_orders.router import router
    paths = [route.path for route in router.routes]
    assert f"{BASE.removeprefix('/api/v1')}/templates" in paths
    assert paths.index('/work-orders/templates') < paths.index('/work-orders/{order_id}')


def test_definitions_are_fixed_and_snapshots_are_independent():
    from app.modules.work_orders import templates
    first = templates.snapshot('visible_leak')
    assert first['version'] == 1
    assert len(first['checklist']) == 3 and all(i['required'] for i in first['checklist'])
    assert first['photo_requirements'] == {'before': 1, 'after': 1}
    first['checklist'][0]['label'] = 'changed'
    assert templates.snapshot('visible_leak')['checklist'][0]['label'] != 'changed'


def template_snapshot(template_id='visible_leak'):
    from app.modules.work_orders.templates import snapshot
    return snapshot(template_id)


def answers(snapshot):
    return [{'id': i['id'], 'checked': True} for i in snapshot['checklist']]


def template_order(database, template_id='visible_leak'):
    return seed_order(database, 'IN_PROGRESS', template_snapshot=template_snapshot(template_id))


def before_photo(database, order, **changes):
    photo = add_photo(database, order)
    photo.type = 'before'
    photo.uploaded_by = database['master'].id
    for name, value in changes.items():
        setattr(photo, name, value)
    database['session'].commit()
    return photo


def test_templates_list_authentication_and_cache(client, database):
    assert client.get(f'{BASE}/templates').status_code == 401
    sign_in(client)
    response = client.get(f'{BASE}/templates')
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert [t['id'] for t in response.json()['items']] == ['visible_leak', 'visible_element']


@pytest.mark.parametrize('template_id', ['visible_leak', 'visible_element'])
def test_creation_snapshot_and_replay_ignore_later_definitions(client, database, monkeypatch, template_id):
    from app.modules.work_orders import templates
    token = sign_in(client, 'master')
    body = create_body(database, template_id=template_id)
    first = client.post(BASE, json=body, headers=headers(token, 'create-template'))
    assert first.status_code == 201, first.text
    snapshot = first.json()['template_snapshot']
    assert snapshot == template_snapshot(template_id)
    monkeypatch.setattr(templates, 'snapshot', lambda _: {**snapshot, 'version': 2})
    retry = client.post(BASE, json=body, headers=headers(token, 'create-template'))
    assert retry.status_code == 201 and retry.json() == first.json()
    assert client.get(f"{BASE}/{first.json()['id']}").json()['template_snapshot'] == snapshot


@pytest.mark.parametrize('template_id', ['visible_leak', 'visible_element'])
def test_complete_template_submission_saves_answers_and_replays(client, database, monkeypatch, template_id):
    from app.modules.work_orders import templates
    order = template_order(database, template_id)
    snapshot = template_snapshot(template_id)
    before_photo(database, order)
    after = add_photo(database, order)
    token = sign_in(client)
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert detail['before_photo_count'] == 1
    monkeypatch.setattr(templates, 'snapshot', lambda _: {**snapshot, 'checklist': []})
    body = payload(database, template_answers=answers(snapshot), after_photo_ids=[str(after.id)])
    first = send(client, token, order, body, 'template-report')
    assert first.status_code == 201, first.text
    assert first.json()['template_answers'] == body['template_answers']
    assert first.json()['missing_evidence'] == []
    assert send(client, token, order, body, 'template-report').json() == first.json()
    assert send(client, token, order, {**body, 'comment': 'changed'}, 'template-report').status_code == 409
    saved = database['session'].scalar(select(Submission))
    assert saved.template_answers == body['template_answers']


@pytest.mark.parametrize('invalid', ['missing', 'false', 'unknown', 'duplicate', 'before', 'after', 'foreign_before', 'foreign_after', 'bound_after', 'stale'])
def test_template_rejection_is_atomic(client, database, invalid):
    order = template_order(database)
    checks = answers(template_snapshot())
    before = before_photo(database, order)
    after = add_photo(database, order)
    if invalid == 'missing': checks.pop()
    if invalid == 'false': checks[0]['checked'] = False
    if invalid == 'unknown': checks.append({'id': 'unknown', 'checked': True})
    if invalid == 'duplicate': checks.append(checks[0])
    if invalid == 'before': database['session'].delete(before)
    if invalid in {'foreign_before', 'foreign_after'}:
        other = seed_order(database)
        (before if invalid == 'foreign_before' else after).work_order_id = UUID(other['id'])
    if invalid == 'bound_after':
        report = Submission(work_order_id=UUID(order['id']), revision=1, assignment_version=1,
                            worker_id=database['worker'].id, work_description='previous',
                            work_code_id=UUID(payload(database)['fault_code_id']), no_materials_used=True)
        database['session'].add(report)
        database['session'].flush()
        after.submission_id = report.id
    database['session'].commit()
    body = payload(database, template_answers=checks,
                   after_photo_ids=[] if invalid == 'after' else [str(after.id)],
                   expected_version=2 if invalid == 'stale' else 1)
    db = database['session']
    models = [Submission, MaterialUsage, WorkOrderEvent, OutboxEvent, IdempotencyRecord]
    counts = [count_rows(db, m) for m in models]
    result = send(client, sign_in(client), order, body, 'rejected')
    assert result.status_code == (409 if invalid == 'stale' else 422), result.text
    assert [count_rows(db, m) for m in models] == counts
    assert db.get(WorkOrder, UUID(order['id']), populate_existing=True).status == 'IN_PROGRESS'


def test_legacy_answers_rejected_but_missing_after_retained(client, database):
    order = seed_order(database, 'IN_PROGRESS', work_type='emergency')
    token = sign_in(client)
    assert send(client, token, order, payload(database, template_answers=[{'id': 'inspect_result', 'checked': True}])).status_code == 422
    accepted = send(client, token, order, payload(database))
    assert accepted.status_code == 201
    assert accepted.json()['missing_evidence'] == ['after_photo']


@pytest.mark.parametrize('login, status', [('master', 403), ('outsider', 404)])
def test_template_submission_permissions(client, database, login, status):
    order = template_order(database)
    result = send(client, sign_in(client, login), order, payload(database))
    assert result.status_code == status


@pytest.mark.parametrize('kind', ['create', 'submit'])
def test_old_receipt_digest_replays_with_new_defaults(client, database, kind):
    from app.modules.work_orders.schemas import SubmissionCreate, WorkOrderCreate
    order = seed_order(database, 'IN_PROGRESS') if kind == 'submit' else None
    token = sign_in(client, 'worker' if order else 'master')
    body = payload(database) if order else create_body(database)
    endpoint = f"{BASE}/{order['id']}/submissions" if order else BASE
    response = client.post(endpoint, json=body, headers=headers(token, 'old-receipt'))
    assert response.status_code == 201, response.text
    model = SubmissionCreate if order else WorkOrderCreate
    old_body = model.model_validate(body).model_dump(mode='json')
    old_body.pop('template_answers' if order else 'template_id')
    path = f"POST /work-orders/{order['id']}/submissions" if order else 'POST /work-orders'
    digest = hashlib.sha256(json.dumps({'path': path, 'body': old_body}, sort_keys=True,
                                      separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    record = database['session'].get(IdempotencyRecord, ((database['worker'] if order else database['master']).id, 'old-receipt'))
    record.fingerprint = digest
    record.response_body.pop('template_answers' if order else 'template_snapshot', None)
    database['session'].commit()
    retry = client.post(endpoint, json=body, headers=headers(token, 'old-receipt'))
    assert retry.status_code == 201, retry.text


def test_saved_template_gaps_block_master_acceptance(client, database):
    from app.modules.work_orders.models import MasterDecision
    order = template_order(database)
    db = database['session']
    saved_order = db.get(WorkOrder, UUID(order['id']))
    saved_order.status = 'AI_REVIEW'
    report = Submission(work_order_id=saved_order.id, revision=1, assignment_version=1,
                        worker_id=database['worker'].id, work_description='Видимая работа описана',
                        work_code_id=UUID(payload(database)['fault_code_id']), no_materials_used=True,
                        template_answers=[])
    db.add(report)
    db.commit()
    token = sign_in(client, 'master')
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert detail['submission']['missing_evidence'] == ['template_checklist', 'before_photo', 'after_photo']
    body = dict(decision='accept', submission_id=str(report.id), expected_version=1,
                assignment_version=1, reason='Осмотр мастером', score=None)
    response = client.post(f"{BASE}/{order['id']}/decision", json=body, headers=headers(token))
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'missing_evidence'
    assert count_rows(db, MasterDecision) == 0


def test_rework_keeps_first_revision_answers_immutable(client, database):
    from work_order_helpers import succeed
    order = template_order(database)
    before_photo(database, order)
    photo = add_photo(database, order)
    checks = answers(template_snapshot())
    body = payload(database, template_answers=checks, after_photo_ids=[str(photo.id)])
    token = sign_in(client)
    first = send(client, token, order, body, 'first-template')
    assert first.status_code == 201, first.text
    db = database['session']
    saved = db.get(WorkOrder, UUID(order['id']))
    saved.status = 'REWORK'
    db.commit()
    restarted = succeed(client, token, {'id': order['id'], 'version': 2}, 'restart')
    second_photo = add_photo(database, order)
    second = send(client, token, order, payload(database, expected_version=restarted['version'],
        template_answers=list(reversed(checks)), after_photo_ids=[str(second_photo.id)]), 'second-template')
    assert second.status_code == 201, second.text
    assert second.json()['revision'] == 2
    original = db.get(Submission, UUID(first.json()['id']), populate_existing=True)
    assert original.template_answers == checks
    assert db.get(Photo, photo.id, populate_existing=True).submission_id == original.id
