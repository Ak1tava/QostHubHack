"""One-use Telegram links and independent persisted notification jobs.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telegram_link_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_telegram_link_tokens_user_id", "telegram_link_tokens", ["user_id"]
    )
    op.create_index(
        "ix_telegram_link_tokens_expires_at", "telegram_link_tokens", ["expires_at"]
    )
    op.create_table(
        "telegram_bindings",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("private_chat_id", sa.BigInteger(), nullable=False, unique=True),
        sa.CheckConstraint(
            "telegram_user_id > 0 AND private_chat_id = telegram_user_id",
            name="private_identity",
        ),
    )
    op.create_table(
        "telegram_updates",
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_telegram_updates_received_at", "telegram_updates", ["received_at"]
    )
    op.create_table(
        "notification_receipts",
        sa.Column(
            "outbox_id",
            sa.Uuid(),
            sa.ForeignKey("outbox_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column(
            "work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id"), nullable=False
        ),
        sa.Column("assignment_version", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dedup_key", sa.String(160), unique=True, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_error", sa.String(40)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "kind IN ('new','reminder','unaccepted','overdue','emergency_queued')",
            name="valid_kind",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','LEASED','RETRY','BLOCKED','SENT','FAILED','CANCELLED')",
            name="valid_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND assignment_version > 0", name="positive_counters"
        ),
    )
    op.create_index(
        "ix_notifications_work_order_id", "notifications", ["work_order_id"]
    )
    op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])
    op.create_index(
        "ix_notifications_ready", "notifications", ["status", "next_attempt_at"]
    )


def downgrade():
    for table in [
        "notifications",
        "notification_receipts",
        "telegram_updates",
        "telegram_bindings",
        "telegram_link_tokens",
    ]:
        op.drop_table(table)
