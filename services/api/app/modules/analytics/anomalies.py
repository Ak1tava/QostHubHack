"""Evidence-backed signals computed from permitted history, without an LLM."""
from collections import defaultdict
from datetime import timedelta

from app.modules.analytics.schemas import Anomaly, AnomaliesResponse

LIMITATION = "Совпадение во времени — сигнал для проверки причины, а не доказательство вины исполнителя."


def find_anomalies(data):
    accepted = sorted(data.accepted(), key=lambda row: (row[0].created_at, str(row[0].id)))
    by_fault, emergencies = defaultdict(list), defaultdict(list)
    for order in data.orders.values():
        if order.work_type == "emergency" and data.matches(data.state_at(order, order.created_at)):
            emergencies[order.equipment_id].append(order)
    items = []
    for order, sub, decision in accepted:
        key = order.equipment_id, sub.work_code_id
        earlier = by_fault[key]
        # The final code defines the fault; the occurrence is the order's issuance.
        candidates = [o for o, s, d in earlier if timedelta(0) <= order.created_at - o.created_at <= timedelta(days=7)]
        if candidates and data.in_period(order.created_at):
            previous = max(candidates, key=lambda o: (o.created_at, str(o.id)))
            items.append(Anomaly(id=f"repeat_fault:{previous.id}:{order.id}", type="repeat_fault",
                                 title="Повтор одного шифра на оборудовании",
                                 description="Два принятых ремонта одного оборудования с одинаковым окончательным шифром за 7 дней.",
                                 equipment_id=order.equipment_id,
                                 metrics=dict(hours_between=(order.created_at - previous.created_at).total_seconds() / 3600,
                                              order_count=2),
                                 evidence_order_ids=[previous.id, order.id], limitations=[LIMITATION]))
        earlier.append((order, sub, decision))
        if order.work_type == "planned":
            candidates = [emergency for emergency in emergencies[order.equipment_id]
                          if timedelta(0) <= emergency.created_at - decision.decided_at <= timedelta(hours=48)]
            if candidates:
                emergency = min(candidates, key=lambda emergency: (emergency.created_at, str(emergency.id)))
                if data.in_period(emergency.created_at):
                    items.append(Anomaly(id=f"after_planned:{order.id}:{emergency.id}", type="after_planned",
                                         title="Аварийный ремонт вскоре после ППР",
                                         description="Ближайшая аварийная работа началась в пределах 48 часов после приёмки плановой.",
                                         equipment_id=order.equipment_id,
                                         metrics=dict(hours_after_acceptance=(emergency.created_at - decision.decided_at).total_seconds() / 3600),
                                         evidence_order_ids=[order.id, emergency.id], limitations=[LIMITATION]))
        if data.in_period(decision.decided_at):
            for usage in data.materials.get(sub.id, []):
                norm = data.norms.get((order.equipment_id, sub.work_code_id, usage.material_id))
                if norm is not None and usage.quantity > norm:
                    items.append(Anomaly(id=f"material_overuse:{order.id}:{usage.material_id}", type="material_overuse",
                                         title="Расход материала выше сопоставимой нормы",
                                         description="Расход окончательного принятого отчёта превышает норму оборудования, шифра и материала.",
                                         equipment_id=order.equipment_id,
                                         metrics=dict(actual=float(usage.quantity), norm=float(norm), ratio=float(usage.quantity / norm)),
                                         evidence_order_ids=[order.id], limitations=[LIMITATION]))
    items.sort(key=lambda a: (a.type, str(a.equipment_id), a.id))
    return AnomaliesResponse(period=data.period, items=items,
                             limitations=[*data.limitations, "Повтор шифра и расход анализируются только по окончательно принятым отчётам.",
                                          "Без сопоставимой нормы превышение расхода не определяется.", LIMITATION])
