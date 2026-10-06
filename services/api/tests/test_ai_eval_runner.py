import json
from pathlib import Path

import pytest

from test_ai_provider import text_review
from test_ai_review import ROOT, review


def test_adapter_rasterizes_svg_and_never_passes_labels_or_fixture_metadata():
    from app.modules.ai_review.eval_runner import load_case_input
    from PIL import Image
    from io import BytesIO

    case = {'input_fixture': 'fixtures/T09-001.json', 'expected_verdict': 'requires_rework', 'required_findings': ['decoy']}
    value, images = load_case_input(ROOT / 'evals', case)
    assert value.work_order_id == review().work_order_id
    assert images.keys() == {'photo_before', 'photo_after'}
    assert 'expected_verdict' not in value.model_dump_json()
    assert 'fixture_path' not in value.model_dump_json()
    for image in images.values():
        assert image.media_type == 'image/png'
        with Image.open(BytesIO(image.data)) as decoded:
            assert decoded.format == 'PNG'
            assert max(decoded.size) <= 1024


def test_eval_paths_cannot_read_outside_fixture_root():
    from app.modules.ai_review.eval_runner import load_case_input

    with pytest.raises(ValueError):
        load_case_input(ROOT / 'evals', {'input_fixture': '../plans.md'})


def test_budget_reserves_before_each_call_and_unknown_usage_keeps_full_reserve(tmp_path):
    from app.modules.ai_review.eval_runner import BudgetLedger, BudgetExceeded

    ledger = BudgetLedger(tmp_path / 'budget.json', limit='5')
    ledger.reserve('first', '4')
    with pytest.raises(BudgetExceeded):
        ledger.reserve('second', '1.01')
    ledger.settle('first', None)
    reopened = BudgetLedger(tmp_path / 'budget.json', limit='5')
    assert reopened.spent == 4
    with pytest.raises(BudgetExceeded):
        reopened.reserve('second', '1.01')
    reopened.reserve('second', '1')
    reopened.settle('second', '0.25')
    assert reopened.spent == 4.25


def test_holdout_requires_matching_freeze_and_runs_once(tmp_path):
    from app.modules.ai_review.eval_runner import freeze_configuration, claim_holdout

    config = {'corpus_hash': 'abc', 'provider_source_hash': 'def', 'models': ['sol']}
    freeze_configuration(tmp_path, config)
    with pytest.raises(ValueError):
        claim_holdout(tmp_path, {**config, 'corpus_hash': 'changed'})
    claim_holdout(tmp_path, config)
    with pytest.raises(FileExistsError):
        claim_holdout(tmp_path, config)


def test_real_frozen_config_survives_json_roundtrip_and_allows_one_holdout(tmp_path):
    from app.modules.ai_review.eval_runner import frozen_config, freeze_configuration, claim_holdout

    config = frozen_config(ROOT / 'evals')
    freeze_configuration(tmp_path, config)
    freeze_configuration(tmp_path, frozen_config(ROOT / 'evals'))
    claim_holdout(tmp_path, frozen_config(ROOT / 'evals'))
    with pytest.raises(FileExistsError):
        claim_holdout(tmp_path, config)


def test_actual_usage_settles_all_calls_including_escalation(tmp_path):
    from app.modules.ai_review.eval_runner import BudgetedProvider, BudgetLedger
    from app.modules.ai_review.schemas import ProviderOutcome, ReviewResult, StagePlan

    class Fake:
        calls = 0

        def review(self, value, plan, **kwargs):
            self.calls += 1
            return ProviderOutcome(result=ReviewResult(verdict='accepted', score=5, findings=[], missing_evidence=[], limitations=[]),
                                   usage={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}, is_mock=True)

    fake = Fake()
    ledger = BudgetLedger(tmp_path / 'budget.json', limit='5')
    wrapper = BudgetedProvider(fake, ledger, max_output_tokens=4096, complex_max_output_tokens=8192)
    wrapper.review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})
    wrapper.review(text_review(), StagePlan(stage='escalation', model='gpt-6-astra', reasoning='medium'), images={})
    assert fake.calls == 2
    assert len(wrapper.calls) == 2
    assert ledger.spent > 0
    assert [c['stage'] for c in wrapper.calls] == ['primary', 'escalation']
    persisted = json.loads((tmp_path / 'budget.json').read_text(encoding='utf-8'))['calls']
    assert [call['metadata']['stage'] for call in persisted] == ['primary', 'escalation']
    assert all(call['metadata']['usage']['total_tokens'] == 15 for call in persisted)


def test_insufficient_budget_never_calls_provider(tmp_path):
    from app.modules.ai_review.eval_runner import BudgetedProvider, BudgetLedger, BudgetExceeded
    from app.modules.ai_review.schemas import StagePlan

    class Never:
        def review(self, *args, **kwargs):
            pytest.fail('No call after a rejected reservation')

    wrapper = BudgetedProvider(Never(), BudgetLedger(tmp_path / 'budget.json', limit='0.0001'))
    with pytest.raises(BudgetExceeded):
        wrapper.review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})


def test_cli_without_key_makes_no_provider_or_holdout_attempt(monkeypatch, tmp_path):
    from app.modules.ai_review import eval_runner
    from app.core.config import settings

    monkeypatch.setattr(settings, 'openai_api_key', None)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(eval_runner, 'OpenAIReviewProvider', lambda *args, **kwargs: pytest.fail('Key absent: no provider constructed'))
    assert eval_runner.main(['--live', '--split', 'holdout', '--output-dir', str(tmp_path)]) == 2
    assert not (tmp_path / 'holdout.started.json').exists()


def test_corpus_hash_detects_changed_labels_or_media(tmp_path):
    from app.modules.ai_review.eval_runner import corpus_hash

    (tmp_path / 'fixtures').mkdir()
    (tmp_path / 'cases.jsonl').write_text('a', encoding='utf-8')
    (tmp_path / 'fixtures' / 'photo.svg').write_text('<svg/>', encoding='utf-8')
    first = corpus_hash(tmp_path)
    (tmp_path / 'fixtures' / 'photo.svg').write_text('<svg width="2"/>', encoding='utf-8')
    assert corpus_hash(tmp_path) != first


def test_metrics_distinguish_false_rework_from_human_review():
    from decimal import Decimal
    from app.modules.ai_review.eval_runner import metrics

    rows = [dict(verdict=actual, expected_verdict=expected, verdict_match=actual == expected,
                 required_found=0, required_total=0, invalid_evidence_refs=0, forbidden_findings=[])
            for actual, expected in [('requires_rework', 'accepted'), ('requires_rework', 'requires_rework'),
                                     ('human_review', 'accepted'), ('accepted', 'requires_rework')]]
    result = metrics(rows, [], Decimal('0'))
    assert result['false_rework'] == 1
    assert result['human_review'] == 1
    assert result['false_acceptance'] == 1
