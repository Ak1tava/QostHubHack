"""Work orders, immutable revisions, lifecycle audit and transactional outbox."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    Numeric,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

ORDER_NUMBER_SEQUENCE = Sequence("work_order_number_seq", metadata=Base.metadata)


def utcnow():
    return datetime.now(timezone.utc)


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint(
            "(assignee_id IS NOT NULL AND brigade_id IS NULL AND responsible_id IS NULL) OR (assignee_id IS NULL AND brigade_id IS NOT NULL AND responsible_id IS NOT NULL)",
            name="one_assignment",
        ),
        CheckConstraint("work_type IN ('planned','emergency')", name="valid_work_type"),
        CheckConstraint(
            "priority IN ('emergency','high','normal','planned')", name="valid_priority"
        ),
        CheckConstraint(
            "status IN ('ISSUED','ACCEPTED','QUEUED','REJECTED','IN_PROGRESS','PAUSED','SUBMITTED','AI_REVIEW','REWORK','CLOSED','CANCELLED')",
            name="valid_status",
        ),
        CheckConstraint(
            "version > 0 AND assignment_version > 0", name="positive_versions"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    number: Mapped[str] = mapped_column(String(64), unique=True)
    work_type: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(Text)
    area_id: Mapped[UUID] = mapped_column(ForeignKey("areas.id"), index=True)
    equipment_id: Mapped[UUID] = mapped_column(ForeignKey("equipment.id"), index=True)
    assignee_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    brigade_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("brigades.id"), index=True
    )
    responsible_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    master_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(24), default="ISSUED", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    assignment_version: Mapped[int] = mapped_column(Integer, default=1)
    queue_position: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class WorkOrderEvent(Base):
    __tablename__ = "work_order_events"
    __table_args__ = (UniqueConstraint("work_order_id", "version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("work_orders.id"), index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    assignment_version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("work_order_id", "revision"),
        CheckConstraint("revision > 0", name="positive_revision"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("work_orders.id"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    assignment_version: Mapped[int] = mapped_column(Integer, default=1)
    worker_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    work_description: Mapped[str] = mapped_column(Text)
    work_code_id: Mapped[UUID] = mapped_column(ForeignKey("work_codes.id"))
    no_materials_used: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Photo(Base):
    __tablename__ = "photos"
    __table_args__ = (CheckConstraint("type IN ('before','after')", name="valid_type"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("work_orders.id"), index=True
    )
    submission_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("submissions.id"), index=True
    )
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    mime_type: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(16), index=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class MaterialUsage(Base):
    __tablename__ = "material_usage"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="positive_quantity"),
        UniqueConstraint("submission_id", "material_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("submissions.id"), index=True
    )
    material_id: Mapped[UUID] = mapped_column(ForeignKey("materials.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))


class AIReview(Base):
    __tablename__ = "ai_reviews"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("submissions.id"), unique=True
    )
    order_version: Mapped[int] = mapped_column(Integer)
    assignment_version: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class MasterDecision(Base):
    __tablename__ = "master_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('accept','rework')", name="valid_decision"),
        CheckConstraint(
            "score IS NULL OR (score >= 1 AND score <= 5)", name="valid_score"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("work_orders.id"), index=True
    )
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id"))
    master_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(Integer)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class DowntimeInterval(Base):
    __tablename__ = "downtime_intervals"
    __table_args__ = (
        CheckConstraint(
            "end_at IS NULL OR end_at > start_at", name="positive_interval"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    equipment_id: Mapped[UUID] = mapped_column(ForeignKey("equipment.id"), index=True)
    work_order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("work_orders.id"), index=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)


Index(
    "uq_work_orders_active_responsible",
    func.coalesce(WorkOrder.assignee_id, WorkOrder.responsible_id),
    unique=True,
    postgresql_where=WorkOrder.status == "IN_PROGRESS",
)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    work_order_id: Mapped[UUID | None] = mapped_column(ForeignKey("work_orders.id"))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("work_order_events.id"), unique=True)
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    assignment_version: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkOrderInterval(Base):
    __tablename__ = "work_order_intervals"
    __table_args__ = (
        CheckConstraint("kind IN ('active','pause','review')", name="valid_kind"),
        CheckConstraint("end_at IS NULL OR end_at >= start_at", name="nonnegative_interval"),
        Index(
            "uq_work_order_intervals_open", "work_order_id", unique=True,
            postgresql_where=text("end_at IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
