"""Real HTTP/DB QR workflow with an injected, explicitly marked test provider.

Run only on an isolated T11 acceptance stack with the no-key consumer stopped.
Requires DATABASE_URL, E2E_BASE_URL, E2E_LOGIN, E2E_PASSWORD; never loads live keys.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/api'))
from app.core.config import settings
from app.core.db import get_engine
from app.modules.ai_review.schemas import Finding, ProviderOutcome, ReviewResult
from app.modules.work_orders.models import AIReview, Submission, WorkOrder
from app.workers.reviews import process_once


class TestProvider:
    calls = 0

    def review(self, value, plan, *, images, previous=None):
        self.calls += 1
        return ProviderOutcome(
            is_mock=True, result=ReviewResult(
                verdict='accepted', score=4, missing_evidence=[], limitations=['Тестовый провайдер'],
                findings=[Finding(code='work_matches_problem', severity='info',
                                  message='Синтетическая проверка T11',
                                  evidence_refs=['problem', 'work_description'])],
            ),
        )


def main():
    url = make_url(os.environ['DATABASE_URL'])
    base = os.environ['E2E_BASE_URL']
    assert url.database == 'qosthub_demo_t11' and url.host in {'localhost', '127.0.0.1'}
    assert urlsplit(base).hostname in {'localhost', '127.0.0.1'}
    assert not settings.openai_api_key and not os.environ.get('OPENAI_API_KEY')
    prefix, password = os.environ['E2E_LOGIN'], os.environ['E2E_PASSWORD']
    assert prefix.startswith('e2e-')

    def login(client, master):
        token = client.get('/api/v1/auth/csrf').json()['csrf_token']
        r = client.post('/api/v1/auth/login', json={
            'login': f"{prefix}-{'master-' if master else ''}t11-qr", 'password': password,
        }, headers={'Origin': base, 'X-CSRF-Token': token})
        assert r.status_code == 200
        return r.json()

    def post(client, auth, path, data, *, key=None):
        return client.post(path, json=data, headers={
            'Origin': base, 'X-CSRF-Token': auth['csrf_token'], 'Idempotency-Key': key or str(uuid4()),
        })

    with httpx.Client(base_url=base, timeout=15) as master, httpx.Client(base_url=base, timeout=15) as worker:
        ma, wa = login(master, True), login(worker, False)
        equipment = master.get('/api/v1/catalog/equipment').json()['items'][0]
        card = master.get(f"/api/v1/equipment/{equipment['id']}")
        assert card.status_code == 200
        card = card.json()
        body = dict(description='Синтетический наряд из QR', work_type='planned',
                    area_id=card['area_id'], equipment_id=card['id'], assignee_id=wa['user']['id'],
                    due_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        r = post(master, ma, '/api/v1/work-orders', body)
        assert r.status_code == 201
        order = r.json(); route = f"/api/v1/work-orders/{order['id']}"
        for action in ['accept', 'start']:
            r = post(worker, wa, route + '/actions', dict(action=action, expected_version=order['version']))
            assert r.status_code == 200
            order = r.json()
        code = worker.get('/api/v1/catalog/work-codes').json()['items'][0]['id']
        submission = dict(expected_version=order['version'], assignment_version=order['assignment_version'],
                          work_description='Выполнена проверка насоса', fault_code_id=code,
                          materials=[], no_materials_used=True, after_photo_ids=[], comment='Тест T11')
        key = str(uuid4())
        r = post(worker, wa, route + '/submissions', submission, key=key)
        assert r.status_code == 201
        report = r.json()
        assert not report['missing_evidence']
        assert post(worker, wa, route + '/submissions', submission, key=key).json() == report
        provider = TestProvider()
        for _ in range(20):
            process_once(get_engine(), provider=provider, api_key=None)
            with Session(get_engine()) as db:
                review = db.scalar(select(AIReview).where(AIReview.submission_id == UUID(report['id'])))
                if review is not None:
                    assert review.usage['is_mock'] is True
                    assert db.get(WorkOrder, UUID(order['id'])).status == 'AI_REVIEW'
                    assert len(list(db.scalars(select(Submission).where(Submission.work_order_id == UUID(order['id']))))) == 1
                    break
        else:
            raise AssertionError('Injected provider did not finish the real pipeline')
        assert provider.calls > 0
        detail = master.get(route).json()
        assert detail['status'] == 'AI_REVIEW' and 'close' not in detail['allowed_actions']
        history = worker.get(f"/api/v1/equipment/{equipment['id']}").json()['recent_work_orders']
        assert any(o['id'] == order['id'] and o['status'] == 'AI_REVIEW' for o in history)
        print('PASS real HTTP/DB: equipment -> creation -> execution -> immutable report/replay -> injected mock review -> equipment history; AI did not close order; paid calls 0')


if __name__ == '__main__':
    main()
