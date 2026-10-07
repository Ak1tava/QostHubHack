from __future__ import annotations

import re

from .rules import assess_rules
from .schemas import (
    Finding,
    ImageEvidence,
    ProviderOutcome,
    ReviewInput,
    ReviewResult,
    RuleAssessment,
    StagePlan,
)

BLOCKING_CODES = {
    "duplicate_evidence",
    "photo_unusable",
    "completion_unverified",
    "missing_required_photo",
    "report_incomplete",
    "unusable_images",
    "photo_subject_mismatch",
    "comparison_unavailable",
    "evidence_conflict",
}
FORBIDDEN_CODES = {
    "automatic_closure",
    "hidden_component_certified",
    "safe_start_certified",
}


def select_primary(value: ReviewInput, rules: RuleAssessment) -> StagePlan:
    from app.core.config import settings

    work_type = next(
        (c.get("work_type") for c in value.checklist if c.get("code") == "work_type"),
        None,
    )
    planned = (
        work_type == "planned"
        if work_type is not None
        else value.problem.lstrip().lower().startswith(("плановый", "planned"))
    )
    mandatory = any(
        c.get("code") == "mandatory_after_photo" and c.get("required", True)
        for c in value.checklist
    )
    light = planned and not value.photo_refs and not mandatory and not rules.anomalies
    return StagePlan(
        stage="primary",
        model=getattr(settings, "ai_light_model", "gpt-6-luna")
        if light
        else (settings.ai_model or "gpt-6.1-sol"),
        reasoning="low" if light else "medium",
    )


def escalation_plan() -> StagePlan:
    from app.core.config import settings

    return StagePlan(
        stage="escalation",
        model=getattr(settings, "ai_complex_model", "gpt-6-astra"),
        reasoning="medium",
    )


def can_escalate(value: ReviewInput, outcome: ProviderOutcome) -> bool:
    if (
        outcome.error_code
        or not outcome.result
        or not outcome.unresolved_conflict
        or not outcome.conflict_refs
    ):
        return False
    if assess_rules(value).result is not None:
        return False
    if outcome.result.missing_evidence or any(
        f.code in BLOCKING_CODES for f in outcome.result.findings
    ):
        return False
    known = value.evidence_ids()
    refs = set(outcome.conflict_refs)
    semantic_refs = {"problem", "work_description"} | {
        p["id"] for p in value.photo_refs
    }
    if not refs <= semantic_refs or len(refs) < 2:
        return False
    if any(not set(f.evidence_refs) <= known for f in outcome.result.findings):
        return False
    for photo in value.photo_refs:
        if photo["id"] in refs and (
            photo.get("quality") == "unusable"
            or photo["id"] not in outcome.legible_refs
        ):
            return False
    return True


REJECTION_MESSAGES = {
    "missing_work_match_finding": "Ответ не содержит подтверждённого соответствия работ заявке.",
    "missing_text_evidence_references": "Вывод не связан одновременно с заявкой и описанием работ.",
    "missing_legible_after_reference": "Не подтверждена пригодность фото после для проверки результата.",
    "unknown_evidence_reference": "Модель сослалась на отсутствующее доказательство.",
    "unverified_material_claim": "Утверждение о расходе не подтверждено серверным расчётом.",
    "forbidden_certification": "Ответ выходит за пределы проверки видимых доказательств.",
}


def human_result(
    rules: RuleAssessment, code: str, reasons: list[str] | None = None
) -> ReviewResult:
    return ReviewResult(
        verdict="human_review",
        score=None,
        findings=[
            *rules.findings,
            Finding(
                code=code,
                severity="warning",
                message=" ".join(
                    REJECTION_MESSAGES.get(reason, "") for reason in (reasons or [])
                ).strip()
                or "Автоматическая проверка недоступна или недостаточно надёжна; требуется мастер.",
                evidence_refs=[],
            ),
        ],
        missing_evidence=[],
        limitations=rules.limitations,
    )


