"""Persist each linked user's Telegram notification language."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "telegram_bindings",
        sa.Column("language", sa.String(2), nullable=False, server_default="ru"),
    )
    op.create_check_constraint(
        "valid_language", "telegram_bindings", "language IN ('ru','kk')"
    )


def downgrade():
    op.drop_constraint("valid_language", "telegram_bindings", type_="check")
    op.drop_column("telegram_bindings", "language")
