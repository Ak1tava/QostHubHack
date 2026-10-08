"""Notification content uses current authorised records and fake delivery only."""

from datetime import timedelta
import unicodedata

import pytest
from test_deadlines import NOW, Transport, deliver, order_at, rows
from test_deadlines import ready as ready


def send_one(database, ready, kind="new", **changes):
    from app.workers.notifications import schedule_notifications

    order = order_at(database, **changes)
    db = database["session"]
    schedule_notifications(order, NOW)
    db.commit()
    selected = next(job for job in rows(db) if job.kind == kind)
    for job in rows(db):
        if job.id != selected.id:
            job.status = "CANCELLED"
    db.commit()
    transport = Transport()
    deliver(ready, selected.due_at + timedelta(minutes=17), client=transport)
    return order, transport


@pytest.mark.parametrize("priority,label", [
    ("emergency", "Аварийный"), ("high", "Высокий"),
    ("normal", "Обычный"), ("planned", "Плановый"),
])
def test_message_contains_business_fields_and_local_deadline(database, ready, monkeypatch, priority, label):
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_timezone", "Asia/Qyzylorda")
    order, transport = send_one(database, ready, priority=priority)
    assert len(transport.messages) == 1
    _, message, url = transport.messages[0]
    assert message.startswith(f"Новый наряд — {order.number}\n")
    assert f"Приоритет: {label}" in message
    assert "Оборудование: Насос" in message
    assert "Участок: Первый участок" in message
    assert "Исполнитель: Исполнитель" in message
    assert "Срок: 05.10.2026 14:00 (Asia/Qyzylorda)" in message
    assert "Примите наряд в PWA" in message
    assert url == f"https://synthetic.invalid/orders/{order.id}"
    assert str(order.id) not in message
    assert "LEASED" not in message


def test_brigade_message_names_current_responsible(database, ready):
    _, transport = send_one(database, ready, assignee_id=None,
                            brigade_id=database["brigade"].id,
                            responsible_id=database["worker"].id)
    message = transport.messages[0][1]
    assert "Бригада: Первая бригада" in message
    assert "Ответственный: Исполнитель" in message


def test_overdue_uses_latest_nonblank_current_order_comment(database, ready):
    from app.modules.work_orders.models import WorkOrderEvent
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    order = order_at(database)
    other = order_at(database, number="WO-PRIVATE", assignee_id=database["outsider"].id)
    for version, target, assignment, reason in [
        (2, order, 1, "Ожидаем деталь <b> & продолжим"),
        (3, order, 1, "  "),
        (4, order, 0, "Прежнее назначение — секрет"),
        (2, other, 1, "Чужой секрет"),
    ]:
        db.add(WorkOrderEvent(work_order_id=target.id, actor_id=database["worker"].id,
                            action="pause", version=version, assignment_version=assignment,
                            reason=reason, occurred_at=NOW + timedelta(minutes=version)))
    schedule_notifications(order, NOW)
    db.commit()
    for job in rows(db):
        if job.kind != "overdue" or job.recipient_id != database["worker"].id:
            job.status = "CANCELLED"
    db.commit()
    transport = Transport()
    deliver(ready, order.due_at + timedelta(minutes=17, seconds=59), client=transport)
    message = transport.messages[0][1]
    assert "Просрочка: 17 мин." in message
    assert "Последний комментарий: Ожидаем деталь <b> & продолжим" in message
    assert "секрет" not in message
    assert "WO-PRIVATE" not in message
    assert "Обновите ход работ в PWA" in message


def test_message_bounds_untrusted_fields_and_removes_controls(database, ready):
    database["equipment"].name = "😀" * 250
    database["worker"].display_name = "Работник\nСрок: подмена\u202e"
    database["session"].flush()
    _, transport = send_one(database, ready)
    message = transport.messages[0][1]
    assert len(message.encode("utf-16-le")) // 2 <= 3500
    assert "…" in message
    assert all(character == "\n" or not unicodedata.category(character).startswith("C") for character in message)
    assert "\nСрок: подмена" not in message


def test_overdue_without_comment_has_explicit_empty_value(database, ready):
    _, transport = send_one(database, ready, kind="overdue")
    assert "Последний комментарий: Нет комментария" in transport.messages[0][1]


def test_overdue_chooses_newer_submission_comment_over_transition_reason(database, ready):
    from sqlalchemy import select
    from app.modules.catalog.models import WorkCode
    from app.modules.work_orders.models import Submission, WorkOrderEvent
    from app.workers.notifications import schedule_notifications

    db = database["session"]
    order = order_at(database, status="REWORK")
    db.add(WorkOrderEvent(work_order_id=order.id, actor_id=database["worker"].id,
                        action="pause", version=2, assignment_version=1,
                        reason="Старый комментарий", occurred_at=NOW))
    code = db.scalar(select(WorkCode.id).limit(1))
    for revision, assignment, comment in [(1, 1, "Новый комментарий отчёта"), (2, 0, "Секрет прежнего назначения")]:
        db.add(Submission(work_order_id=order.id, revision=revision, assignment_version=assignment,
                          worker_id=database["worker"].id, work_description="Синтетический ремонт",
                          work_code_id=code, no_materials_used=True, comment=comment,
                          submitted_at=NOW + timedelta(minutes=revision)))
    schedule_notifications(order, NOW)
    db.commit()
    for job in rows(db):
        if job.kind != "overdue" or job.recipient_id != database["worker"].id:
            job.status = "CANCELLED"
    db.commit()
    transport = Transport()
    deliver(ready, order.due_at + timedelta(minutes=1), client=transport)
    message = transport.messages[0][1]
    assert "Последний комментарий: Новый комментарий отчёта" in message
    assert "Старый комментарий" not in message
    assert "Секрет прежнего назначения" not in message


def test_denied_recipient_never_receives_private_content(database, ready):
    from app.workers.notifications import schedule_notifications

    order = order_at(database)
    db = database["session"]
    schedule_notifications(order, NOW)
    db.commit()
    order.assignee_id = database["outsider"].id
    db.commit()
    transport = Transport()
    deliver(ready, NOW, client=transport)
    assert transport.messages == []


def test_formatter_bounds_every_field_even_with_astral_unicode():
    from types import SimpleNamespace
    from app.modules.telegram.formatter import format_notification, safe_text

    huge = "😀" * 5000
    named = SimpleNamespace(name=huge, display_name=huge)
    message = format_notification(
        kind="overdue", order=SimpleNamespace(number=huge, priority="normal", due_at=NOW),
        equipment=named, area=named, responsible=named, brigade=named,
        now=NOW + timedelta(minutes=23), timezone="UTC", comment=huge,
    )
    assert len(message.encode("utf-16-le")) // 2 <= 3500
    assert "Срок: 05.10.2026 08:00 (UTC)" in message
    assert message.endswith("с мастером.")
    assert safe_text("\x00\t\r\n\u202eРаботник\x1b") == "Работник"
