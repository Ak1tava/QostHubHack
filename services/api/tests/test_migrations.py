"""Upgrade/downgrade only in an explicitly dedicated migration database."""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url


def test_empty_postgres_migration_roundtrip():
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set MIGRATION_TEST_DATABASE_URL to qosthub_migration_test*")
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or not (
        parsed.database or ""
    ).startswith("qosthub_migration_test"):
        pytest.fail("Refusing migration reset outside qosthub_migration_test*")
    from app.core.db import Base
    from app.modules.auth import (
        models as auth_models,  # noqa: F401 — registers SQLAlchemy metadata
    )
    from app.modules.catalog import (
        models as catalog_models,  # noqa: F401 — registers SQLAlchemy metadata
    )
    from app.modules.work_orders import (
        models,  # noqa: F401 — registers SQLAlchemy metadata
    )

    engine = create_engine(url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names()) <= {"alembic_version"}
            command.upgrade(config, "0001")
            user_id, area_id, equipment_id = uuid4(), uuid4(), uuid4()
            connection.execute(auth_models.User.__table__.insert().values(
                id=user_id, login="migration-worker", password_hash="not-a-real-hash",
                display_name="Migration fixture", role="worker",
            ))
            connection.execute(catalog_models.Area.__table__.insert().values(
                id=area_id, name="Migration area",
            ))
            connection.execute(catalog_models.Equipment.__table__.insert().values(
                id=equipment_id, area_id=area_id, name="Migration equipment",
            ))
            for number in ["W001", "WO-000041"]:
                connection.execute(models.WorkOrder.__table__.insert().values(
                    number=number, work_type="planned", description="Migration fixture",
                    area_id=area_id, equipment_id=equipment_id,
                    master_id=user_id, assignee_id=user_id,
                    due_at=datetime.now(timezone.utc),
                ))
            command.upgrade(config, "head")
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == ScriptDirectory.from_config(config).get_current_head()
            )
            assert connection.scalar(select(models.ORDER_NUMBER_SEQUENCE.next_value())) == 42
            assert set(Base.metadata.tables) <= set(
                inspect(connection).get_table_names()
            )
            assert (
                compare_metadata(MigrationContext.configure(connection), Base.metadata)
                == []
            )
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names()) <= {"alembic_version"}
            assert "work_order_number_seq" not in inspect(connection).get_sequence_names()
            command.upgrade(config, "head")
    finally:
        engine.dispose()
