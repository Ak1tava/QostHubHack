from alembic import context

from app.core.db import Base, get_engine
from app.modules.auth import (
    models as auth_models,  # noqa: F401 — registers SQLAlchemy metadata
)
from app.modules.catalog import (
    models as catalog_models,  # noqa: F401 — registers SQLAlchemy metadata
)
from app.modules.work_orders import models  # noqa: F401 — registers SQLAlchemy metadata
from app.modules.telegram import models as telegram_models  # noqa: F401
from app.modules.ai_review import jobs_models as review_models  # noqa: F401


def run_migrations():
    # No offline URL/logging: secrets stay inside the configured engine.
    if context.is_offline_mode():
        raise RuntimeError("Use online migrations against PostgreSQL")
    existing = context.config.attributes.get("connection")
    if existing is not None:
        context.configure(
            connection=existing, target_metadata=Base.metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        with get_engine().connect() as connection:
            context.configure(
                connection=connection, target_metadata=Base.metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()


run_migrations()
