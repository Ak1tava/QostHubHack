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


@pytest.fixture
def guarded_engine(database):
    from sqlalchemy import create_engine
    engine = create_engine(database['engine'].url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


def own_lock_pid(engine):
    from sqlalchemy import text
    with engine.connect() as connection:
        pids = list(connection.scalars(text("SELECT pid FROM pg_locks WHERE locktype='advisory' "
                    "AND classid=0 AND objid=71007010 AND objsubid=1 AND granted "
                    "AND database=(SELECT oid FROM pg_database WHERE datname=current_database())")))
    assert len(pids) == 1, 'Exactly the test-owned consumer must hold the lock'
    return pids[0]


def terminate_own_lock_session(engine, pid):
    from sqlalchemy import text
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT pg_backend_pid()')) != pid
        assert own_lock_pid(engine) == pid
        assert connection.scalar(text('SELECT pg_terminate_backend(:pid)'), {'pid': pid})
        # Wait for termination to release precisely this test-owned backend's lock.
        for _ in range(100):
            if not connection.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid)'), {'pid': pid}):
                break
        else:
            pytest.fail('Test-owned backend did not terminate')


def close_terminated_holder(context):
    from sqlalchemy.exc import SQLAlchemyError
    try:
        context.__exit__(None, None, None)
    except SQLAlchemyError:
        # Old implementation attempts an unlock on the terminated session. Let
        # the RED assertion identify the extra provider call instead of cleanup.
        pass


def test_database_lock_loss_between_iterations_halts_original_and_allows_second_consumer(guarded_engine, tmp_path, monkeypatch):
    from sqlalchemy import text
    from app.workers import budgeted_reviews, reviews
    first_context = budgeted_reviews.single_database_consumer(guarded_engine)
    first_guard = first_context.__enter__()
    pid = own_lock_pid(guarded_engine)
    first_fake, second_fake = FakeProvider(), FakeProvider()
    first = budgeted_reviews.DemoBudgetedProvider(first_fake, budgeted_reviews.open_ledger(tmp_path / 'first.json'))
    first.lock_guard = first_guard
    terminated = False
    def stage(engine, *, provider):
        # Ordinary work connections are healthy/recreated independently of the lock session.
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT 1')) == 1
        call(provider)
        return True
    def between_iterations(_):
        nonlocal terminated
        if terminated:
            return
        terminated = True
        terminate_own_lock_session(guarded_engine, pid)
        with budgeted_reviews.single_database_consumer(guarded_engine) as second_guard:
            second = budgeted_reviews.DemoBudgetedProvider(second_fake, budgeted_reviews.open_ledger(tmp_path / 'second.json'))
            second.lock_guard = second_guard
            assert budgeted_reviews.run(guarded_engine, second, max_stages=1, poll_seconds=0) == 0
    monkeypatch.setattr(reviews, 'process_once', stage)
    monkeypatch.setattr(budgeted_reviews.time, 'sleep', between_iterations)
    try:
        result = budgeted_reviews.run(guarded_engine, first, max_stages=2, poll_seconds=0)
    finally:
        close_terminated_holder(first_context)
    assert first_fake.calls == 1, 'Original consumer began another billed request after losing its lock'
    assert second_fake.calls == 1
    assert result == 2
    halt = json.loads((tmp_path / 'first.halt.json').read_text())
    assert halt['reason'] == 'database_lock_lost'
    assert halt['backend_pid'] == pid
    with pytest.raises(RuntimeError, match='audit'):
        budgeted_reviews.open_ledger(tmp_path / 'first.json')


def test_live_original_session_without_lock_ownership_cannot_start_io(guarded_engine, tmp_path):
    from app.workers import budgeted_reviews
    context = budgeted_reviews.single_database_consumer(guarded_engine)
    guard = context.__enter__()
    original_pid = guard.backend_pid
    fake = FakeProvider()
    first = budgeted_reviews.DemoBudgetedProvider(fake, budgeted_reviews.open_ledger(tmp_path / 'first.json'),
                                                lock_guard=guard)
    try:
        with guard.driver.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', (budgeted_reviews.LOCK_KEY,))
            assert cursor.fetchone()[0]
        assert not guard.driver.closed
        assert guard.driver.info.backend_pid == original_pid
        with budgeted_reviews.single_database_consumer(guarded_engine):
            with pytest.raises(budgeted_reviews.DatabaseLockLost, match='audit'):
                call(first)
        assert fake.calls == 0
        assert first.ledger.spent > 0
        assert (tmp_path / 'first.halt.json').exists()
    finally:
        close_terminated_holder(context)


def test_closed_original_connection_persists_halt_before_any_io(guarded_engine, tmp_path):
    from app.workers import budgeted_reviews
    context = budgeted_reviews.single_database_consumer(guarded_engine)
    guard = context.__enter__()
    fake = FakeProvider()
    provider = budgeted_reviews.DemoBudgetedProvider(fake, budgeted_reviews.open_ledger(tmp_path / 'budget.json'),
                                                   lock_guard=guard)
    try:
        guard.connection.close()
        with pytest.raises(budgeted_reviews.DatabaseLockLost, match='audit'):
            call(provider)
        assert fake.calls == 0
        assert (tmp_path / 'budget.halt.json').exists()
    finally:
        close_terminated_holder(context)


def test_lock_loss_after_reservation_is_fenced_immediately_before_provider_io(guarded_engine, tmp_path, monkeypatch):
    from app.workers import budgeted_reviews
    context = budgeted_reviews.single_database_consumer(guarded_engine)
    guard = context.__enter__()
    pid = own_lock_pid(guarded_engine)
    first_fake, second_fake = FakeProvider(), FakeProvider()
    first = budgeted_reviews.DemoBudgetedProvider(first_fake, budgeted_reviews.open_ledger(tmp_path / 'first.json'))
    first.lock_guard = guard
    reserve = first.ledger.reserve
    def reserve_then_lose_session(*args, **kwargs):
        reserve(*args, **kwargs)
        terminate_own_lock_session(guarded_engine, pid)
        with budgeted_reviews.single_database_consumer(guarded_engine) as second_guard:
            second = budgeted_reviews.DemoBudgetedProvider(second_fake, budgeted_reviews.open_ledger(tmp_path / 'second.json'))
            second.lock_guard = second_guard
            call(second)
    monkeypatch.setattr(first.ledger, 'reserve', reserve_then_lose_session)
    try:
        try:
            call(first)
        except RuntimeError:
            pass
    finally:
        close_terminated_holder(context)
    assert first_fake.calls == 0, 'Paid I/O began with a dead lock session after its reservation'
    assert second_fake.calls == 1
    assert first.ledger.records[0]['state'] == 'reserved'
    assert first.ledger.spent > 0
    with pytest.raises(RuntimeError, match='audit'):
        budgeted_reviews.open_ledger(tmp_path / 'first.json')
