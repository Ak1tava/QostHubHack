"""Batched, area-scoped history; aggregates never join one-to-many rows."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, or_, select

from app.core.config import settings
from app.core.security import AuthError, allowed_area_ids
from app.modules.auth.models import Shift, User, UserArea
from app.modules.catalog.models import Equipment, MaterialNorm
from app.modules.work_orders.models import (
    DowntimeInterval, MasterDecision, MaterialUsage, Submission, WorkOrder,
    WorkOrderEvent, WorkOrderInterval,
)
from app.modules.analytics.schemas import ReportPeriod, ShiftReportResponse


def merged_seconds(spans, start, end):
    clipped = sorted((max(a, start), min(b or end, end)) for a, b in spans
                     if a < end and (b is None or b > start))
    seconds = 0.0
    finish = start
    for begin, stop in clipped:
        begin = max(begin, finish)
        if stop > begin:
            seconds += (stop - begin).total_seconds()
            finish = stop
    return seconds


def group_by(rows, name):
    grouped = defaultdict(list)
    for row in rows:
        grouped[getattr(row, name)].append(row)
    return grouped


@dataclass
class History:
    period: ReportPeriod
    actor: User
    filters: object
    orders: dict
    events: dict
    submissions: dict
    decisions: dict
    intervals: dict
    downtime: list
    users: dict
    materials: dict
    norms: dict
    limitations: list

    @property
    def stop(self):
        return min(self.period.end_at, self.period.as_of)

    def in_period(self, at):
        return self.period.start_at <= at < self.stop

    def initial(self, order):
        events = self.events.get(order.id, [])
        if events:
            first = events[0].payload
            return dict(first.get("before") or first.get("after") or {})
        return dict(status=order.status, due_at=order.due_at.isoformat(),
                    assignee_id=str(order.assignee_id) if order.assignee_id else None,
                    responsible_id=str(order.responsible_id) if order.responsible_id else None,
                    brigade_id=str(order.brigade_id) if order.brigade_id else None)

    def state_at(self, order, at):
        state = self.initial(order)
        for event in self.events.get(order.id, []):
            if event.occurred_at > at:
                break
            state.update(event.payload.get("after", {}))
        return state

    def segments(self, order):
        state, begin = self.initial(order), order.created_at
        for event in self.events.get(order.id, []):
            if event.occurred_at > begin:
                yield begin, event.occurred_at, state
            state = {**state, **event.payload.get("after", {})}
            begin = max(begin, event.occurred_at)
        if begin < self.period.as_of:
            yield begin, self.period.as_of, state

    def matches(self, state, *, worker_id=None):
        assigned = worker_id or state.get("assignee_id") or state.get("responsible_id")
        if self.actor.role == "worker" and str(assigned) != str(self.actor.id):
            return False
        if self.filters.assignee_id and str(assigned) != str(self.filters.assignee_id):
            return False
        if self.filters.brigade_id and str(state.get("brigade_id")) != str(self.filters.brigade_id):
            return False
        return True

    def accepted(self):
        """Only the final master decision; old revisions never enter quality scores."""
        for order_id, decisions in self.decisions.items():
            if not decisions:
                continue
            decision = decisions[-1]
            if decision.decision != "accept":
                continue
            order = self.orders[order_id]
            sub = next((s for s in self.submissions.get(order_id, []) if s.id == decision.submission_id), None)
            if sub and self.matches(self.state_at(order, sub.submitted_at), worker_id=sub.worker_id):
                yield order, sub, decision


def load_history(db, actor, filters, as_of, *, insights=False):
    if insights and actor.role == "worker":
        raise AuthError(403, "forbidden", "Закономерности оборудования доступны руководителям")
    if actor.role == "worker" and filters.assignee_id not in (None, actor.id):
        raise AuthError(404, "not_found", "Объект не найден")
    if actor.role == "worker" and filters.brigade_id not in (None, actor.brigade_id):
        former_assignment = db.scalar(select(WorkOrderEvent.id).where(
            WorkOrderEvent.occurred_at <= as_of,
            WorkOrderEvent.payload["after"]["brigade_id"].as_string() == str(filters.brigade_id),
            or_(WorkOrderEvent.payload["after"]["assignee_id"].as_string() == str(actor.id),
                WorkOrderEvent.payload["after"]["responsible_id"].as_string() == str(actor.id))).limit(1))
        if former_assignment is None:
            raise AuthError(403, "forbidden", "Доступны только собственные показатели")
    areas = allowed_area_ids(db, actor)
    if filters.area_id is not None and filters.area_id not in areas:
        raise AuthError(404, "not_found", "Объект не найден")
    if filters.equipment_id is not None:
        equipment = db.get(Equipment, filters.equipment_id)
        if not equipment or equipment.area_id not in areas:
            raise AuthError(404, "not_found", "Объект не найден")
    if getattr(filters, "shift_id", None):
        shift = db.get(Shift, filters.shift_id)
        if shift is None:
            raise AuthError(404, "not_found", "Смена не найдена")
        start, end = shift.start_at, shift.end_at
    else:
        start, end = filters.start_at, filters.end_at
    period = ReportPeriod(start_at=start, end_at=end, as_of=as_of, timezone=settings.app_timezone)
    query = select(WorkOrder).where(WorkOrder.created_at < min(end, as_of))
    if actor.role == "worker":
        own_submission = exists(select(Submission.id).where(
            Submission.work_order_id == WorkOrder.id, Submission.worker_id == actor.id,
            Submission.submitted_at <= as_of))
        own_event = exists(select(WorkOrderEvent.id).where(
            WorkOrderEvent.work_order_id == WorkOrder.id, WorkOrderEvent.occurred_at <= as_of,
            or_(WorkOrderEvent.payload["after"]["assignee_id"].as_string() == str(actor.id),
                WorkOrderEvent.payload["after"]["responsible_id"].as_string() == str(actor.id))))
        query = query.where(or_(WorkOrder.assignee_id == actor.id,
                               WorkOrder.responsible_id == actor.id, own_submission, own_event))
    else:
        query = query.where(WorkOrder.area_id.in_(areas))
    for field in ("area_id", "equipment_id"):
        value = getattr(filters, field)
        if value is not None:
            query = query.where(getattr(WorkOrder, field) == value)
    orders = {o.id: o for o in db.scalars(query)}
    ids = list(orders)
    events = group_by(db.scalars(select(WorkOrderEvent).where(
        WorkOrderEvent.work_order_id.in_(ids), WorkOrderEvent.occurred_at <= as_of)
        .order_by(WorkOrderEvent.occurred_at, WorkOrderEvent.version)), "work_order_id")
    submissions = group_by(db.scalars(select(Submission).where(
        Submission.work_order_id.in_(ids), Submission.submitted_at <= as_of)
        .order_by(Submission.revision)), "work_order_id")
    decisions = group_by(db.scalars(select(MasterDecision).where(
        MasterDecision.work_order_id.in_(ids), MasterDecision.decided_at <= as_of)
        .order_by(MasterDecision.decided_at, MasterDecision.id)), "work_order_id")
    intervals = group_by(db.scalars(select(WorkOrderInterval).where(
        WorkOrderInterval.work_order_id.in_(ids), WorkOrderInterval.start_at < min(end, as_of),
        or_(WorkOrderInterval.end_at.is_(None), WorkOrderInterval.end_at > start))), "work_order_id")
    permitted_equipment = select(Equipment.id).where(Equipment.area_id.in_(areas))
    if filters.area_id:
        permitted_equipment = permitted_equipment.where(Equipment.area_id == filters.area_id)
    if filters.equipment_id:
        permitted_equipment = permitted_equipment.where(Equipment.id == filters.equipment_id)
    downtime_query = select(DowntimeInterval).where(
        DowntimeInterval.start_at < min(end, as_of),
        or_(DowntimeInterval.end_at.is_(None), DowntimeInterval.end_at > start))
    if actor.role == "worker" or filters.assignee_id or filters.brigade_id:
        downtime_query = downtime_query.where(DowntimeInterval.work_order_id.in_(ids))
    else:
        downtime_query = downtime_query.where(DowntimeInterval.equipment_id.in_(permitted_equipment))
    downtime = list(db.scalars(downtime_query))
    worker_ids = {s.worker_id for rows in submissions.values() for s in rows}
    users_query = select(User).where(User.role == "worker")
    if actor.role == "worker":
        users_query = users_query.where(User.id == actor.id)
    else:
        users_query = users_query.where(or_(User.id.in_(worker_ids), User.id.in_(
            select(UserArea.user_id).where(UserArea.area_id.in_(areas)))))
    if filters.assignee_id:
        users_query = users_query.where(User.id == filters.assignee_id)
    if filters.brigade_id:
        historical = {s.worker_id for order_id, rows in submissions.items() for s in rows
                      if any(str(e.payload.get("after", {}).get("brigade_id")) == str(filters.brigade_id)
                             for e in events.get(order_id, []))}
        users_query = users_query.where(or_(User.brigade_id == filters.brigade_id, User.id.in_(historical)))
    users = {u.id: u for u in db.scalars(users_query)}
    if filters.assignee_id and filters.assignee_id not in users:
        raise AuthError(404, "not_found", "Объект не найден")
    if filters.brigade_id and not users:
        raise AuthError(404, "not_found", "Объект не найден")
    sub_ids = [s.id for rows in submissions.values() for s in rows]
    materials, norms = {}, {}
    if insights:
        materials = group_by(db.scalars(select(MaterialUsage).where(MaterialUsage.submission_id.in_(sub_ids))), "submission_id")
        norms = {(n.equipment_id, n.work_code_id, n.material_id): n.quantity for n in db.scalars(
            select(MaterialNorm).where(MaterialNorm.equipment_id.in_({o.equipment_id for o in orders.values()})))}
    limitations = []
    if any(not events.get(o.id) for o in orders.values()):
        limitations.append("У части нарядов отсутствует журнал: прошлые сроки и назначения восстановлены неполно.")
    return History(period, actor, filters, orders, events, submissions, decisions, intervals,
                   downtime, users, materials, norms, limitations)


def shift_report(data):
    counts = dict(issued=0, performed=0, closed=0, overdue=0, rejected=0)
    workload = dict(active_seconds=0.0, pause_seconds=0.0, review_seconds=0.0)
    start, stop = data.period.start_at, data.stop
    closed = {o.id for o, sub, decision in data.accepted() if data.in_period(decision.decided_at)}
    counts["closed"] = len(closed)
    for order in data.orders.values():
        if data.in_period(order.created_at) and data.matches(data.state_at(order, order.created_at)):
            counts["issued"] += 1
        if any(data.in_period(s.submitted_at) and data.matches(data.state_at(order, s.submitted_at), worker_id=s.worker_id)
               for s in data.submissions.get(order.id, [])):
            counts["performed"] += 1
        if any(e.action == "reject" and data.in_period(e.occurred_at) and data.matches(e.payload.get("after", {}))
               for e in data.events.get(order.id, [])):
            counts["rejected"] += 1
        overdue = False
        segments = list(data.segments(order))
        for begin, end, state in segments:
            a, b = max(begin, start), min(end, stop)
            if a >= b or not data.matches(state):
                continue
            due = state.get("due_at")
            due = datetime.fromisoformat(due) if isinstance(due, str) else due
            if due and due < b and state.get("status") not in {"SUBMITTED", "AI_REVIEW", "CLOSED", "CANCELLED"}:
                overdue = True
            for interval in data.intervals.get(order.id, []):
                workload[interval.kind + "_seconds"] += merged_seconds([(interval.start_at, interval.end_at)], a, b)
        counts["overdue"] += int(overdue)
    spans = defaultdict(list)
    for interval in data.downtime:
        if data.actor.role != "worker" and not (data.filters.assignee_id or data.filters.brigade_id):
            spans[interval.equipment_id].append((interval.start_at, interval.end_at))
            continue
        order = data.orders.get(interval.work_order_id)
        if order is not None:
            for a, b, state in data.segments(order):
                if data.matches(state):
                    spans[interval.equipment_id].append((max(interval.start_at, a), min(interval.end_at or stop, b)))
    seconds = sum(merged_seconds(v, start, stop) for v in spans.values())
    has_data = any(a < stop and (b is None or b > start) and (b is None or b > a)
                   for v in spans.values() for a, b in v)
    summary = (f"Выдано {counts['issued']}, исполнено {counts['performed']}, закрыто {counts['closed']}. "
               f"Просроченных за период: {counts['overdue']}; отклонённых: {counts['rejected']}. "
               + (f"Простой оборудования: {seconds / 3600:.2f} ч." if has_data else "Нет данных о простое оборудования."))
    limitations = list(data.limitations)
    if not has_data:
        limitations.append("Нет зарегистрированных интервалов простоя за период; это не подтверждает отсутствие простоя.")
    limitations.append("Уважительность отказов и внешние задержки не структурированы; скрытые штрафы не применяются.")
    return ShiftReportResponse(period=data.period, counts=counts, workload=workload,
                               downtime=dict(seconds=seconds, has_data=has_data), summary=summary, limitations=limitations)
