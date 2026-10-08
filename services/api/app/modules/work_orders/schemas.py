from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.modules.ai_review.schemas import ReviewResult
from app.modules.photos.schemas import PhotoView

WorkOrderPriority = Literal["emergency", "high", "normal", "planned"]
TemplateId = Literal["visible_leak", "visible_element"]


class TemplateChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=1000)
    required: bool = True


class TemplatePhotoRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    before: int = Field(ge=0, le=5)
    after: int = Field(ge=0, le=20)


class WorkOrderTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: TemplateId
    version: int = Field(gt=0)
    title: str
    initial_description: str
    instructions: list[str]
    checklist: list[TemplateChecklistItem]
    photo_requirements: TemplatePhotoRequirements


class WorkOrderTemplateList(BaseModel):
    items: list[WorkOrderTemplate]


class TemplateAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=64)
    checked: StrictBool

WorkOrderStatus = Literal[
    "ISSUED",
    "ACCEPTED",
    "QUEUED",
    "REJECTED",
    "IN_PROGRESS",
    "PAUSED",
    "SUBMITTED",
    "AI_REVIEW",
    "REWORK",
    "CLOSED",
    "CANCELLED",
]


def validate_assignment(assignee_id, brigade_id, responsible_id):
    if assignee_id is not None:
        valid = brigade_id is None and responsible_id is None
    else:
        valid = brigade_id is not None and responsible_id is not None
    if not valid:
        raise ValueError("Assign one worker or a brigade with a responsible worker")


class WorkOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    work_type: Literal["planned", "emergency"]
    description: str = Field(min_length=1, max_length=10000)
    area_id: UUID
    equipment_id: UUID
    assignee_id: UUID | None = None
    brigade_id: UUID | None = None
    responsible_id: UUID | None = None
    priority: WorkOrderPriority = "normal"
    due_at: AwareDatetime
    template_id: TemplateId | None = None

    @model_validator(mode="after")
    def assignment_is_complete(self):
        validate_assignment(self.assignee_id, self.brigade_id, self.responsible_id)
        return self


class ActionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal[
        "accept", "queue", "reject", "reassign", "start", "pause", "resume",
        "restart", "cancel", "reprioritize",
    ]
    expected_version: int = Field(gt=0)
    reason: str | None = Field(default=None, min_length=1, max_length=4000)
    assignee_id: UUID | None = None
    brigade_id: UUID | None = None
    responsible_id: UUID | None = None
    priority: WorkOrderPriority | None = None

    @model_validator(mode="after")
    def fields_match_action(self):
        allowed = {"action", "expected_version"}
        if self.action in {"reject", "pause", "reassign", "cancel"}:
            allowed.add("reason")
            if self.reason is None:
                raise ValueError("This action requires a reason")
        if self.action == "reassign":
            allowed.update({"assignee_id", "brigade_id", "responsible_id"})
            validate_assignment(self.assignee_id, self.brigade_id, self.responsible_id)
        if self.action == "reprioritize":
            allowed.add("priority")
            if self.priority is None:
                raise ValueError("Reprioritization requires a priority")
        if self.model_fields_set - allowed:
            raise ValueError("Fields do not apply to this action")
        return self


class InternalActionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["submit", "begin_review", "request_rework", "close", "override_close"]
    expected_version: int = Field(gt=0)
    assignment_version: int = Field(gt=0)
    submission_id: UUID
    reason: str | None = Field(default=None, min_length=1, max_length=4000)
    review_id: UUID | None = None
    decision_id: UUID | None = None

    @model_validator(mode="after")
    def reason_is_present(self):
        if self.action in {"request_rework", "override_close"} and self.reason is None:
            raise ValueError("This action requires a reason")
        return self


class WorkOrderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    number: str
    work_type: Literal["planned", "emergency"]
    description: str
    area_id: UUID
    equipment_id: UUID
    assignee_id: UUID | None
    brigade_id: UUID | None
    responsible_id: UUID | None
    master_id: UUID
    priority: WorkOrderPriority
    due_at: datetime
    status: WorkOrderStatus
    version: int
    assignment_version: int
    queue_position: int | None = None
    created_at: datetime
    is_overdue: bool
    allowed_actions: list[str] = Field(default_factory=list)
    template_snapshot: WorkOrderTemplate | None = None


class WorkOrderEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    work_order_id: UUID
    actor_id: UUID | None
    action: str
    version: int
    assignment_version: int
    reason: str | None
    payload: dict
    occurred_at: datetime


class SubmissionMaterialView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    material_id: UUID
    quantity: Decimal = Field(gt=0)


class SubmissionMaterialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4, allow_inf_nan=False)


class SubmissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(gt=0)
    assignment_version: int = Field(gt=0)
    work_description: str = Field(min_length=1, max_length=10000)
    fault_code_id: UUID
    materials: list[SubmissionMaterialCreate] = Field(default_factory=list, max_length=200)
    no_materials_used: bool = False
    after_photo_ids: list[UUID] = Field(default_factory=list, max_length=20)
    comment: str | None = Field(default=None, max_length=4000)
    template_answers: list[TemplateAnswer] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def evidence_is_consistent(self):
        if bool(self.materials) == self.no_materials_used:
            raise ValueError("Specify materials or explicitly mark none used")
        if len({item.material_id for item in self.materials}) != len(self.materials):
            raise ValueError("Material IDs must be unique")
        if len(set(self.after_photo_ids)) != len(self.after_photo_ids):
            raise ValueError("Photo IDs must be unique")
        return self


class SubmissionView(BaseModel):
    id: UUID
    work_order_id: UUID
    revision: int
    assignment_version: int
    worker_id: UUID
    work_description: str
    fault_code_id: UUID
    no_materials_used: bool
    materials: list[SubmissionMaterialView] = Field(default_factory=list)
    after_photo_ids: list[UUID] = Field(default_factory=list)
    comment: str | None
    submitted_at: datetime
    missing_evidence: list[str] = Field(default_factory=list)
    template_answers: list[TemplateAnswer] = Field(default_factory=list)


class WorkOrderDetail(WorkOrderView):
    before_photo_count: int = Field(default=0, ge=0)
    events: list[WorkOrderEventView] = Field(default_factory=list)
    issuance_photos: list[PhotoView] = Field(default_factory=list)
    submission: SubmissionView | None = None
    ai_review: "AIReviewView | None" = None
    master_decision: "MasterDecisionView | None" = None
    review_status: Literal["pending", "running", "blocked", "completed", "discarded"] | None = None
    allowed_decisions: list[Literal["accept", "rework"]] = Field(default_factory=list)


class MasterDecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["accept", "rework"]
    submission_id: UUID
    expected_version: int = Field(gt=0)
    assignment_version: int = Field(gt=0)
    score: int | None = Field(default=None, ge=1, le=5)
    reason: str | None = Field(default=None, min_length=1, max_length=4000)


class AIReviewView(BaseModel):
    id: UUID
    submission_id: UUID
    verdict: Literal["accepted", "accepted_with_notes", "requires_rework", "human_review"]
    result: "ReviewResult"
    model: str
    prompt_version: str
    created_at: datetime
    is_mock: bool
    source: Literal["provider", "rules", "prepared", "mock", "unknown"]


class MasterDecisionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    submission_id: UUID
    decision: Literal["accept", "rework"]
    score: int | None
    reason: str | None
    master_id: UUID
    decided_at: datetime


WorkOrderDetail.model_rebuild()


class WorkOrderList(BaseModel):
    items: list[WorkOrderView]
    total: int
    offset: int
    limit: int
