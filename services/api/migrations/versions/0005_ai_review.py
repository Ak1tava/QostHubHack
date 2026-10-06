"""Durable AI stages and the contractual five-point master score.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    invalid = op.get_bind().scalar(sa.text(
        'SELECT count(*) FROM master_decisions WHERE score IS NOT NULL AND (score < 1 OR score > 5)'
    ))
    if invalid:
        raise RuntimeError(
            f'T07 requires scores 1..5: {invalid} legacy master decisions need explicit review; '
            'no historical score was modified.'
        )
    op.drop_constraint(op.f('ck_master_decisions_valid_score'), 'master_decisions', type_='check')
    op.create_check_constraint(op.f('ck_master_decisions_valid_score'), 'master_decisions',
                               'score IS NULL OR (score >= 1 AND score <= 5)')
    op.create_table(
        'review_receipts',
        sa.Column('outbox_id', sa.Uuid(), sa.ForeignKey('outbox_events.id'), primary_key=True),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'review_jobs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('submission_id', sa.Uuid(), sa.ForeignKey('submissions.id'), unique=True, nullable=False),
        sa.Column('work_order_id', sa.Uuid(), sa.ForeignKey('work_orders.id'), nullable=False),
        sa.Column('assignment_version', sa.Integer(), nullable=False),
        sa.Column('order_version', sa.Integer(), nullable=False),
        sa.Column('submission_revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('stage', sa.String(16), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=True),
        sa.Column('stage_outputs', sa.JSON(), nullable=False),
        sa.Column('calls', sa.JSON(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('snapshot_restarts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('lease_token', sa.Uuid()),
        sa.Column('last_error', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','running','blocked','completed','discarded')", name='valid_status'),
        sa.CheckConstraint('assignment_version > 0 AND order_version > 0 AND submission_revision > 0 AND attempts >= 0 AND snapshot_restarts >= 0', name='valid_counters'),
    )
    op.create_index('ix_review_jobs_work_order_id', 'review_jobs', ['work_order_id'])
    op.create_index('ix_review_jobs_next_attempt_at', 'review_jobs', ['next_attempt_at'])
    op.create_index('ix_review_jobs_ready', 'review_jobs', ['status', 'next_attempt_at'])


def downgrade():
    op.drop_table('review_jobs')
    op.drop_table('review_receipts')
    op.drop_constraint(op.f('ck_master_decisions_valid_score'), 'master_decisions', type_='check')
    op.create_check_constraint(op.f('ck_master_decisions_valid_score'), 'master_decisions',
                               'score IS NULL OR (score >= 0 AND score <= 100)')