def finalize_result(
    value: ReviewInput,
    rules: RuleAssessment,
    outcome: ProviderOutcome,
    *,
    diagnostics: dict | None = None,
) -> ReviewResult:
    reasons = []
    if diagnostics is not None:
        diagnostics["rejection_reasons"] = reasons

    def rejected(code, *details):
        reasons.extend(details)
        return human_result(rules, code, reasons)

    if rules.result is not None:
        return rules.result
    if outcome.error_code or outcome.result is None:
        return rejected(
            outcome.error_code or "provider_unavailable",
            outcome.error_code or "provider_unavailable",
        )
    result = outcome.result
    refs = value.evidence_ids()
    no_norm = {m["id"] for m in value.material_checks if m.get("norm_quantity") is None}
    verified_overuse = {
        ref
        for f in rules.findings
        if f.code == "material_overuse"
        for ref in f.evidence_refs
    }
    invalid = any(not set(f.evidence_refs) <= refs for f in result.findings)
    if invalid:
        reasons.append("unknown_evidence_reference")
    forbidden = any(f.code in FORBIDDEN_CODES for f in result.findings)
    invalid |= forbidden
    if forbidden:
        reasons.append("forbidden_certification")
    invalid |= any(
        f.code == "material_overuse" and not set(f.evidence_refs) <= verified_overuse
        for f in result.findings
    )
    invalid |= any(
        f.code == "material_overuse"
        and (
            not f.evidence_refs
            or any(r in no_norm for r in f.evidence_refs)
            or not any(
                m["id"] in f.evidence_refs and m.get("norm_quantity") is not None
                for m in value.material_checks
            )
        )
        for f in result.findings
    )

    # Explicit non-assessment is not a claim of excessive consumption. Mixed affirmative
    # statements still fail closed. Such wording never propagates from model to C5.
    def material_claim(message):
        remaining = re.sub(
            r"перерасход\s+не\s+оценивается(?:\s+без\s+нормы)?",
            "",
            message,
            flags=re.IGNORECASE,
        )
        remaining = re.sub(
            r"нельзя\s+утверждать\s+завышение\s+расхода\s+без\s+нормы",
            "",
            remaining,
            flags=re.IGNORECASE,
        )
        return bool(
            re.search(
                r"(завыш|перерасход|overuse|excessive.{0,20}(material|consumption)|расход.{0,30}превыш)",
                remaining,
                re.IGNORECASE,
            )
        )

    if no_norm and any(material_claim(f.message) for f in result.findings):
        invalid = True
        reasons.append("unverified_material_claim")
    if invalid:
        return rejected(
            "invalid_provider_evidence",
            *([] if reasons else ["invalid_provider_evidence"]),
        )
    semantic_refs = {"problem", "work_description"}
    positive = any(
        f.code == "work_matches_problem" and semantic_refs <= set(f.evidence_refs)
        for f in result.findings
    )
    if value.photo_refs:
        after_refs = {
            p["id"] for p in value.photo_refs if p.get("phase") == "after"
        } & set(outcome.legible_refs)
        positive = any(
            f.code == "work_matches_problem"
            and semantic_refs <= set(f.evidence_refs)
            and set(f.evidence_refs) & after_refs
            for f in result.findings
        )
    negative = any(
        f.code == "work_problem_mismatch"
        and f.severity == "error"
        and semantic_refs <= set(f.evidence_refs)
        for f in result.findings
    )
    if result.verdict in {"accepted", "accepted_with_notes"} and not positive:
        matching = [f for f in result.findings if f.code == "work_matches_problem"]
        reason = (
            "missing_work_match_finding"
            if not matching
            else (
                "missing_text_evidence_references"
                if not any(semantic_refs <= set(f.evidence_refs) for f in matching)
                else "missing_legible_after_reference"
            )
        )
        return rejected("completion_unverified", reason)
    if result.verdict == "requires_rework" and not negative:
        return rejected(
            "invalid_provider_evidence",
            *([] if reasons else ["invalid_provider_evidence"]),
        )
    combined = list(rules.findings)
    existing = {(f.code, tuple(f.evidence_refs)) for f in combined}
    # Material/timing explanations are exclusively server authored. Do not carry
    # provider arithmetic or normative commentary even inside a semantic finding.
    server_codes = {
        "material_overuse",
        "norm_unavailable",
        "late_submission",
        "timing_inconsistent",
        "report_complete",
    }
    commentary = re.compile(
        r"(норм|расход|материал|просроч|срок|опозд|\b(?:material|consumption|deadline|overdue|late)\b)",
        re.IGNORECASE,
    )

    def semantic_finding(f):
        if commentary.search(f.message):
            return f.model_copy(
                update={
                    "message": "По указанным доказательствам описание работ соответствует заявке."
                    if f.code == "work_matches_problem"
                    else "Требуется проверить соответствие работ и видимых доказательств."
                }
            )
        return f

    combined.extend(
        semantic_finding(f)
        for f in result.findings
        if f.code not in server_codes
        and (f.code, tuple(f.evidence_refs)) not in existing
    )
    verdict = result.verdict
    if outcome.unresolved_conflict or any(f.code in BLOCKING_CODES for f in combined):
        verdict = "human_review"
    elif verdict == "accepted" and any(f.severity != "info" for f in combined):
        verdict = "accepted_with_notes"
    limitations = list(
        dict.fromkeys(
            [
                *rules.limitations,
                *(text for text in result.limitations if not commentary.search(text)),
            ]
        )
    )
    if not value.photo_refs:
        limitations.append(
            "Проверен только текст; визуальное подтверждение не выполнялось."
        )
    return ReviewResult(
        verdict=verdict,
        score=None if verdict == "human_review" else result.score,
        findings=combined,
        missing_evidence=result.missing_evidence,
        limitations=limitations,
    )


def evaluate_stage(
    value: ReviewInput,
    provider,
    plan: StagePlan,
    images: dict[str, ImageEvidence] | None = None,
    previous: ProviderOutcome | None = None,
) -> ProviderOutcome:
    return provider.review(value, plan, images=images or {}, previous=previous)


def evaluate_submission(
    value: ReviewInput,
    provider=None,
    images: dict[str, ImageEvidence] | None = None,
    *,
    diagnostics: list[dict] | None = None,
) -> ReviewResult:
    rules = assess_rules(value)
    if rules.result is not None:
        return rules.result
    if provider is None:
        return human_result(rules, "provider_unavailable")
    plan = select_primary(value, rules)
    outcome = evaluate_stage(value, provider, plan, images)
    if plan.model != "gpt-6-luna" and can_escalate(value, outcome):
        if diagnostics is not None:
            diagnostics.append(
                {
                    "stage": "primary",
                    "provider_outcome": outcome.model_dump(mode="json"),
                    "rejection_reasons": ["semantic_conflict_escalated"],
                }
            )
        previous = outcome
        plan = escalation_plan()
        outcome = evaluate_stage(value, provider, plan, images, previous)
    trace = {"stage": plan.stage, "provider_outcome": outcome.model_dump(mode="json")}
    result = finalize_result(value, rules, outcome, diagnostics=trace)
    if diagnostics is not None:
        diagnostics.append(trace)
    if plan.model == "gpt-6-luna" and not any(
        "только текст" in text for text in result.limitations
    ):
        result.limitations.append(
            "Проверен только текст; визуальное подтверждение не выполнялось."
        )
    return result
