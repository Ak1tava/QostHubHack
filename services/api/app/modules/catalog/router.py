from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import settings
from app.core.security import (
    AuthError,
    allowed_area_ids,
    can_access_order,
    get_current_user,
)
from app.modules.auth.models import Brigade, Shift, User, UserArea
from app.modules.auth.schemas import ErrorResponse, UserView
from app.modules.catalog.models import Area, Equipment, Material, MaterialNorm, WorkCode
from app.modules.catalog.schemas import (
    CatalogResponse,
    EquipmentView,
    MaterialView,
    NamedView,
    NormView,
    ShiftMemberView,
    ShiftResponse,
    WorkCodeView,
)
from app.modules.work_orders.models import WorkOrder

router = APIRouter(prefix="/catalog", tags=["catalog"])
shift_router = APIRouter(prefix="/shift", tags=["shift"])


def visible_users(db: Session, actor: User):
    query = select(User).where(User.is_active.is_(True))
    if actor.role == "worker":
        return query.where(User.id == actor.id)
    return query.where(
        User.id.in_(
            select(UserArea.user_id).where(
                UserArea.area_id.in_(allowed_area_ids(db, actor))
            )
        )
    )


@router.get(
    "/{kind}",
    response_model=CatalogResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def catalog(
    kind: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    areas = allowed_area_ids(db, actor)
    options = {
        "areas": (Area, NamedView, select(Area).where(Area.id.in_(areas))),
        "equipment": (
            Equipment,
            EquipmentView,
            select(Equipment).where(Equipment.area_id.in_(areas)),
        ),
        "materials": (Material, MaterialView, select(Material)),
        "work-codes": (WorkCode, WorkCodeView, select(WorkCode)),
        "users": (User, UserView, visible_users(db, actor)),
        "brigades": (
            Brigade,
            NamedView,
            select(Brigade).where(
                Brigade.id.in_(
                    visible_users(db, actor).with_only_columns(User.brigade_id)
                )
            ),
        ),
        "norms": (
            MaterialNorm,
            NormView,
            select(MaterialNorm).where(
                MaterialNorm.equipment_id.in_(
                    select(Equipment.id).where(Equipment.area_id.in_(areas))
                )
            ),
        ),
    }
    if kind not in options:
        raise AuthError(404, "not_found", "Справочник не найден")
    model, schema, query = options[kind]
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(model.id).offset(offset).limit(limit))
    return CatalogResponse(
        items=[schema.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@shift_router.get(
    "", response_model=ShiftResponse, responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}
)
def shift(area_id: UUID | None = None, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    query = visible_users(db, actor)
    if area_id is not None:
        if area_id not in allowed_area_ids(db, actor):
            raise AuthError(404, "not_found", "Участок не найден")
        query = query.where(User.id.in_(select(UserArea.user_id).where(UserArea.area_id == area_id)))
    users = list(db.scalars(query.order_by(User.id)))
    shifts = {
        s.id: s
        for s in db.scalars(
            select(Shift).where(Shift.id.in_([u.shift_id for u in users if u.shift_id]))
        )
    }
    user_ids = [u.id for u in users]
    # Count the full workload of visible users; disclose order IDs separately.
    orders = list(
        db.scalars(
            select(WorkOrder).where(
                or_(
                    WorkOrder.assignee_id.in_(user_ids),
                    WorkOrder.responsible_id.in_(user_ids),
                ),
                WorkOrder.status.in_(["IN_PROGRESS", "QUEUED"]),
            )
        )
    )
    items = []
    for user in users:
        current = shifts.get(user.shift_id)
        assigned = [o for o in orders if (o.assignee_id or o.responsible_id) == user.id]
        active = next((o for o in assigned if o.status == "IN_PROGRESS"), None)
        queue_count = sum(o.status == "QUEUED" for o in assigned)
        on_shift = current is not None and current.start_at <= now < current.end_at
        availability = (
            "off_shift"
            if not on_shift
            else ("busy" if active else "queued" if queue_count else "free")
        )
        items.append(
            ShiftMemberView(
                user=UserView.model_validate(user),
                start_at=current.start_at if current else None,
                end_at=current.end_at if current else None,
                availability=availability,
                queue_count=queue_count,
                active_work_order_id=active.id
                if active and can_access_order(db, actor, active)
                else None,
            )
        )
    return ShiftResponse(items=items, as_of=now, timezone=settings.app_timezone)
