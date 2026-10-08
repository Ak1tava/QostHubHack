"""Integration seams: unambiguous upgrade history and usable notification links."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr


def test_telegram_migration_follows_published_photo_revision_without_ambiguity():
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "migrations"))
    directory = ScriptDirectory.from_config(config)
    assert len(directory.get_heads()) == 1, "upgrade head must have one unambiguous target"
    telegram = directory.get_revision("0004")
    assert telegram.down_revision == "0003", "Existing photo databases must upgrade without resetting evidence"


def test_prepared_telegram_button_opens_the_existing_pwa_order_route(monkeypatch):
    from app.core.config import settings
    from app.modules.auth.models import User
    from app.modules.catalog.models import Area, Equipment
    from app.modules.telegram.models import Notification, TelegramBinding
    from app.modules.work_orders.models import WorkOrder
    from app.workers.notifications import _prepare

    now = datetime(2026, 10, 6, 9, tzinfo=timezone.utc)
    worker = User(id=uuid4(), login="synthetic-worker", display_name="Worker", role="worker", is_active=True)
    order = WorkOrder(id=uuid4(), number="WO-000001", status="ISSUED", priority="normal",
                      assignee_id=worker.id, brigade_id=None, master_id=uuid4(),
                      assignment_version=1, due_at=now + timedelta(hours=1))
    job = Notification(id=uuid4(), work_order_id=order.id, recipient_id=worker.id,
                       assignment_version=1, kind="new", status="LEASED", attempts=0,
                       lease_token=uuid4(), lease_until=now + timedelta(seconds=60))
    binding = TelegramBinding(user_id=worker.id, telegram_user_id=123, private_chat_id=123)
    area = Area(id=uuid4(), name="Первый участок")
    equipment = Equipment(id=uuid4(), name="Насос", area_id=area.id)
    order.area_id, order.equipment_id = area.id, equipment.id
    entities = {WorkOrder: order, Notification: job, User: worker, TelegramBinding: binding,
                Area: area, Equipment: equipment}

    class PersistenceRows:
        """Only the external persistence boundary is replaced; preparation is real."""
        def get(self, model, identity):
            return entities[model]

        def scalar(self, statement):
            return entities[statement.column_descriptions[0]["entity"]]

        def flush(self):
            pass

    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("synthetic-test-token"))
    monkeypatch.setattr(settings, "public_base_url", "https://synthetic.invalid/")
    prepared = _prepare(PersistenceRows(), (job.id, job.lease_token), lambda: now)
    assert prepared is not None
    assert prepared[2] == f"https://synthetic.invalid/orders/{order.id}"
    assert prepared[1].startswith("Новый наряд — WO-000001\n")
    assert "Приоритет: Обычный" in prepared[1]
    assert "Оборудование: Насос" in prepared[1]
