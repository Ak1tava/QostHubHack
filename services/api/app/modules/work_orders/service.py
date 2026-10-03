"""Atomic user commands. A successful response is committed before HTTP returns."""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.core.security import AuthError, can_access_order, require_order_creation
from app.modules.auth.models import User, UserArea
from app.modules.catalog.models import Equipment
from app.modules.work_orders import events, queries
from app.modules.work_orders.models import IdempotencyRecord, ORDER_NUMBER_SEQUENCE, WorkOrder
from app.modules.work_orders.schemas import WorkOrderView
from app.modules.work_orders.state_machine import require_action_role, transition


def lock_order(db, order_id):
    order = db.scalar(select(WorkOrder).where(WorkOrder.id == order_id)
                      .with_for_update(key_share=True).execution_options(populate_existing=True))
    if order is None:
        raise AuthError(404, "not_found", "Объект не найден")
    return order


def lock_workers(db, *ids):
    ids = sorted({item for item in ids if item is not None}, key=str)
    if ids:
        list(db.scalars(select(User).where(User.id.in_(ids)).order_by(User.id)
                        .with_for_update(key_share=True).execution_options(populate_existing=True)))


def authorize(db, order, actor, action):
    if not can_access_order(db, actor, order):
        raise AuthError(404, "not_found", "Объект не найден")
    require_action_role(action, actor.role)
    if actor.role == "worker" and not queries.is_responsible(order, actor):
        raise AuthError(403, "forbidden", "Действие доступно только ответственному")


def check_version(order, expected):
    if order.version != expected:
        raise AuthError(409, "version_conflict", "Наряд изменён, обновите карточку")


def check_available(db, order):
    active = db.scalar(select(WorkOrder.id).where(
        func.coalesce(WorkOrder.assignee_id, WorkOrder.responsible_id) == queries.responsible_id(order),
        WorkOrder.status == "IN_PROGRESS", WorkOrder.id != order.id,
    ).limit(1))
    if active is not None:
        raise AuthError(409, "worker_busy", "У исполнителя уже есть активный наряд")


def validate_assignment(db, area_id, command):
    worker_id = command.assignee_id or command.responsible_id
    worker = db.get(User, worker_id)
    area = db.get(UserArea, (worker_id, area_id))
    if (worker is None or not worker.is_active or worker.role != "worker" or area is None
            or (command.brigade_id and worker.brigade_id != command.brigade_id)):
        raise AuthError(422, "invalid_assignment", "Недопустимое назначение исполнителя")


class WorkOrderService:
    def __init__(self, db):
        self.db = db

    def _reserve(self, actor, path, command, key):
        if not key or not key.strip() or len(key) > 128:
            raise AuthError(422, "validation_error", "Требуется Idempotency-Key до 128 символов")
        fingerprint = hashlib.sha256(json.dumps(
            {"path": path, "body": command.model_dump(mode="json")},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()).hexdigest()
        inserted = self.db.scalar(insert(IdempotencyRecord).values(
            actor_id=actor.id, key=key, fingerprint=fingerprint,
        ).on_conflict_do_nothing(index_elements=["actor_id", "key"]).returning(IdempotencyRecord.actor_id))
        record = self.db.get(IdempotencyRecord, (actor.id, key), populate_existing=True)
        if record.fingerprint != fingerprint:
            raise AuthError(409, "idempotency_conflict", "Ключ уже использован для другого запроса")
        return record, inserted is None

    def _finish(self, record, order, actor, status):
        self.db.flush()
        result = queries.view(self.db, order, actor)
        record.work_order_id = order.id
        record.response_status = status
        record.response_body = result.model_dump(mode="json")
        self.db.commit()
        return result

    def _replay(self, record):
        result = WorkOrderView.model_validate(record.response_body)
        self.db.commit()
        return result

    def create(self, actor, command, key):
        try:
            require_order_creation(self.db, actor, command.area_id)
            record, replay = self._reserve(actor, "POST /work-orders", command, key)
            if replay:
                order = lock_order(self.db, record.work_order_id)
                if not can_access_order(self.db, actor, order):
                    raise AuthError(404, "not_found", "Объект не найден")
                return self._replay(record)
            lock_workers(self.db, command.assignee_id or command.responsible_id)
            validate_assignment(self.db, command.area_id, command)
            equipment = self.db.get(Equipment, command.equipment_id)
            if equipment is None or equipment.area_id != command.area_id:
                raise AuthError(422, "invalid_equipment", "Оборудование не относится к участку")
            number = self.db.scalar(ORDER_NUMBER_SEQUENCE.next_value())
            now = datetime.now(timezone.utc)
            order = WorkOrder(**command.model_dump(), number=f"WO-{number:06d}",
                              master_id=actor.id, status="ISSUED", version=1,
                              assignment_version=1, created_at=now)
            self.db.add(order)
            self.db.flush()
            events.record_transition(self.db, order, action="create", actor_id=actor.id,
                                     reason=None, before={}, now=now)
            return self._finish(record, order, actor, 201)
        except Exception:
            self.db.rollback()
            raise

    def apply_action(self, order_id, actor, command, key):
        try:
            record, replay = self._reserve(actor, f"POST /work-orders/{order_id}/actions", command, key)
            order = lock_order(self.db, order_id)
            lock_workers(self.db, queries.responsible_id(order),
                         command.assignee_id or command.responsible_id)
            authorize(self.db, order, actor, command.action)
            if replay:
                return self._replay(record)
            check_version(order, command.expected_version)
            target = transition(order.status, command.action, actor.role, command.reason)
            if command.action in {"start", "resume", "restart"}:
                check_available(self.db, order)
            before = events.snapshot(order)
            if command.action == "reassign":
                validate_assignment(self.db, order.area_id, command)
                order.assignee_id = command.assignee_id
                order.brigade_id = command.brigade_id
                order.responsible_id = command.responsible_id
                order.assignment_version += 1
            if command.action == "reprioritize":
                order.priority = command.priority
            if command.action == "queue":
                last = self.db.scalar(select(func.max(WorkOrder.queue_position)).where(
                    func.coalesce(WorkOrder.assignee_id, WorkOrder.responsible_id) == queries.responsible_id(order),
                    WorkOrder.status == "QUEUED",
                ))
                order.queue_position = (last or 0) + 1
            elif target != "QUEUED":
                order.queue_position = None
            order.status = target
            order.version += 1
            events.record_transition(self.db, order, action=command.action, actor_id=actor.id,
                                     reason=command.reason, before=before, now=datetime.now(timezone.utc))
            return self._finish(record, order, actor, 200)
        except IntegrityError as exc:
            self.db.rollback()
            # Only the documented concurrency constraint is a user-level conflict.
            if getattr(getattr(exc.orig, "diag", None), "constraint_name", "") == "uq_work_orders_active_responsible":
                raise AuthError(409, "worker_busy", "У исполнителя уже есть активный наряд") from exc
            raise
        except Exception:
            self.db.rollback()
            raise
