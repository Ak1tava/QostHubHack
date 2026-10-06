import copy
import json
from pathlib import Path

import pytest

from test_ai_provider import text_review


def denied(winerror=5):
    error = PermissionError('synthetic sharing violation')
    error.winerror = winerror
    return error


def wrapper_for(path, callback):
    from app.modules.ai_review.eval_runner import BudgetedProvider, BudgetLedger
    from app.modules.ai_review.schemas import ProviderOutcome, ReviewResult

    class Fake:
        calls = 0

        def review(self, *args, **kwargs):
            self.calls += 1
            callback()
            return ProviderOutcome(
                result=ReviewResult(verdict='accepted', score=5, findings=[], missing_evidence=[], limitations=[]),
                usage={'input_tokens': 10, 'output_tokens': 5}, is_mock=True,
            )

    fake = Fake()
    return BudgetedProvider(fake, BudgetLedger(path)), fake


def invoke(wrapper):
    from app.modules.ai_review.schemas import StagePlan

    return wrapper.review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})


def test_reservation_replace_retries_finish_before_the_single_provider_call(monkeypatch, tmp_path):
    from app.modules.ai_review import eval_runner

    path = tmp_path / 'budget.json'
    ledger = eval_runner.BudgetLedger(path)
    ledger.reserve('previous', '0.25')
    original = Path.replace
    attempts = []
    sleeps = []

    def replace(source, target):
        attempts.append(target)
        if len(attempts) <= 2:
            raise denied(32)
        return original(source, target)

    def before_network():
        records = json.loads(path.read_text(encoding='utf-8'))['calls']
        assert len(attempts) == 3
        assert records[0]['call_id'] == 'previous'
        assert records[0]['charged_usd'] == '0.25'
        assert records[1]['state'] == 'reserved'

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(eval_runner.time, 'sleep', sleeps.append)
    wrapper, fake = wrapper_for(path, before_network)
    invoke(wrapper)
    assert fake.calls == 1
    assert len(sleeps) == 2
    assert wrapper.ledger.spent >= eval_runner.Decimal('0.25')


@pytest.mark.parametrize('failure,expected_attempts', [(denied(), 5), (OSError('disk failure'), 1), (denied(87), 1)])
def test_permanent_reservation_io_failure_leaves_old_ledger_and_never_calls_provider(monkeypatch, tmp_path, failure, expected_attempts):
    from app.modules.ai_review import eval_runner

    path = tmp_path / 'budget.json'
    eval_runner.BudgetLedger(path).reserve('previous', '0.25')
    before = path.read_bytes()
    attempts = []
    sleeps = []

    def replace(source, target):
        attempts.append(target)
        raise failure

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(eval_runner.time, 'sleep', sleeps.append)
    wrapper, fake = wrapper_for(path, lambda: pytest.fail('Reservation must persist before network'))
    with pytest.raises(type(failure)):
        invoke(wrapper)
    assert fake.calls == 0
    assert len(attempts) == expected_attempts
    assert len(sleeps) == expected_attempts - 1
    assert path.read_bytes() == before


def test_settlement_replace_retries_do_not_repeat_provider(monkeypatch, tmp_path):
    from app.modules.ai_review import eval_runner

    path = tmp_path / 'budget.json'
    original = Path.replace
    attempts = []

    def replace(source, target):
        attempts.append(target)
        if len(attempts) in (2, 3):
            raise denied(33)
        return original(source, target)

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(eval_runner.time, 'sleep', lambda _: None)
    wrapper, fake = wrapper_for(path, lambda: None)
    invoke(wrapper)
    assert len(attempts) == 4
    assert fake.calls == 1
    records = json.loads(path.read_text(encoding='utf-8'))['calls']
    assert len(records) == 1
    assert records[0]['state'] == 'settled'


