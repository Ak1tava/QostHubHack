"""C6 scores from final human acceptance, with explicit unavailable components."""
from collections import defaultdict
from datetime import datetime, timedelta

from app.modules.analytics.schemas import RatingResponse, RatingRow

WEIGHTS = {"Q": .50, "T": .25, "R": .15, "V": .10}


def component(value=None, sample_size=0, reason=None):
    return dict(value=value, sample_size=sample_size, reason=reason)


def build_rating(data):
    grouped = defaultdict(list)
    for order, submission, decision in data.accepted():
        if data.in_period(decision.decided_at):
            grouped[(submission.worker_id, order.work_type)].append((order, submission, decision))
    items = []
    for user in data.users.values():
        for kind in ("planned", "emergency"):
            rows = grouped[(user.id, kind)]
            scores = [d.score / 5 for o, s, d in rows if d.score is not None]
            timely = []
            for order, sub, decision in rows:
                due = data.state_at(order, sub.submitted_at).get("due_at")
                due = datetime.fromisoformat(due) if isinstance(due, str) else due
                if due:
                    timely.append(int(sub.submitted_at <= due))
            immature = sum(d.decided_at + timedelta(days=7) > data.period.as_of for o, s, d in rows)
            components = dict(
                Q=component(sum(scores) / len(scores), len(scores)) if scores else component(reason="Нет окончательных оценок мастера."),
                T=component(sum(timely) / len(timely), len(timely)) if timely else component(reason="Нет принятых сдач с известным сроком."),
                R=component(reason=(f"Окно наблюдения 7 дней не завершено для {immature} работ. " if immature else "")
                            + "Нет структурированного подтверждения возврата или повтора по причине качества."),
                V=component(reason="Нет нормативных часов работ и исторических доступных часов смен."),
            )
            available = [(WEIGHTS[k], c["value"]) for k, c in components.items() if c["value"] is not None]
            score = 100 * sum(w * value for w, value in available) / sum(w for w, value in available) if available and rows else None
            items.append(RatingRow(worker_id=user.id, display_name=user.display_name,
                                   specialty=user.specialty or "Не указана", work_type=kind,
                                   closed_count=len(rows), score=score, components=components))
    items.sort(key=lambda row: (row.specialty, row.work_type, row.score is None,
                                -(row.score or 0), row.display_name, str(row.worker_id)))
    return RatingResponse(period=data.period, items=items,
                          limitations=[*data.limitations, "Доступные веса нормированы: Q 0.50, T 0.25; R/V неизвестны.",
                                       "T использует исторический срок: подтверждённые внешние задержки не структурированы.",
                                       "Оценки ИИ и свободный текст причин не подтверждают качество или вину исполнителя."])
