from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator


class ReportFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area_id: UUID | None = None
    equipment_id: UUID | None = None
    assignee_id: UUID | None = None
    brigade_id: UUID | None = None


class PeriodQuery(ReportFilters):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_period(self):
        if self.start_at >= self.end_at:
            raise ValueError("start_at must precede end_at")
        return self


class ShiftQuery(ReportFilters):
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    shift_id: UUID | None = None

    @model_validator(mode="after")
    def shift_or_period(self):
        if self.shift_id is not None:
            if self.start_at is not None or self.end_at is not None:
                raise ValueError("Use shift_id or both period boundaries")
        elif self.start_at is None or self.end_at is None or self.start_at >= self.end_at:
            raise ValueError("An ordered, complete period is required")
        return self


class ReportPeriod(BaseModel):
    start_at: AwareDatetime
    end_at: AwareDatetime
    as_of: AwareDatetime
    timezone: str


class ReportCounts(BaseModel):
    issued: int
    performed: int
    closed: int
    overdue: int
    rejected: int


class ReportWorkload(BaseModel):
    active_seconds: float
    pause_seconds: float
    review_seconds: float


class ReportDowntime(BaseModel):
    seconds: float
    has_data: bool


class ShiftReportResponse(BaseModel):
    period: ReportPeriod
    counts: ReportCounts
    workload: ReportWorkload
    downtime: ReportDowntime
    summary: str
    limitations: list[str]


class RatingComponent(BaseModel):
    value: float | None
    sample_size: int
    reason: str | None


class RatingComponents(BaseModel):
    Q: RatingComponent
    T: RatingComponent
    R: RatingComponent
    V: RatingComponent


class RatingRow(BaseModel):
    worker_id: UUID
    display_name: str
    specialty: str
    work_type: Literal["planned", "emergency"]
    closed_count: int
    score: float | None
    components: RatingComponents


class RatingResponse(BaseModel):
    period: ReportPeriod
    formula_version: Literal["c6-v1-available"] = "c6-v1-available"
    items: list[RatingRow]
    limitations: list[str]


class Anomaly(BaseModel):
    id: str
    type: Literal["repeat_fault", "after_planned", "material_overuse"]
    title: str
    description: str
    equipment_id: UUID
    metrics: dict[str, float]
    evidence_order_ids: list[UUID]
    limitations: list[str]


class AnomaliesResponse(BaseModel):
    period: ReportPeriod
    items: list[Anomaly]
    limitations: list[str]
