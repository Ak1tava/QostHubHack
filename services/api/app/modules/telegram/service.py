"""Caller commits: update dedup and one-use link consumption form one transaction."""

import re
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.core.security import AuthError, session_hash
from app.modules.auth.models import User
from app.modules.telegram.models import (
    TelegramBinding,
    TelegramLinkToken,
    TelegramUpdate,
)


def issue_link_token(db, user, now):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    count = db.scalar(
        select(func.count())
        .select_from(TelegramLinkToken)
        .where(
            TelegramLinkToken.user_id == user.id,
            TelegramLinkToken.created_at > now - timedelta(minutes=1),
        )
    )
    if count >= 5:
        raise AuthError(
            429, "rate_limited", "Слишком много попыток. Попробуйте позже", 60
        )
    # Keep one current credential and bounded history for rate limiting.
    db.execute(
        delete(TelegramLinkToken).where(
            TelegramLinkToken.user_id == user.id,
            TelegramLinkToken.expires_at < now - timedelta(minutes=1),
        )
    )
    db.execute(
        update(TelegramLinkToken)
        .where(
            TelegramLinkToken.user_id == user.id, TelegramLinkToken.used_at.is_(None)
        )
        .values(used_at=now)
    )
    token = secrets.token_urlsafe(32)
    db.add(
        TelegramLinkToken(
            token_hash=session_hash(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
        )
    )
    db.flush()
    return token


def unlink(db, user, now):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    db.execute(delete(TelegramBinding).where(TelegramBinding.user_id == user.id))
    db.execute(
        update(TelegramLinkToken)
        .where(
            TelegramLinkToken.user_id == user.id, TelegramLinkToken.used_at.is_(None)
        )
        .values(used_at=now)
    )
    db.flush()


def _identity(value):
    return type(value) is int and 0 < value < 2**63


def handle_update(db, payload, now):
    if (
        not isinstance(payload, dict)
        or type(payload.get("update_id")) is not int
        or not 0 <= payload["update_id"] < 2**63
    ):
        return "ignored"
    inserted = db.scalar(
        insert(TelegramUpdate)
        .values(update_id=payload["update_id"], received_at=now)
        .on_conflict_do_nothing()
        .returning(TelegramUpdate.update_id)
    )
    if inserted is None:
        return "duplicate"
    message = payload.get("message")
    if not isinstance(message, dict):
        return "ignored"
    sender, chat = message.get("from"), message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return "ignored"
    telegram_id, chat_id = sender.get("id"), chat.get("id")
    command = message.get("text")
    if (
        chat.get("type") != "private"
        or not _identity(telegram_id)
        or telegram_id != chat_id
        or not _identity(chat_id)
    ):
        return "ignored"
    if not isinstance(command, str) or not re.fullmatch(
        r"/start [A-Za-z0-9_-]{1,64}", command
    ):
        return "ignored"
    token_hash = session_hash(command[7:])
    # Discover owner without locking token first: issue/unlink and linking all
    # lock owner before token, avoiding a token/user lock-order deadlock.
    owner = db.scalar(
        select(TelegramLinkToken.user_id).where(
            TelegramLinkToken.token_hash == token_hash
        )
    )
    if owner is None:
        return "invalid_token"
    user = db.scalar(select(User).where(User.id == owner).with_for_update())
    token = db.scalar(
        select(TelegramLinkToken)
        .where(TelegramLinkToken.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not user
        or not user.is_active
        or not token
        or token.used_at is not None
        or token.expires_at <= now
    ):
        return "invalid_token"
    # Serializes competing Telegram identities without storing raw update payload.
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": telegram_id})
    binding = db.get(TelegramBinding, owner)
    other = db.scalar(
        select(TelegramBinding).where(TelegramBinding.telegram_user_id == telegram_id)
    )
    if (binding and binding.telegram_user_id != telegram_id) or (
        other and other.user_id != owner
    ):
        return "conflict"
    if binding is None:
        db.add(
            TelegramBinding(
                user_id=owner, telegram_user_id=telegram_id, private_chat_id=chat_id
            )
        )
    token.used_at = now
    db.flush()
    return "linked"
