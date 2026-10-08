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
KIND_LABELS_KK = {
    "new": "Жаңа наряд", "reminder": "Мерзімге 30 минут қалды",
    "unaccepted": "Наряд қабылданбады", "overdue": "Мерзімі өтті",
    "emergency_queued": "Апаттық наряд кезекте",
}
PRIORITY_LABELS_KK = {
    "emergency": "Апаттық", "high": "Жоғары", "normal": "Қалыпты", "planned": "Жоспарлы",
}
ACTIONS_KK = {
    "new": "Нарядты PWA ішінде қабылдаңыз.",
    "reminder": "Мерзім аяқталғанға дейін PWA ішінде жұмыс барысын жаңартыңыз.",
    "unaccepted": "PWA ішінде тағайындауды тексеріп, орындаушымен байланысыңыз.",
    "overdue": "PWA ішінде жұмыс барысын жаңартып, келесі әрекеттерді шебермен келісіңіз.",
    "emergency_queued": "PWA ішінде кезекті және апаттық нарядтың тағайындалуын тексеріңіз.",
}
FIELD_LABELS = {
    "ru": dict(priority="Приоритет", equipment="Оборудование", area="Участок", brigade="Бригада", responsible="Ответственный", worker="Исполнитель", due="Срок", overdue="Просрочка", comment="Последний комментарий", empty="Не указано", no_comment="Нет комментария", minute="мин."),
    "kk": dict(priority="Басымдық", equipment="Жабдық", area="Учаске", brigade="Бригада", responsible="Жауапты", worker="Орындаушы", due="Мерзім", overdue="Кешігу", comment="Соңғы түсініктеме", empty="Көрсетілмеген", no_comment="Түсініктеме жоқ", minute="мин."),
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
                        now, timezone, comment=None, language="ru"):
    language = "kk" if language == "kk" else "ru"
    fields = FIELD_LABELS[language]
    kinds, priorities, actions = (KIND_LABELS_KK, PRIORITY_LABELS_KK, ACTIONS_KK) if language == "kk" else (KIND_LABELS, PRIORITY_LABELS, ACTIONS)

    def value(text, limit=160):
        return safe_text(text, limit, empty=fields["empty"])

    due = order.due_at.astimezone(ZoneInfo(timezone))
    lines = [
        f"{kinds[kind]} — {value(order.number, 64)}",
        f"{fields['priority']}: {priorities[order.priority]}",
        f"{fields['equipment']}: {value(equipment.name if equipment else None)}",
        f"{fields['area']}: {value(area.name if area else None)}",
    ]
    name = value(responsible.display_name if responsible else None)
    if brigade:
        lines.extend([f"{fields['brigade']}: {value(brigade.name)}", f"{fields['responsible']}: {name}"])
    else:
        lines.append(f"{fields['worker']}: {name}")
    lines.append(f"{fields['due']}: {due:%d.%m.%Y %H:%M} ({value(timezone, 64)})")
    if kind == "overdue":
        minutes = max(0, int((now - order.due_at).total_seconds() // 60))
        lines.extend([
            f"{fields['overdue']}: {minutes} {fields['minute']}",
            f"{fields['comment']}: {safe_text(comment, 700, empty=fields['no_comment'])}",
        ])
    lines.append(actions[kind])
    # Independent field limits keep even astral Unicode below 3500 UTF-16 units.
    return "\n".join(lines)
