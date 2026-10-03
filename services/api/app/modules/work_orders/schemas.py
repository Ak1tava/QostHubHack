from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    priority: Literal["emergency", "high", "normal", "planned"]
    due_at: datetime
    status: WorkOrderStatus
    version: int
    assignment_version: int
    created_at: datetime
    is_overdue: bool
    allowed_actions: list[str] = Field(default_factory=list)
