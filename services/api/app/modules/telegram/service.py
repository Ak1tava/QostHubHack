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


def private_message(payload):
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        return None
    sender, chat = message.get("from"), message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return None
    if (chat.get("type") != "private" or not _identity(sender.get("id"))
            or not _identity(chat.get("id")) or sender["id"] != chat["id"]
            or not isinstance(message.get("text"), str)):
        return None
    return sender, chat, message["text"]


def telegram_language(value):
    return "kk" if isinstance(value, str) and value.casefold().split("-")[0] == "kk" else "ru"


def _language_command(db, telegram_id, command):
    binding = db.scalar(select(TelegramBinding).where(TelegramBinding.telegram_user_id == telegram_id))
    if binding is None:
        return "not_linked"
    # Match issue/unlink/link lock order: user first, then binding. Re-read after
    # the user lock, because unlink may have completed while we waited.
    user = db.scalar(select(User).where(User.id == binding.user_id).with_for_update().execution_options(populate_existing=True))
    binding = db.scalar(select(TelegramBinding).where(
        TelegramBinding.telegram_user_id == telegram_id,
    ).with_for_update().execution_options(populate_existing=True))
    if not user or not user.is_active or not binding or binding.user_id != user.id:
        return "not_linked"
    language = {"/ru": "ru", "ru": "ru", "/kz": "kk", "/kk": "kk", "kz": "kk", "kk": "kk"}.get(command)
    if language:
        binding.language = language
        db.flush()
        return "language_updated"
    return "language_menu" if command == "/language" else "help"


def prepare_reply(db, payload, result):
    """Prepare a webhook sendMessage response; caller commits before returning it."""
    private = private_message(payload)
    if private is None or result in {"ignored", "duplicate"}:
        return {}
    sender, chat, _ = private
    binding = db.scalar(select(TelegramBinding).join(User).where(
        TelegramBinding.telegram_user_id == sender["id"], User.is_active.is_(True),
    ))
    language = binding.language if binding else None
    if language is None:
        text = (
            "Привяжите Telegram в PWA: откройте раздел Telegram и нажмите «Привязать». "
            "После привязки язык выбирается через /language (RU/KZ).\n"
            "Telegram-ды PWA ішінде байланыстырыңыз: Telegram бөлімін ашып, «Байланыстыру» түймесін басыңыз. "
            "Байланыстырғаннан кейін тілді /language арқылы таңдаңыз (RU/KZ)."
        )
    else:
        texts = {
            "ru": {
                "linked": "Telegram привязан. Здесь приходят уведомления; принятие и закрытие нарядов — в PWA. Язык: /language (RU/KZ).",
                "language_updated": "Выбран русский язык. Уведомления будут на русском. Сменить язык: /language (RU/KZ).",
                "language_menu": "Выберите язык уведомлений: RU — русский, KZ — қазақша.",
                "help": "Здесь приходят уведомления. Все действия с нарядами выполняются в PWA. Сменить язык: /language (RU/KZ).",
                "invalid_token": "Ссылка привязки недействительна. Создайте новую в PWA. Язык: /language (RU/KZ).",
                "conflict": "Привязка не выполнена. Проверьте подключение Telegram в PWA. Язык: /language (RU/KZ).",
            },
            "kk": {
                "linked": "Telegram байланыстырылды. Мұнда хабарламалар келеді; нарядты қабылдау және жабу PWA ішінде орындалады. Тіл: /language (RU/KZ).",
                "language_updated": "Қазақ тілі таңдалды. Хабарламалар қазақ тілінде келеді. Тілді өзгерту: /language (RU/KZ).",
                "language_menu": "Хабарламалар тілін таңдаңыз: RU — русский, KZ — қазақша.",
                "help": "Мұнда хабарламалар келеді. Нарядқа қатысты барлық әрекет PWA ішінде орындалады. Тілді өзгерту: /language (RU/KZ).",
                "invalid_token": "Байланыстыру сілтемесі жарамсыз. PWA ішінде жаңа сілтеме жасаңыз. Тіл: /language (RU/KZ).",
                "conflict": "Байланыстыру орындалмады. PWA ішінде Telegram байланысын тексеріңіз. Тіл: /language (RU/KZ).",
            },
        }
        text = texts[language].get(result, texts[language]["help"])
    reply = dict(method="sendMessage", chat_id=chat["id"], text=text)
    if binding:
        reply["reply_markup"] = {
            "keyboard": [[{"text": "RU"}, {"text": "KZ"}]],
            "resize_keyboard": True, "is_persistent": True,
        }
    return reply


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
    private = private_message(payload)
    if private is None:
        return "ignored"
    sender, chat, command = private
    telegram_id, chat_id = sender["id"], chat["id"]
    normalized = command.strip().casefold()
    if normalized in {"/language", "/ru", "/kz", "/kk", "ru", "kz", "kk", "/start", "/help"}:
        return _language_command(db, telegram_id, normalized)
    if not re.fullmatch(r"/start [A-Za-z0-9_-]{1,64}", command):
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
                user_id=owner, telegram_user_id=telegram_id, private_chat_id=chat_id,
                language=telegram_language(sender.get("language_code")),
            )
        )
    token.used_at = now
    db.flush()
    return "linked"