def checkpoint(tmp_path, **changes):
    config = {'provider_source_hash': 'old', 'corpus_hash': 'same', 'models': {'primary': 'sol'}, 'schema_hash': 'schema'}
    saved = {'mode': 'live', 'config': config, 'rows': [{'case_id': 'dev01'}], 'previous_configs': []}
    saved.update(changes)
    path = tmp_path / 'dev.results.json'
    path.write_text(json.dumps(saved), encoding='utf-8')
    return path, config, saved


def test_dev_checkpoint_retains_rows_and_audits_only_explicit_source_migration(tmp_path):
    from app.modules.ai_review.eval_runner import load_dev_checkpoint

    path, old, saved = checkpoint(tmp_path, previous_configs=[{'provider_source_hash': 'earlier'}])
    rows, history = load_dev_checkpoint(path, old, {'dev01', 'dev02'})
    assert rows == saved['rows']
    assert history == saved['previous_configs']
    current = {**old, 'provider_source_hash': 'new'}
    with pytest.raises(ValueError):
        load_dev_checkpoint(path, current, {'dev01', 'dev02'})
    rows, history = load_dev_checkpoint(path, current, {'dev01', 'dev02'}, previous_source_hash='old')
    assert rows == saved['rows']
    assert history == [*saved['previous_configs'], old]
    assert json.loads(path.read_text(encoding='utf-8')) == saved


@pytest.mark.parametrize('change', ['mode', 'duplicate', 'outside', 'corpus', 'schema', 'models', 'wrong_source'])
def test_dev_checkpoint_rejects_invalid_resume(tmp_path, change):
    from app.modules.ai_review.eval_runner import load_dev_checkpoint

    path, old, saved = checkpoint(tmp_path)
    current = copy.deepcopy(old)
    current['provider_source_hash'] = 'new'
    declared = 'old'
    if change == 'mode':
        saved['mode'] = 'rules_only'
    elif change == 'duplicate':
        saved['rows'].append({'case_id': 'dev01'})
    elif change == 'outside':
        saved['rows'].append({'case_id': 'holdout01'})
    elif change == 'wrong_source':
        declared = 'unrelated'
    else:
        field = {'corpus': 'corpus_hash', 'schema': 'schema_hash', 'models': 'models'}[change]
        current[field] = 'changed'
    path.write_text(json.dumps(saved), encoding='utf-8')
    with pytest.raises(ValueError):
        load_dev_checkpoint(path, current, {'dev01', 'dev02'}, previous_source_hash=declared)


def test_persisted_calls_includes_unfinished_paid_case_without_resetting_reserves(tmp_path):
    from app.modules.ai_review.eval_runner import BudgetLedger, persisted_calls

    ledger = BudgetLedger(tmp_path / 'budget.json')
    ledger.reserve('finished', '0.4', {'case_id': 'dev01', 'stage': 'primary', 'model': 'sol'})
    ledger.settle('finished', '0.1', {'call_id': 'finished', 'case_id': 'dev01', 'stage': 'primary', 'model': 'sol',
                                    'usage': {'input_tokens': 7}, 'latency_ms': 12, 'error_code': None, 'is_mock': False})
    ledger.reserve('unfinished', '0.5', {'case_id': 'dev02', 'stage': 'escalation', 'model': 'astra', 'state': 'calling'})
    ledger.reserve('holdout', '0.3', {'case_id': 'holdout01', 'model': 'sol'})
    before = ledger.path.read_bytes()
    calls = persisted_calls(ledger, {'dev01', 'dev02'})
    assert [call['call_id'] for call in calls] == ['finished', 'unfinished']
    assert calls[0]['usage'] == {'input_tokens': 7}
    assert calls[1]['usage'] == {}
    assert calls[1]['latency_ms'] == 0
    assert calls[1]['error_code'] == 'interrupted_call'
    from decimal import Decimal

    assert ledger.spent == Decimal('0.9')
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize('flags', [
    ['--resume-dev'],
    ['--live', '--split', 'holdout', '--resume-dev'],
    ['--live', '--resume-from-source-hash', 'old'],
])
def test_resume_flags_reject_before_config_or_provider_use(monkeypatch, flags):
    from app.modules.ai_review import eval_runner

    monkeypatch.setattr(eval_runner, 'frozen_config', lambda *_: pytest.fail('Invalid flags must reject before config'))
    monkeypatch.setattr(eval_runner, 'OpenAIReviewProvider', lambda *args, **kwargs: pytest.fail('Invalid flags must never call provider'))
    try:
        code = eval_runner.main(flags)
    except SystemExit as error:
        code = error.code
    assert code == 2


