"""Independent AI outbox consumer and durable, token-fenced stage jobs."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.work_orders.models import utcnow


class ReviewReceipt(Base):
    __tablename__ = "review_receipts"
    outbox_id: Mapped[UUID] = mapped_column(ForeignKey("outbox_events.id"), primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewJob(Base):
    __tablename__ = "review_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('pending','running','blocked','completed','discarded')", name="valid_status"),
        CheckConstraint("assignment_version > 0 AND order_version > 0 AND submission_revision > 0 AND attempts >= 0 AND snapshot_restarts >= 0", name="valid_counters"),
        Index("ix_review_jobs_ready", "status", "next_attempt_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id"), unique=True)
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    assignment_version: Mapped[int] = mapped_column(Integer)
    order_version: Mapped[int] = mapped_column(Integer)
    submission_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    stage: Mapped[str] = mapped_column(String(16), default="prepare")
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stage_outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    calls: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_restarts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
