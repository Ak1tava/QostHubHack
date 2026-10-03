"""Upgrade/downgrade only in an explicitly dedicated migration database."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
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
            command.upgrade(config, "head")
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0001"
            )
            assert set(Base.metadata.tables) <= set(
                inspect(connection).get_table_names()
            )
            assert (
                compare_metadata(MigrationContext.configure(connection), Base.metadata)
                == []
            )
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names()) <= {"alembic_version"}
            command.upgrade(config, "head")
    finally:
        engine.dispose()
