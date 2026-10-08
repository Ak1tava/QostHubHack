"""Persisted links, webhook receipts, dedicated outbox cursor and delivery jobs."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TelegramLinkToken(Base):
    __tablename__ = "telegram_link_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramBinding(Base):
    __tablename__ = "telegram_bindings"
    __table_args__ = (
        CheckConstraint("language IN ('ru','kk')", name="valid_language"),
        CheckConstraint(
            "telegram_user_id > 0 AND private_chat_id = telegram_user_id",
            name="private_identity",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    private_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    language: Mapped[str] = mapped_column(
        String(2), nullable=False, default="ru", server_default="ru"
    )


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class NotificationReceipt(Base):
    __tablename__ = "notification_receipts"
    outbox_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="CASCADE"), primary_key=True
    )
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('new','reminder','unaccepted','overdue','emergency_queued')",
            name="valid_kind",
        ),
        CheckConstraint(
            "status IN ('PENDING','LEASED','RETRY','BLOCKED','SENT','FAILED','CANCELLED')",
            name="valid_status",
        ),
        CheckConstraint(
            "attempts >= 0 AND assignment_version > 0", name="positive_counters"
        ),
        Index("ix_notifications_ready", "status", "next_attempt_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(24))
    work_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("work_orders.id"), index=True
    )
    assignment_version: Mapped[int] = mapped_column(Integer)
    recipient_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dedup_key: Mapped[str] = mapped_column(String(160), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    last_error: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
