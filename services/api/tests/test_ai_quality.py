import json

import pytest
from pydantic import ValidationError
from test_ai_review import review


def good(value, message="Видимое состояние соответствует работам."):
    from app.modules.ai_review.schemas import Finding, ProviderOutcome, ReviewResult

    return ProviderOutcome(
        result=ReviewResult(
            verdict="accepted",
            score=4,
            findings=[
                Finding(
                    code="work_matches_problem",
                    severity="info",
                    message=message,
                    evidence_refs=["problem", "work_description", "photo_after"],
                )
            ],
            missing_evidence=[],
            limitations=[],
        ),
        legible_refs=["photo_after"],
    )


def test_provider_schema_rejects_invented_or_server_owned_codes():
    from app.modules.ai_review.schemas import StageResponse

    for code in [
        "work_is_done",
        "norm_unavailable",
        "material_overuse",
        "late_submission",
    ]:
        raw = {
            "result": good(review()).result.model_dump(),
            "unresolved_conflict": False,
            "conflict_refs": [],
            "legible_refs": ["photo_after"],
        }
        raw["result"]["findings"][0]["code"] = code
        with pytest.raises(ValidationError):
            StageResponse.model_validate(raw)


def test_denial_of_material_overuse_does_not_reject_good_visual_work():
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import finalize_result

    value = review(11)
    result = finalize_result(
        value,
        assess_rules(value),
        good(value, "Работы соответствуют. Перерасход не оценивается без нормы."),
    )
    assert result.verdict == "accepted_with_notes"
    assert {f.code for f in result.findings} >= {
        "work_matches_problem",
        "norm_unavailable",
    }
    assert [f.message for f in result.findings if f.code == "norm_unavailable"] == [
        "Сопоставимой нормы расхода нет; превышение не оценивается."
    ]
    assert all("Перерасход" not in f.message for f in result.findings)


def test_denial_cannot_hide_an_affirmative_unverified_material_claim():
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import finalize_result

    value = review(11)
    result = finalize_result(
        value,
        assess_rules(value),
        good(value, "Перерасход не оценивается. Расход материала завышен."),
    )
    assert result.verdict == "human_review"


def test_semantic_provider_never_receives_numeric_material_or_timing_checks():
    from app.modules.ai_review.prompts import prompt_payload
    from app.modules.ai_review.schemas import StagePlan

    payload = json.loads(
        prompt_payload(
            review(15),
            StagePlan(stage="primary", model="gpt-6.1-sol", reasoning="medium"),
        )
    )
    assert payload["review_input"]["material_checks"] == []
    assert payload["review_input"]["timing_checks"] == []
    assert all(
        f["code"] not in {"material_overuse", "norm_unavailable", "late_submission"}
        for f in payload["server_findings"]
    )


def test_local_trace_keeps_model_result_before_guard_and_precise_rejection():
    from app.modules.ai_review.service import evaluate_submission

    value = review()

    class Provider:
        def review(self, *args, **kwargs):
            return good(value).model_copy(update={"legible_refs": []})

    trace = []
    result = evaluate_submission(value, Provider(), diagnostics=trace)
    assert result.verdict == "human_review"
    assert trace[-1]["provider_outcome"]["result"]["verdict"] == "accepted"
    assert trace[-1]["rejection_reasons"] == ["missing_legible_after_reference"]
    assert "фото после" in result.findings[-1].message.lower()


def test_provider_debug_capture_keeps_structured_response_before_legibility_guard():
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan
    from test_ai_provider import Client, parsed_response, text_review

    raw = parsed_response()
    raw.output_parsed["legible_refs"] = ["invented"]
    provider = OpenAIReviewProvider(
        "test-key", client=Client(raw), capture_diagnostics=True
    )
    result = provider.review(
        text_review(),
        StagePlan(stage="primary", model="gpt-6.1-sol", reasoning="medium"),
        images={},
    )
    assert result.error_code == "invalid_provider_evidence"
    assert provider.last_diagnostics["structured_response"]["legible_refs"] == [
        "invented"
    ]
    assert provider.last_diagnostics["rejection_reasons"] == [
        "legible_ref_not_supplied"
    ]


def test_capture_api_error_type_without_credentials_or_server_error_body():
    import httpx
    import openai
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan
    from test_ai_provider import Client, text_review

    response = httpx.Response(
        403, request=httpx.Request("POST", "https://api.openai.com/v1/responses")
    )
    error = openai.APIStatusError(
        "sensitive body must not be recorded",
        response=response,
        body={"secret": "never-log"},
    )
    provider = OpenAIReviewProvider(
        "test-key", client=Client(error), capture_diagnostics=True
    )
    result = provider.review(
        text_review(),
        StagePlan(stage="primary", model="gpt-6.1-sol", reasoning="medium"),
        images={},
    )
    assert result.error_code == "api_error"
    assert provider.last_diagnostics["http_status"] == 403
    assert "never-log" not in json.dumps(provider.last_diagnostics)


def test_visual_acceptance_cannot_join_unrelated_findings_into_one_proof():
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.schemas import Finding
    from app.modules.ai_review.service import finalize_result

    value = review()
    outcome = good(value)
    outcome.result.findings = [
        Finding(
            code="work_matches_problem",
            severity="info",
            message="Текст совпадает.",
            evidence_refs=["problem", "work_description"],
        ),
        Finding(
            code="work_matches_problem",
            severity="info",
            message="Фото читается.",
            evidence_refs=["photo_after"],
        ),
    ]
    assert (
        finalize_result(value, assess_rules(value), outcome).verdict == "human_review"
    )


def test_provider_material_and_timing_commentary_in_limitations_does_not_propagate():
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import finalize_result

    value = review()
    outcome = good(value)
    outcome.result.limitations = [
        "Расход материала завышен.",
        "Отчёт сдан с просрочкой.",
        "Скрытые узлы не проверялись.",
    ]
    result = finalize_result(value, assess_rules(value), outcome)
    assert "Расход материала завышен." not in result.limitations
    assert "Отчёт сдан с просрочкой." not in result.limitations
    assert "Скрытые узлы не проверялись." in result.limitations


def test_grounded_semantic_conflict_can_escalate_but_is_not_accepted_unresolved():
    from app.modules.ai_review.service import can_escalate, finalize_result
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.schemas import Finding

    value = review()
    outcome = good(value)
    outcome.result.verdict = "human_review"
    outcome.result.score = None
    outcome.result.findings = [
        Finding(
            code="evidence_conflict",
            severity="warning",
            message="Чёткое фото расходится с описанием.",
            evidence_refs=["problem", "work_description", "photo_after"],
        )
    ]
    outcome.unresolved_conflict = True
    outcome.conflict_refs = ["problem", "work_description", "photo_after"]
    assert can_escalate(value, outcome)
    assert (
        finalize_result(value, assess_rules(value), outcome).verdict == "human_review"
    )
