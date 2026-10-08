"""Versioned requirements on orders and immutable checklist answers on submissions."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work_orders", sa.Column("template_snapshot", sa.JSON(none_as_null=True), nullable=True))
    op.add_column("submissions", sa.Column("template_answers", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("submissions", "template_answers")
    op.drop_column("work_orders", "template_snapshot")