def test_main_resume_dispatches_only_remaining_case_and_retains_paid_history(monkeypatch, tmp_path):
    from decimal import Decimal
    from pydantic import SecretStr
    from app.core.config import settings
    from app.modules.ai_review import eval_runner
    from app.modules.ai_review.schemas import ProviderOutcome, ReviewResult, StagePlan

    evals = tmp_path / 'evals'
    evals.mkdir()
    cases = [dict(case_id=case_id, split='dev', input_fixture='fixtures/fixture.json',
                  expected_verdict='accepted', required_findings=[]) for case_id in ('dev01', 'dev02')]
    (evals / 'cases.jsonl').write_text('\n'.join(json.dumps(case) for case in cases), encoding='utf-8')
    (evals / 'fixtures').mkdir()
    (evals / 'fixtures' / 'fixture.json').write_text(json.dumps({'forbidden_findings': []}), encoding='utf-8')
    state = tmp_path / '.tooling' / 't07' / 'evals'
    state.mkdir(parents=True)
    config = {'provider_source_hash': 'same', 'corpus_hash': 'same'}
    previous_row = dict(case_id='dev01', verdict='accepted', expected_verdict='accepted', verdict_match=True, required_total=0,
                        required_found=0, forbidden_findings=[], invalid_evidence_refs=0)
    (state / 'dev.results.json').write_text(json.dumps({'mode': 'live', 'config': config,
                                                      'rows': [previous_row]}), encoding='utf-8')
    ledger = eval_runner.BudgetLedger(state / 'budget.json')
    ledger.reserve('old-paid', '0.2', {'case_id': 'dev01', 'model': 'gpt-6.1-sol'})
    ledger.reserve('incomplete-paid', '0.3', {'case_id': 'dev02', 'model': 'gpt-6.1-sol'})
    dispatched = []
    network = []
    result = ReviewResult(verdict='accepted', score=5, findings=[], missing_evidence=[], limitations=[])

    class FakeProvider:
        def review(self, *args, **kwargs):
            network.append(True)
            return ProviderOutcome(result=result, usage={'input_tokens': 10, 'output_tokens': 5}, is_mock=True)

    def load_input(directory, case):
        dispatched.append(case['case_id'])
        return text_review(), {}

    def evaluate(value, provider, images):
        return provider.review(value, StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images=images).result

    monkeypatch.setattr(settings, 'openai_api_key', SecretStr('synthetic-unused-key'))
    monkeypatch.setattr(eval_runner, 'ROOT', tmp_path)
    monkeypatch.setattr(eval_runner, 'frozen_config', lambda _: config)
    monkeypatch.setattr(eval_runner, 'OpenAIReviewProvider', lambda *args, **kwargs: FakeProvider())
    monkeypatch.setattr(eval_runner, 'load_case_input', load_input)
    monkeypatch.setattr(eval_runner, 'evaluate_submission', evaluate)
    assert eval_runner.main(['--live', '--resume-dev', '--evals-dir', str(evals), '--output-dir', str(state)]) == 0
    saved = json.loads((state / 'dev.results.json').read_text(encoding='utf-8'))
    assert dispatched == ['dev02']
    assert len(network) == 1
    assert [row['case_id'] for row in saved['rows']] == ['dev01', 'dev02']
    assert saved['rows'][0] == previous_row
    assert [call['call_id'] for call in saved['calls'][:2]] == ['old-paid', 'incomplete-paid']
    assert len(saved['calls']) == 3
    assert Decimal(saved['metrics']['spent_or_reserved_usd']) > Decimal('0.5')
    assert not (state / 'holdout.started.json').exists()
