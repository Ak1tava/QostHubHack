import json
from decimal import Decimal

import pytest


def test_quality_budget_preserves_three_dollars_for_holdout_and_never_resets(tmp_path):
    from app.modules.ai_review.eval_runner import BudgetExceeded
    from app.modules.ai_review.quality_eval import QualityBudgetLedger

    path = tmp_path / "budget.json"
    dev = QualityBudgetLedger(path, "dev")
    dev.reserve("first", "4.5")
    with pytest.raises(BudgetExceeded):
        dev.reserve("too-much", ".51")
    holdout = QualityBudgetLedger(path, "holdout")
    holdout.reserve("control", "3.5")
    assert holdout.spent == Decimal("8")
    with pytest.raises(BudgetExceeded):
        QualityBudgetLedger(path, "comparison").reserve("reset", ".01")


def test_quality_budget_refuses_corrupt_or_other_budget_ledgers(tmp_path):
    from app.modules.ai_review.quality_eval import QualityBudgetLedger

    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"limit_usd": "5", "calls": []}))
    with pytest.raises(ValueError):
        QualityBudgetLedger(path, "dev")


def test_development_supports_two_prompt_versions_and_freeze_stops_tuning(tmp_path):
    from app.modules.ai_review.quality_eval import register_development

    register_development(tmp_path, "one")
    register_development(tmp_path, "one")
    register_development(tmp_path, "two")
    with pytest.raises(ValueError):
        register_development(tmp_path, "three")
    (tmp_path / "frozen.json").write_text("{}")
    with pytest.raises(ValueError):
        register_development(tmp_path, "two")


def test_quality_corpus_has_independent_source_groups_and_twelve_control_cases():
    from app.modules.ai_review.quality_eval import load_cases

    cases = load_cases()
    dev = {s for c in cases if c["split"] == "dev" for s in c["source_groups"]}
    control = [c for c in cases if c["split"] == "holdout"]
    assert len(control) == 12
    assert [
        sum(c["category"] == category for c in control)
        for category in ["good", "bad", "ambiguous"]
    ] == [4, 4, 4]
    assert not dev & {s for c in control for s in c["source_groups"]}


def test_evaluation_trace_is_persisted_even_when_server_rejects_model(tmp_path):
    from app.modules.ai_review.eval_runner import BudgetedProvider, BudgetLedger
    from app.modules.ai_review.schemas import StagePlan
    from test_ai_provider import text_review
    from test_ai_quality import good

    class Provider:
        last_diagnostics = {
            "structured_response": {"unresolved_conflict": False},
            "rejection_reasons": [],
        }

        def review(self, *args, **kwargs):
            return good(text_review()).model_copy(
                update={"usage": {"input_tokens": 10, "output_tokens": 5}}
            )

    ledger = BudgetLedger(tmp_path / "budget.json")
    wrapped = BudgetedProvider(Provider(), ledger)
    wrapped.case_id = "test"
    wrapped.review(
        text_review(),
        StagePlan(stage="primary", model="gpt-6.1-sol", reasoning="medium"),
        images={},
    )
    saved = json.loads(ledger.path.read_text())["calls"][0]["metadata"]
    assert saved["provider_diagnostics"]["structured_response"] == {
        "unresolved_conflict": False
    }


def test_acceptance_does_not_pass_if_cases_are_missing_or_clear_bad_is_accepted():
    from app.modules.ai_review.quality_eval import acceptance

    rows = (
        [{"category": "good", "verdict": "accepted"}] * 4
        + [{"category": "bad", "verdict": "requires_rework"}] * 4
        + [{"category": "ambiguous", "verdict": "human_review"}] * 4
    )
    assert acceptance(rows)["passed"] is True
    assert acceptance(rows[:-1])["passed"] is False
    rows[4] = {"category": "bad", "verdict": "accepted"}
    assert acceptance(rows)["passed"] is False


def test_quality_reservation_uses_pixels_not_jpeg_transport_byte_length(tmp_path):
    from io import BytesIO

    from app.modules.ai_review.quality_eval import (
        QualityBudgetedProvider,
        QualityBudgetLedger,
    )
    from app.modules.ai_review.schemas import ImageEvidence, StagePlan
    from PIL import Image
    from test_ai_quality import good
    from test_ai_review import review

    # A detailed JPEG may be large while pixel/token geometry remains bounded.
    stream = BytesIO()
    Image.effect_noise((1024, 1024), 100).convert("RGB").save(
        stream, format="JPEG", quality=98
    )
    assert len(stream.getvalue()) > 100000

    class Provider:
        def review(self, *args, **kwargs):
            return good(review()).model_copy(
                update={"usage": {"input_tokens": 100, "output_tokens": 20}}
            )

    ledger = QualityBudgetLedger(tmp_path / "budget.json", "comparison")
    wrapped = QualityBudgetedProvider(Provider(), ledger)
    images = {
        ref: ImageEvidence(media_type="image/jpeg", data=stream.getvalue())
        for ref in ["photo_before", "photo_after"]
    }
    wrapped.review(
        review(),
        StagePlan(stage="escalation", model="gpt-6-astra", reasoning="medium"),
        images=images,
    )
    assert Decimal(ledger.records[0]["reserved_usd"]) < Decimal("5")
    assert ledger.spent < Decimal(".02")


def test_comparison_never_repeats_an_unknown_usage_call(tmp_path):
    from app.modules.ai_review.quality_eval import (
        QualityBudgetLedger,
        pending_comparison,
    )

    ledger = QualityBudgetLedger(tmp_path / "budget.json", "comparison")
    ledger.reserve(
        "attempt",
        "1",
        {"case_id": "first", "model": "gpt-6-astra", "stage": "escalation"},
    )
    ledger.settle("attempt", None)
    assert pending_comparison(
        [{"case_id": "first"}, {"case_id": "second"}], ledger
    ) == [{"case_id": "second"}]


def test_media_filename_cannot_hide_holdout_photo_in_development_group(tmp_path):
    from app.modules.ai_review.quality_eval import load_cases

    cases = load_cases()
    cases[0]["photos"]["after"] = "corrocoat-after.normalized.jpg"
    (tmp_path / "cases.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cases))
    with pytest.raises(ValueError):
        load_cases(tmp_path)


def test_photo_eval_uses_real_worker_reference_format_instead_of_example_ids(tmp_path):
    from PIL import Image
    from uuid import UUID
    from app.modules.ai_review.quality_eval import load_photo_case

    Image.new("RGB", (200, 200), "gray").save(tmp_path / "unit-after.jpg")
    case = {
        "case_id": "real-reference",
        "problem": "Очистить корпус",
        "work_description": "Корпус очищен",
        "photos": {"after": "unit-after.jpg"},
    }
    value, images = load_photo_case(case, tmp_path)
    ref = value.photo_refs[0]["id"]
    assert ref.startswith("photo:")
    UUID(ref.removeprefix("photo:"))
    assert "photo_after" not in value.evidence_ids()
    assert set(images) == {ref}
