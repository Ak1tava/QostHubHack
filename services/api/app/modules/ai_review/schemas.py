from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewInput(StrictModel):
    work_order_id: UUID
    submission_revision: int = Field(ge=1)
    assignment_version: int = Field(ge=1)
    problem: str
    work_description: str
    material_checks: list[dict[str, Any]]
    timing_checks: list[dict[str, Any]]
    photo_refs: list[dict[str, Any]]
    checklist: list[dict[str, Any]]

    @model_validator(mode="after")
    def unique_evidence(self):
        ids = ["problem", "work_description"]
        for collection in (
            self.material_checks,
            self.timing_checks,
            self.photo_refs,
            self.checklist,
        ):
            for item in collection:
                value = item.get("id")
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Server evidence requires a nonempty id")
                ids.append(value)
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence ids must be unique, including reserved ids")
        return self

    def evidence_ids(self) -> set[str]:
        return {"problem", "work_description"} | {
            item["id"]
            for collection in (
                self.material_checks,
                self.timing_checks,
                self.photo_refs,
                self.checklist,
            )
            for item in collection
        }


class Finding(StrictModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    evidence_refs: list[str]


class ReviewResult(StrictModel):
    verdict: Literal[
        "accepted", "accepted_with_notes", "requires_rework", "human_review"
    ]
    score: int | None = Field(ge=1, le=5, strict=True)
    findings: list[Finding]
    missing_evidence: list[str]
    limitations: list[str]


class StagePlan(StrictModel):
    stage: Literal["primary", "escalation"]
    model: str
    reasoning: Literal["low", "medium"]
    prompt_version: str = "t07-v2"


class ImageEvidence(StrictModel):
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    data: bytes


class ProviderOutcome(StrictModel):
    result: ReviewResult | None = None
    error_code: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: int = 0
    response_id: str | None = None
    is_mock: bool = False
    unresolved_conflict: bool = False
    conflict_refs: list[str] = Field(default_factory=list)
    legible_refs: list[str] = Field(default_factory=list)
    retryable: bool = False
    retry_after_seconds: float | None = None


# Private provider schema; public C5 Finding/ReviewResult stay unchanged.
class ProviderFinding(Finding):
    code: Literal[
        "work_matches_problem",
        "work_problem_mismatch",
        "visible_leak_comparison",
        "visible_cleaning_comparison",
        "visible_cover_present",
        "visible_surface_change",
        "evidence_conflict",
        "unusable_images",
        "photo_subject_mismatch",
        "comparison_unavailable",
        "untrusted_instruction_ignored",
    ]


class ProviderResult(ReviewResult):
    findings: list[ProviderFinding]


class StageResponse(StrictModel):
    result: ProviderResult
    unresolved_conflict: bool
    conflict_refs: list[str]
    legible_refs: list[str]


class RuleAssessment(StrictModel):
    result: ReviewResult | None = None
    findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    anomalies: bool = False
