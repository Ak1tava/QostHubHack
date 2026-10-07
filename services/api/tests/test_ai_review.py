"""Behavior checks for server rules and bounded, evidence-grounded provider routing."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def review(number=1, **updates):
    from app.modules.ai_review.schemas import ReviewInput

    raw = json.loads((ROOT / f'evals/fixtures/T09-{number:03}.json').read_text(encoding='utf-8'))['review_input']
    raw.update(updates)
    return ReviewInput.model_validate(raw)


def test_missing_mandatory_photo_short_circuits_provider():
    from app.modules.ai_review.service import evaluate_submission

    class Never:
        def review(self, *args, **kwargs):
            pytest.fail('Incomplete evidence must not cause a paid call')

    result = evaluate_submission(review(3), Never())
    assert result.verdict == 'requires_rework'
    assert 'missing_required_photo' in {f.code for f in result.findings}


@pytest.mark.parametrize('number,code', [(5, 'duplicate_evidence'), (7, 'photo_unusable'), (18, 'timing_inconsistent')])
def test_unreliable_evidence_is_human_review_without_bad_score(number, code):
    from app.modules.ai_review.service import evaluate_submission

    result = evaluate_submission(review(number))
    assert result.verdict == 'human_review'
    assert result.score is None
    assert code in {f.code for f in result.findings}


def test_material_comparison_is_calculated_and_norm_absence_is_not_overuse():
    from app.modules.ai_review.rules import assess_rules

    no_norm = assess_rules(review(11))
    assert 'norm_unavailable' in {f.code for f in no_norm.findings}
    assert 'material_overuse' not in {f.code for f in no_norm.findings}
    overuse = assess_rules(review(15))
    assert 'material_overuse' in {f.code for f in overuse.findings}


def test_only_planned_text_without_mandatory_photo_or_anomalies_uses_luna():
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import select_primary

    planned = review(photo_refs=[], problem='Плановый наряд: сверка журнала', checklist=[{'id': 'report', 'code': 'report_fields', 'complete': True}])
    assert select_primary(planned, assess_rules(planned)).model == 'gpt-6-luna'
    assert select_primary(review(), assess_rules(review())).model == 'gpt-6.1-sol'
    anomalous = planned.model_copy(update={'timing_checks': [{'id': 'late', 'late_minutes': 3}]})
    assert select_primary(anomalous, assess_rules(anomalous)).model == 'gpt-6.1-sol'


def test_invented_refs_and_overuse_without_norm_fail_closed():
    from app.modules.ai_review.schemas import Finding, ProviderOutcome, ReviewResult
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import finalize_result

    for number, code, refs in [(1, 'work_matches_problem', ['invented']), (11, 'material_overuse', ['material_1'])]:
        value = review(number)
        outcome = ProviderOutcome(result=ReviewResult(verdict='accepted', score=5, findings=[Finding(code=code, severity='info', message='claim', evidence_refs=refs)], missing_evidence=[], limitations=[]))
        result = finalize_result(value, assess_rules(value), outcome)
        assert result.verdict == 'human_review'
        assert result.score is None
        assert 'material_overuse' not in {f.code for f in result.findings}
        assert all('invented' not in f.evidence_refs for f in result.findings)


def test_escalation_requires_valid_legible_semantic_refs_and_is_single():
    from app.modules.ai_review.schemas import ProviderOutcome, ReviewResult
    from app.modules.ai_review.service import can_escalate, evaluate_submission

    result = ReviewResult(verdict='human_review', score=None, findings=[], missing_evidence=[], limitations=[])
    conflict = ProviderOutcome(result=result, unresolved_conflict=True, conflict_refs=['problem', 'work_description', 'photo_after'], legible_refs=['photo_after'])
    assert can_escalate(review(), conflict)
    assert not can_escalate(review(), conflict.model_copy(update={'conflict_refs': ['missing']}))
    assert not can_escalate(review(7), conflict)
    assert not can_escalate(review(), conflict.model_copy(update={'error_code': 'api_error'}))

    class Conflict:
        calls = []

        def review(self, value, plan, **kwargs):
            self.calls.append(plan.model)
            return conflict

    provider = Conflict()
    assert evaluate_submission(review(), provider).verdict == 'human_review'
    assert provider.calls == ['gpt-6.1-sol', 'gpt-6-astra']


def test_before_photo_absence_does_not_require_rework():
    from app.modules.ai_review.rules import assess_rules

    value = review()
    value.photo_refs = [p for p in value.photo_refs if p['phase'] == 'after']
    assert assess_rules(value).result is None


def test_provider_errors_never_escalate_and_keep_null_score():
    from app.modules.ai_review.schemas import ProviderOutcome
    from app.modules.ai_review.service import evaluate_submission

    class Failed:
        calls = 0

        def review(self, *args, **kwargs):
            self.calls += 1
            return ProviderOutcome(error_code='refusal')

    provider = Failed()
    result = evaluate_submission(review(), provider)
    assert provider.calls == 1
    assert result.verdict == 'human_review' and result.score is None


def test_server_evidence_ids_are_unique_and_reserved():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        review(checklist=[{'id': 'problem', 'code': 'report_fields', 'complete': True}])


def test_optional_photo_check_is_not_incompleteness():
    from app.modules.ai_review.rules import assess_rules

    value = review(photo_refs=[], checklist=[{'id': 'optional', 'code': 'mandatory_after_photo', 'complete': False, 'required': False}])
    assert assess_rules(value).result is None


@pytest.mark.parametrize('number', [13, 14])
def test_embedded_instructions_are_ignored_even_when_rules_short_circuit(number):
    from app.modules.ai_review.service import evaluate_submission

    result = evaluate_submission(review(number))
    assert result.verdict != 'accepted'
    assert 'untrusted_instruction_ignored' in {f.code for f in result.findings}


def test_claimed_overuse_requires_server_comparison_to_agree():
    from app.modules.ai_review.schemas import Finding, ProviderOutcome, ReviewResult
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import finalize_result

    value = review()
    outcome = ProviderOutcome(result=ReviewResult(verdict='accepted_with_notes', score=4,
        findings=[Finding(code='material_overuse', severity='warning', message='overuse', evidence_refs=['material_1'])], missing_evidence=[], limitations=[]))
    assert finalize_result(value, assess_rules(value), outcome).verdict == 'human_review'


@pytest.mark.parametrize('verdict', ['accepted', 'requires_rework'])
def test_semantic_verdict_without_grounded_analysis_is_human_review(verdict):
    from app.modules.ai_review.schemas import ProviderOutcome, ReviewResult
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import finalize_result

    value = review()
    outcome = ProviderOutcome(result=ReviewResult(verdict=verdict, score=5, findings=[], missing_evidence=[], limitations=[]))
    result = finalize_result(value, assess_rules(value), outcome)
    assert result.verdict == 'human_review' and result.score is None


def test_unknown_photo_quality_can_escalate_only_after_actual_legibility_assessment():
    from app.modules.ai_review.schemas import ProviderOutcome, ReviewResult
    from app.modules.ai_review.service import can_escalate

    value = review()
    for photo in value.photo_refs:
        photo['quality'] = 'unknown'
    outcome = ProviderOutcome(result=ReviewResult(verdict='human_review', score=None, findings=[], missing_evidence=[], limitations=[]),
                              unresolved_conflict=True, conflict_refs=['problem', 'photo_after'], legible_refs=[])
    assert not can_escalate(value, outcome)
    outcome.legible_refs = ['photo_after']
    assert can_escalate(value, outcome)


def test_visual_acceptance_requires_legible_current_after_evidence():
    from app.modules.ai_review.schemas import Finding, ProviderOutcome, ReviewResult
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import finalize_result

    value = review()
    result = ReviewResult(verdict='accepted', score=5, findings=[Finding(code='work_matches_problem', severity='info',
        message='Видимый результат соответствует заявке.', evidence_refs=['problem', 'work_description', 'photo_after'])], missing_evidence=[], limitations=[])
    outcome = ProviderOutcome(result=result)
    assert finalize_result(value, assess_rules(value), outcome).verdict == 'human_review'
    outcome.legible_refs = ['photo_after']
    assert finalize_result(value, assess_rules(value), outcome).verdict == 'accepted'


def test_no_norm_overuse_claim_cannot_hide_in_semantic_message():
    from app.modules.ai_review.schemas import Finding, ProviderOutcome, ReviewResult
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import finalize_result

    value = review(11)
    result = ReviewResult(verdict='accepted', score=5, findings=[Finding(code='work_matches_problem', severity='info',
        message='Работы соответствуют, но расход материала завышен.', evidence_refs=['problem', 'work_description', 'photo_after'])], missing_evidence=[], limitations=[])
    outcome = ProviderOutcome(result=result, legible_refs=['photo_after'])
    final = finalize_result(value, assess_rules(value), outcome)
    assert final.verdict == 'human_review'
    assert all('завышен' not in f.message for f in final.findings)


def test_calculated_material_timing_facts_are_not_semantic_escalation():
    from app.modules.ai_review.schemas import ProviderOutcome, ReviewResult
    from app.modules.ai_review.service import can_escalate

    outcome = ProviderOutcome(result=ReviewResult(verdict='human_review', score=None, findings=[], missing_evidence=[], limitations=[]),
        unresolved_conflict=True, conflict_refs=['material_1', 'timing_1'])
    assert not can_escalate(review(), outcome)
