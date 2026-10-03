"""Work order lifecycle, audit guarantees and transactional outbox.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.schema.CreateSequence(sa.Sequence("work_order_number_seq")))
    # Preserve existing WO-numbers when upgrading populated databases. Legacy
    # W001-style numbers occupy a separate namespace from the new WO- prefix.
    op.execute(sa.text("""
        SELECT setval(
            'work_order_number_seq',
            GREATEST(COALESCE(
                (SELECT MAX(SUBSTRING(number FROM 4)::bigint)
                 FROM work_orders WHERE number ~ '^WO-[0-9]+$'), 0
            ), 0) + 1,
            false
        )
    """))
    op.create_index(
        "uq_work_orders_active_responsible", "work_orders",
        [sa.text("coalesce(assignee_id, responsible_id)")], unique=True,
        postgresql_where=sa.text("status = 'IN_PROGRESS'"),
    )
    op.create_unique_constraint(
        op.f("uq_work_order_events_work_order_id"),
        "work_order_events", ["work_order_id", "version"],
    )
    op.add_column("submissions", sa.Column(
        "no_materials_used", sa.Boolean(), server_default=sa.false(), nullable=False,
    ))
    op.create_table(
        "idempotency_records",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_idempotency_records_actor_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["work_order_id"], ["work_orders.id"],
            name=op.f("fk_idempotency_records_work_order_id_work_orders"),
        ),
        sa.PrimaryKeyConstraint("actor_id", "key", name=op.f("pk_idempotency_records")),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("assignment_version", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"], ["work_order_events.id"],
            name=op.f("fk_outbox_events_event_id_work_order_events"),
        ),
        sa.ForeignKeyConstraint(
            ["work_order_id"], ["work_orders.id"],
            name=op.f("fk_outbox_events_work_order_id_work_orders"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
        sa.UniqueConstraint("event_id", name=op.f("uq_outbox_events_event_id")),
    )
    op.create_index("ix_outbox_events_work_order_id", "outbox_events", ["work_order_id"])
    op.create_table(
        "work_order_intervals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('active','pause','review')",
            name=op.f("ck_work_order_intervals_valid_kind"),
        ),
        sa.CheckConstraint(
            "end_at IS NULL OR end_at >= start_at",
            name=op.f("ck_work_order_intervals_nonnegative_interval"),
        ),
        sa.ForeignKeyConstraint(
            ["work_order_id"], ["work_orders.id"],
            name=op.f("fk_work_order_intervals_work_order_id_work_orders"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_order_intervals")),
    )
    op.create_index(
        "ix_work_order_intervals_work_order_id", "work_order_intervals", ["work_order_id"],
    )
    op.create_index(
        "uq_work_order_intervals_open", "work_order_intervals", ["work_order_id"],
        unique=True, postgresql_where=sa.text("end_at IS NULL"),
    )


def downgrade():
    op.drop_index("uq_work_order_intervals_open", table_name="work_order_intervals")
    op.drop_index("ix_work_order_intervals_work_order_id", table_name="work_order_intervals")
    op.drop_table("work_order_intervals")
    op.drop_index("ix_outbox_events_work_order_id", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("idempotency_records")
    op.drop_column("submissions", "no_materials_used")
    op.drop_constraint(
        op.f("uq_work_order_events_work_order_id"), "work_order_events", type_="unique",
    )
    op.drop_index("uq_work_orders_active_responsible", table_name="work_orders")
    op.execute(sa.schema.DropSequence(sa.Sequence("work_order_number_seq")))
