from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.auth.schemas import UserView


class NamedView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str


class EquipmentView(NamedView):
    area_id: UUID


class WorkCodeView(NamedView):
    code: str


class MaterialView(NamedView):
    unit: str


class NormView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    equipment_id: UUID
    work_code_id: UUID
    material_id: UUID
    quantity: Decimal


class CatalogResponse(BaseModel):
    items: list[
        EquipmentView | WorkCodeView | MaterialView | UserView | NormView | NamedView
    ]
    total: int
    offset: int
    limit: int


class ShiftMemberView(BaseModel):
    user: UserView
    start_at: datetime | None
    end_at: datetime | None
    availability: Literal["free", "busy", "queued", "off_shift"]
    queue_count: int
    active_work_order_id: UUID | None


class ShiftResponse(BaseModel):
    items: list[ShiftMemberView]
    as_of: datetime
