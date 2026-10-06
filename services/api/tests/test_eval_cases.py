"""Offline corpus integrity checks; these do not run or score an AI model."""

import json
from collections import Counter
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[3]
EVALS = ROOT / "evals"
VERDICTS = {"accepted", "accepted_with_notes", "requires_rework", "human_review"}
# Reserved before prompt tuning. Changing this split requires a new corpus version.
HOLDOUT_IDS = {f"T09-{number:03}" for number in range(21, 33)}
REQUIRED_SCENARIOS = {
    "good_report",
    "missing_photo",
    "duplicate",
    "blurred_image",
    "unrelated_works",
    "material_without_norm",
    "prompt_injection",
}


def load_cases():
    path = EVALS / "cases.jsonl"
    assert path.is_file(), "T09 labeled evaluation corpus is missing"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert all(line.strip() for line in lines), "Blank JSONL records are forbidden"
    return [json.loads(line) for line in lines]


def load_fixture(case):
    relative = Path(case["input_fixture"])
    assert not relative.is_absolute() and ".." not in relative.parts
    path = (EVALS / relative).resolve()
    assert path.is_relative_to((EVALS / "fixtures").resolve())
    assert path.is_file(), f"Missing fixture: {case['input_fixture']}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_labeled_corpus_has_required_size_unique_ids_and_contract_verdicts():
    cases = load_cases()
    assert len(cases) >= 30
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert len({case["input_fixture"] for case in cases}) == len(cases)
    for case in cases:
        assert set(case) == {
            "case_id",
            "split",
            "input_fixture",
            "expected_verdict",
            "required_findings",
        }
        assert case["split"] in {"dev", "holdout"}
        assert case["expected_verdict"] in VERDICTS
        findings = case["required_findings"]
        assert isinstance(findings, list) and findings
        assert all(isinstance(code, str) and code.strip() for code in findings)
        assert len(set(findings)) == len(findings)
    assert {case["expected_verdict"] for case in cases} == VERDICTS


def test_holdout_is_predesignated_and_covers_required_failure_classes():
    cases = load_cases()
    holdout = [case for case in cases if case["split"] == "holdout"]
    assert {case["case_id"] for case in holdout} == HOLDOUT_IDS
    assert len(holdout) >= 10
    for split in ("dev", "holdout"):
        scenarios = {
            load_fixture(case)["scenario"] for case in cases if case["split"] == split
        }
        assert REQUIRED_SCENARIOS <= scenarios


def test_review_input_has_contract_fields_and_resolvable_synthetic_evidence():
    for case in load_cases():
        fixture = load_fixture(case)
        assert fixture["synthetic"] is True
        review = fixture["review_input"]
        assert set(review) == {
            "work_order_id",
            "submission_revision",
            "assignment_version",
            "problem",
            "work_description",
            "material_checks",
            "timing_checks",
            "photo_refs",
            "checklist",
        }
        UUID(review["work_order_id"])
        assert review["submission_revision"] >= 1
        assert review["assignment_version"] >= 1
        assert review["problem"] and review["work_description"]
        refs = set(fixture["evidence_manifest"])
        assert {"problem", "work_description"} <= refs
        for field in ("material_checks", "timing_checks", "photo_refs", "checklist"):
            for evidence in review[field]:
                assert evidence["id"] in refs
        for photo in review["photo_refs"]:
            path = (EVALS / photo["fixture_path"]).resolve()
            assert path.is_relative_to((EVALS / "fixtures").resolve())
            assert path.suffix == ".svg" and path.is_file()
            assert "SYNTHETIC" in path.read_text(encoding="utf-8")
        assert set(fixture["forbidden_findings"]).isdisjoint(case["required_findings"])


def test_labels_follow_completeness_photo_quality_and_norm_rules():
    scenarios = Counter()
    for case in load_cases():
        fixture = load_fixture(case)
        scenario = fixture["scenario"]
        scenarios[scenario] += 1
        review = fixture["review_input"]
        findings = set(case["required_findings"])
        if scenario == "missing_photo":
            assert not any(photo["phase"] == "after" for photo in review["photo_refs"])
            assert case["expected_verdict"] == "requires_rework"
            assert "missing_required_photo" in findings
        elif scenario == "blurred_image":
            assert any(photo["quality"] == "unusable" for photo in review["photo_refs"])
            assert case["expected_verdict"] == "human_review"
        elif scenario == "material_without_norm":
            assert all(
                item["norm_quantity"] is None for item in review["material_checks"]
            )
            assert "norm_unavailable" in findings
            assert "material_overuse" in fixture["forbidden_findings"]
        elif scenario == "prompt_injection":
            assert fixture["attack_surface"] in {"report", "photo_caption"}
            assert "untrusted_instruction_ignored" in findings
            assert "automatic_closure" in fixture["forbidden_findings"]
    assert REQUIRED_SCENARIOS <= set(scenarios)


def test_inputs_do_not_embed_expected_answers_or_personal_media():
    unique_inputs = set()
    for case in load_cases():
        fixture = load_fixture(case)
        review = fixture["review_input"]
        serialized = json.dumps(review, ensure_ascii=False, sort_keys=True)
        assert serialized not in unique_inputs, "Exact duplicate evaluation input"
        unique_inputs.add(serialized)
        assert "expected_verdict" not in serialized
        assert "required_findings" not in serialized
        assert "http://" not in serialized and "https://" not in serialized
        assert "SYNTHETIC" in fixture["provenance"]


def test_planned_cleaning_uses_cleaning_evidence_instead_of_leak_template():
    for case in load_cases():
        fixture = load_fixture(case)
        if fixture["variant"] == "planned":
            photos = fixture["review_input"]["photo_refs"]
            assert {photo["template"] for photo in photos} == {"visible_cleaning"}
            assert "filter-dirty.svg" in photos[0]["fixture_path"]
            assert "filter-clean.svg" in photos[1]["fixture_path"]
