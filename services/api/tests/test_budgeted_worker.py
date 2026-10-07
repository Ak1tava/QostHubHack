"""The live demo worker cannot restart, race or retry past its persisted budget."""
import json
from decimal import Decimal

import pytest

from test_ai_provider import text_review


def call(provider, model='gpt-6-luna'):
    from app.modules.ai_review.schemas import StagePlan
    return provider.review(text_review(), StagePlan(stage='primary', model=model, reasoning='low'), images={})


class FakeProvider:
    def __init__(self, callback=None, usage=None, error=None):
        self.calls = 0
        self.callback, self.usage, self.error = callback, usage, error

    def review(self, *args, **kwargs):
        from app.modules.ai_review.schemas import ProviderOutcome, ReviewResult
        self.calls += 1
        if self.callback:
            self.callback()
        return ProviderOutcome(result=ReviewResult(verdict='accepted', score=5, findings=[], missing_evidence=[], limitations=[]),
                               usage=self.usage if self.usage is not None else {'input_tokens': 10, 'output_tokens': 5},
                               error_code=self.error, is_mock=True)


def test_reservation_exists_before_paid_io_and_cost_survives_restart(tmp_path):
    from app.workers.budgeted_reviews import DemoBudgetedProvider, open_ledger
    path = tmp_path / 'budget.json'
    def before_io():
        saved = json.loads(path.read_text())
        assert saved['limit_usd'] == '2'
        assert saved['calls'][0]['state'] == 'reserved'
        assert Decimal(saved['spent_or_reserved_usd']) > 0
    provider = DemoBudgetedProvider(FakeProvider(before_io), open_ledger(path))
    call(provider)
    restarted = open_ledger(path)
    assert restarted.spent == provider.ledger.spent > 0


def test_crash_reservation_is_kept_and_restart_refuses_another_call(tmp_path):
    from app.workers.budgeted_reviews import DemoBudgetedProvider, open_ledger
    path = tmp_path / 'budget.json'
    def crash():
        raise RuntimeError('simulated crash')
    with pytest.raises(RuntimeError, match='simulated crash'):
        call(DemoBudgetedProvider(FakeProvider(crash), open_ledger(path)))
    saved = json.loads(path.read_text())
    assert Decimal(saved['spent_or_reserved_usd']) > 0
    with pytest.raises(RuntimeError, match='audit'):
        open_ledger(path)
    assert json.loads(path.read_text()) == saved


@pytest.mark.parametrize('usage,error', [({}, None), ({'input_tokens': 10, 'output_tokens': 5}, 'api_error')])
def test_unknown_usage_or_provider_error_stops_without_paid_retry(tmp_path, usage, error):
    from app.workers.budgeted_reviews import DemoBudgetedProvider, open_ledger
    fake = FakeProvider(usage=usage, error=error)
    provider = DemoBudgetedProvider(fake, open_ledger(tmp_path / 'budget.json'))
    call(provider)
    assert provider.stop_reason
    with pytest.raises(RuntimeError):
        call(provider)
    assert fake.calls == 1


def test_exhausted_budget_and_unknown_price_never_call_provider(tmp_path):
    from app.workers.budgeted_reviews import DemoBudgetedProvider, open_ledger
    from app.modules.ai_review.eval_runner import BudgetExceeded
    ledger = open_ledger(tmp_path / 'budget.json')
    ledger.reserve('earlier', '2')
    ledger.settle('earlier', '2')
    fake = FakeProvider()
    with pytest.raises(BudgetExceeded):
        call(DemoBudgetedProvider(fake, ledger))
    with pytest.raises(ValueError, match='Unknown model'):
        call(DemoBudgetedProvider(fake, open_ledger(tmp_path / 'other.json')), 'unknown-model')
    assert fake.calls == 0


def test_persisted_limit_cannot_be_raised_on_restart(tmp_path):
    from app.workers.budgeted_reviews import open_ledger
    path = tmp_path / 'budget.json'
    open_ledger(path, '1').save()
    with pytest.raises(ValueError, match='limit'):
        open_ledger(path, '2')
    with pytest.raises(ValueError):
        open_ledger(tmp_path / 'new.json', '2.01')


def test_second_consumer_is_refused_and_lock_is_reusable(tmp_path):
    from app.workers.budgeted_reviews import exclusive_worker
    path = tmp_path / 'worker.lock'
    with exclusive_worker(path):
        with pytest.raises(RuntimeError, match='already running'):
            with exclusive_worker(path):
                pytest.fail('Second consumer obtained the lock')
    with exclusive_worker(path):
        assert path.exists()


def test_cli_requires_live_and_stopped_ordinary_worker_before_any_setup():
    from app.workers.budgeted_reviews import main
    with pytest.raises(SystemExit):
        main([])
    with pytest.raises(SystemExit):
        main(['--live'])
