"""Bounded plain-text notification content; input text never becomes markup."""

import unicodedata
from zoneinfo import ZoneInfo

KIND_LABELS = {
    "new": "Новый наряд",
    "reminder": "До срока 30 минут",
    "unaccepted": "Наряд не принят",
    "overdue": "Срок истёк",
    "emergency_queued": "Аварийный наряд в очереди",
}
PRIORITY_LABELS = {
    "emergency": "Аварийный", "high": "Высокий",
    "normal": "Обычный", "planned": "Плановый",
}
ACTIONS = {
    "new": "Примите наряд в PWA.",
    "reminder": "Обновите ход работ в PWA до истечения срока.",
    "unaccepted": "Проверьте назначение и свяжитесь с исполнителем в PWA.",
    "overdue": "Обновите ход работ в PWA и согласуйте дальнейшие действия с мастером.",
    "emergency_queued": "Проверьте очередь и назначение аварийного наряда в PWA.",
}


def safe_text(value, limit=160, *, empty="Не указано"):
    # Each field is a single bounded line; bidi/control characters cannot spoof it.
    clean = " ".join("".join(
        " " if character.isspace() else character
        for character in (value or "")
        if character.isspace() or not unicodedata.category(character).startswith("C")
    ).split())
    if not clean:
        return empty
    encoded = clean.encode("utf-16-le")
    if len(encoded) <= limit * 2:
        return clean
    return encoded[: (limit - 1) * 2].decode("utf-16-le", errors="ignore") + "…"


def format_notification(*, kind, order, equipment, area, responsible, brigade,
                        now, timezone, comment=None):
    due = order.due_at.astimezone(ZoneInfo(timezone))
    lines = [
        f"{KIND_LABELS[kind]} — {safe_text(order.number, 64)}",
        f"Приоритет: {PRIORITY_LABELS[order.priority]}",
        f"Оборудование: {safe_text(equipment.name if equipment else None)}",
        f"Участок: {safe_text(area.name if area else None)}",
    ]
    name = safe_text(responsible.display_name if responsible else None)
    if brigade:
        lines.extend([f"Бригада: {safe_text(brigade.name)}", f"Ответственный: {name}"])
    else:
        lines.append(f"Исполнитель: {name}")
    lines.append(f"Срок: {due:%d.%m.%Y %H:%M} ({safe_text(timezone, 64)})")
    if kind == "overdue":
        minutes = max(0, int((now - order.due_at).total_seconds() // 60))
        lines.extend([
            f"Просрочка: {minutes} мин.",
            f"Последний комментарий: {safe_text(comment, 700, empty='Нет комментария')}",
        ])
    lines.append(ACTIONS[kind])
    # Independent field limits keep even astral Unicode below 3500 UTF-16 units.
    return "\n".join(lines)
