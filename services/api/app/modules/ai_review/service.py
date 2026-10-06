from __future__ import annotations
import re

from .rules import assess_rules
from .schemas import Finding, ImageEvidence, ProviderOutcome, ReviewInput, ReviewResult, RuleAssessment, StagePlan

BLOCKING_CODES = {'duplicate_evidence', 'photo_unusable', 'completion_unverified', 'missing_required_photo', 'report_incomplete'}
FORBIDDEN_CODES = {'automatic_closure', 'hidden_component_certified', 'safe_start_certified'}


def select_primary(value: ReviewInput, rules: RuleAssessment) -> StagePlan:
    from app.core.config import settings

    work_type = next((c.get('work_type') for c in value.checklist if c.get('code') == 'work_type'), None)
    planned = work_type == 'planned' if work_type is not None else value.problem.lstrip().lower().startswith(('плановый', 'planned'))
    mandatory = any(c.get('code') == 'mandatory_after_photo' and c.get('required', True) for c in value.checklist)
    light = planned and not value.photo_refs and not mandatory and not rules.anomalies
    return StagePlan(stage='primary', model=getattr(settings, 'ai_light_model', 'gpt-6-luna') if light else (settings.ai_model or 'gpt-6.1-sol'),
                     reasoning='low' if light else 'medium')


def escalation_plan() -> StagePlan:
    from app.core.config import settings

    return StagePlan(stage='escalation', model=getattr(settings, 'ai_complex_model', 'gpt-6-astra'), reasoning='medium')


def can_escalate(value: ReviewInput, outcome: ProviderOutcome) -> bool:
    if outcome.error_code or not outcome.result or not outcome.unresolved_conflict or not outcome.conflict_refs:
        return False
    if assess_rules(value).result is not None:
        return False
    if outcome.result.missing_evidence or any(f.code in BLOCKING_CODES for f in outcome.result.findings):
        return False
    known = value.evidence_ids()
    refs = set(outcome.conflict_refs)
    semantic_refs = {'problem', 'work_description'} | {p['id'] for p in value.photo_refs}
    if not refs <= semantic_refs or len(refs) < 2:
        return False
    if any(not set(f.evidence_refs) <= known for f in outcome.result.findings):
        return False
    for photo in value.photo_refs:
        if photo['id'] in refs and (photo.get('quality') == 'unusable' or photo['id'] not in outcome.legible_refs):
            return False
    return True


def human_result(rules: RuleAssessment, code: str) -> ReviewResult:
    return ReviewResult(verdict='human_review', score=None,
                        findings=[*rules.findings, Finding(code=code, severity='warning', message='Автоматическая проверка недоступна или недостаточно надёжна; требуется мастер.', evidence_refs=[])],
                        missing_evidence=[], limitations=rules.limitations)


def finalize_result(value: ReviewInput, rules: RuleAssessment, outcome: ProviderOutcome) -> ReviewResult:
    if rules.result is not None:
        return rules.result
    if outcome.error_code or outcome.result is None:
        return human_result(rules, outcome.error_code or 'provider_unavailable')
    result = outcome.result
    refs = value.evidence_ids()
    no_norm = {m['id'] for m in value.material_checks if m.get('norm_quantity') is None}
    verified_overuse = {ref for f in rules.findings if f.code == 'material_overuse' for ref in f.evidence_refs}
    invalid = any(not set(f.evidence_refs) <= refs for f in result.findings)
    invalid |= any(f.code in FORBIDDEN_CODES for f in result.findings)
    invalid |= any(f.code == 'material_overuse' and not set(f.evidence_refs) <= verified_overuse for f in result.findings)
    invalid |= any(f.code == 'material_overuse' and (not f.evidence_refs or any(r in no_norm for r in f.evidence_refs) or not any(m['id'] in f.evidence_refs and m.get('norm_quantity') is not None for m in value.material_checks)) for f in result.findings)
    if no_norm:
        invalid |= any(re.search(r'(завыш|перерасход|overuse|excessive.{0,20}(material|consumption)|расход.{0,30}превыш)', f.message, re.IGNORECASE) for f in result.findings)
    if invalid:
        return human_result(rules, 'invalid_provider_evidence')
    semantic_refs = {'problem', 'work_description'}
    positive = any(f.code == 'work_matches_problem' and semantic_refs <= set(f.evidence_refs) for f in result.findings)
    if value.photo_refs:
        after_refs = {p['id'] for p in value.photo_refs if p.get('phase') == 'after'} & set(outcome.legible_refs)
        positive = positive and any(f.code == 'work_matches_problem' and set(f.evidence_refs) & after_refs for f in result.findings)
    negative = any(f.code == 'work_problem_mismatch' and f.severity == 'error' and semantic_refs <= set(f.evidence_refs) for f in result.findings)
    if result.verdict in {'accepted', 'accepted_with_notes'} and not positive:
        return human_result(rules, 'completion_unverified')
    if result.verdict == 'requires_rework' and not negative:
        return human_result(rules, 'invalid_provider_evidence')
    combined = list(rules.findings)
    existing = {(f.code, tuple(f.evidence_refs)) for f in combined}
    combined.extend(f for f in result.findings if (f.code, tuple(f.evidence_refs)) not in existing)
    verdict = result.verdict
    if outcome.unresolved_conflict or any(f.code in BLOCKING_CODES for f in combined):
        verdict = 'human_review'
    elif verdict == 'accepted' and any(f.severity != 'info' for f in combined):
        verdict = 'accepted_with_notes'
    limitations = list(dict.fromkeys([*rules.limitations, *result.limitations]))
    if not value.photo_refs:
        limitations.append('Проверен только текст; визуальное подтверждение не выполнялось.')
    return ReviewResult(verdict=verdict, score=None if verdict == 'human_review' else result.score,
                        findings=combined, missing_evidence=result.missing_evidence,
                        limitations=limitations)


def evaluate_stage(value: ReviewInput, provider, plan: StagePlan, images: dict[str, ImageEvidence] | None = None,
                   previous: ProviderOutcome | None = None) -> ProviderOutcome:
    return provider.review(value, plan, images=images or {}, previous=previous)


def evaluate_submission(value: ReviewInput, provider=None, images: dict[str, ImageEvidence] | None = None) -> ReviewResult:
    rules = assess_rules(value)
    if rules.result is not None:
        return rules.result
    if provider is None:
        return human_result(rules, 'provider_unavailable')
    plan = select_primary(value, rules)
    outcome = evaluate_stage(value, provider, plan, images)
    if plan.model != 'gpt-6-luna' and can_escalate(value, outcome):
        outcome = evaluate_stage(value, provider, escalation_plan(), images, outcome)
    result = finalize_result(value, rules, outcome)
    if plan.model == 'gpt-6-luna' and not any('только текст' in text for text in result.limitations):
        result.limitations.append('Проверен только текст; визуальное подтверждение не выполнялось.')
    return result
