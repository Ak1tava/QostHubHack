"""Equipment cards reuse catalog scope and work-order visibility."""
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import AuthError, allowed_area_ids, get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import ErrorResponse
from app.modules.catalog.models import Area, Equipment
from app.modules.catalog.schemas import EquipmentView, NamedView
from app.modules.work_orders.models import WorkOrder
from app.modules.work_orders.queries import visible_orders
from app.modules.work_orders.schemas import WorkOrderStatus


class EquipmentOrderView(BaseModel):
    id: UUID
    number: str
    created_at: datetime
    description: str = Field(max_length=240)
    status: WorkOrderStatus
    detail_url: str


class EquipmentDetail(EquipmentView):
    area: NamedView
    public_url: str | None
    timezone: str
    recent_work_orders: list[EquipmentOrderView] = Field(max_length=10)


router = APIRouter(prefix='/equipment', tags=['equipment'])


def equipment_public_url(equipment_id: UUID) -> str | None:
    # A local HTTP dev origin must never become a printable, misleading QR.
    base = settings.public_base_url.rstrip('/')
    try:
        parsed = urlsplit(base)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            return None
        _ = parsed.port
    except ValueError:
        return None
    return f'{base}/equipment/{equipment_id}'


@router.get('/{equipment_id}', response_model=EquipmentDetail,
            responses={401: {'model': ErrorResponse}, 404: {'model': ErrorResponse}})
def equipment_detail(equipment_id: UUID, response: Response,
                     actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    equipment = db.get(Equipment, equipment_id)
    if equipment is None or equipment.area_id not in allowed_area_ids(db, actor):
        raise AuthError(404, 'not_found', 'Оборудование не найдено')
    # SQL applies actor/brigade/area visibility before ordering and LIMIT.
    orders = db.scalars(visible_orders(db, actor).where(WorkOrder.equipment_id == equipment_id)
                        .order_by(WorkOrder.created_at.desc(), WorkOrder.id).limit(10))
    response.headers['Cache-Control'] = 'no-store'
    return EquipmentDetail(
        id=equipment.id, name=equipment.name, area_id=equipment.area_id,
        area=NamedView.model_validate(db.get(Area, equipment.area_id)),
        public_url=equipment_public_url(equipment.id), timezone=settings.app_timezone,
        recent_work_orders=[EquipmentOrderView(
            id=o.id, number=o.number, created_at=o.created_at, description=o.description[:240],
            status=o.status, detail_url=f'/orders/{o.id}',
        ) for o in orders],
    )
