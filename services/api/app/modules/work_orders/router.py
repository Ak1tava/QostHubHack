from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import ErrorResponse
from app.modules.work_orders import queries
from app.modules.work_orders.schemas import (
    ActionCommand, WorkOrderCreate, WorkOrderDetail, WorkOrderList,
    WorkOrderPriority, WorkOrderStatus, WorkOrderView, SubmissionCreate, SubmissionView,
    MasterDecisionCommand, WorkOrderTemplateList,
)
from app.modules.work_orders.service import WorkOrderService
from app.modules.work_orders.submissions import SubmissionService

router = APIRouter(prefix="/work-orders", tags=["work-orders"])
ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)}
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


@router.post("", response_model=WorkOrderView, status_code=201, responses=ERRORS)
def create_order(command: WorkOrderCreate, response: Response, key: Key,
                 actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return WorkOrderService(db).create(actor, command, key)


@router.get("", response_model=WorkOrderList, responses=ERRORS)
def list_orders(response: Response, area_id: UUID | None = None, equipment_id: UUID | None = None,
                assignee_id: UUID | None = None, priority: WorkOrderPriority | None = None,
                status: WorkOrderStatus | None = None, offset: int = Query(0, ge=0),
                limit: int = Query(50, ge=1, le=200), actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return queries.list_orders(db, actor, area_id=area_id, equipment_id=equipment_id,
                               assignee_id=assignee_id, priority=priority, status=status,
                               offset=offset, limit=limit)


@router.get("/templates", response_model=WorkOrderTemplateList, responses=ERRORS)
def list_templates(response: Response, actor: User = Depends(get_current_user)):
    from app.modules.work_orders.templates import list_templates
    response.headers["Cache-Control"] = "no-store"
    return WorkOrderTemplateList(items=list_templates())


@router.get("/{order_id}", response_model=WorkOrderDetail, responses=ERRORS)
def get_order(order_id: UUID, response: Response, actor: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return queries.get_order(db, order_id, actor)


@router.post("/{order_id}/actions", response_model=WorkOrderView, responses=ERRORS)
def apply_action(order_id: UUID, command: ActionCommand, response: Response, key: Key,
                  actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return WorkOrderService(db).apply_action(order_id, actor, command, key)


@router.post("/{order_id}/submissions", response_model=SubmissionView, status_code=201, responses=ERRORS)
def submit_order(order_id: UUID, command: SubmissionCreate, response: Response, key: Key,
                 actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return SubmissionService(db).submit_order(order_id, actor, command, key)


@router.post("/{order_id}/decision", response_model=WorkOrderView, responses=ERRORS)
def decide_order(order_id: UUID, command: MasterDecisionCommand, response: Response, key: Key,
                 actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.modules.ai_review.decisions import MasterDecisionService
    response.headers["Cache-Control"] = "no-store"
    return MasterDecisionService(db).apply_master_decision(order_id, actor, command, key)
