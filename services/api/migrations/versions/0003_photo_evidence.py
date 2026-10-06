"""Photo capture claim and perceptual fingerprint.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("photos", sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("photos", sa.Column("perceptual_hash", sa.String(16), nullable=True))
    op.create_index(op.f("ix_photos_perceptual_hash"), "photos", ["perceptual_hash"])


def downgrade():
    op.drop_index(op.f("ix_photos_perceptual_hash"), table_name="photos")
    op.drop_column("photos", "perceptual_hash")
    op.drop_column("photos", "captured_at")
