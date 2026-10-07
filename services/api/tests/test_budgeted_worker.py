"""The live demo worker cannot restart, race or retry past its persisted budget."""
import json
import os
import signal
import subprocess
import sys
import time
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


def test_worker_loop_stops_after_first_provider_error(tmp_path, monkeypatch):
    from app.workers import reviews
    from app.workers.budgeted_reviews import DemoBudgetedProvider, open_ledger, run
    fake = FakeProvider(error='api_error')
    provider = DemoBudgetedProvider(fake, open_ledger(tmp_path / 'budget.json'))
    def stage(*args, **kwargs):
        call(kwargs['provider'])
        return True
    monkeypatch.setattr(reviews, 'process_once', stage)
    assert run(None, provider, max_stages=5, poll_seconds=0) == 2
    assert fake.calls == 1


def test_restart_after_provider_error_requires_audit_instead_of_paid_retry(tmp_path):
    from app.workers.budgeted_reviews import DemoBudgetedProvider, open_ledger
    path = tmp_path / 'budget.json'
    call(DemoBudgetedProvider(FakeProvider(error='api_error'), open_ledger(path)))
    with pytest.raises(RuntimeError, match='audit'):
        open_ledger(path)


def test_process_crash_releases_lock_without_deleting_persistent_marker(tmp_path):
    from app.workers.budgeted_reviews import exclusive_worker
    path, ready = tmp_path / 'worker.lock', tmp_path / 'ready'
    code = "from pathlib import Path\nimport sys,time,os\nfrom app.workers.budgeted_reviews import exclusive_worker\nwith exclusive_worker(Path(sys.argv[1])):\n Path(sys.argv[2]).write_text(str(os.getpid()))\n time.sleep(60)\n"
    process = subprocess.Popen([sys.executable, '-c', code, str(path), str(ready)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 8
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert ready.exists(), 'Child worker did not obtain its lock'
        with pytest.raises(RuntimeError, match='already running'):
            with exclusive_worker(path):
                pytest.fail('Parallel worker obtained the lock')
        # Windows venv's python.exe may be a launcher; kill the actual lock owner.
        os.kill(int(ready.read_text()), signal.SIGTERM)
        process.wait(timeout=5)
        with exclusive_worker(path):
            assert path.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
