import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.db import get_db
from app.core.security import AuthError, get_current_user, require_order_access
from app.modules.auth.models import User
from app.modules.auth.schemas import ErrorResponse
from app.modules.telegram import service
from app.modules.telegram.models import Notification, TelegramBinding
from app.modules.work_orders.models import WorkOrder

router = APIRouter(tags=["telegram"])
ERRORS = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 413, 422, 429, 503)
}


class LinkTokenResponse(BaseModel):
    token: str
    url: str
    expires_at: datetime


class LinkStatus(BaseModel):
    linked: bool


class LanguageButton(BaseModel):
    text: Literal["RU", "KZ"]


class LanguageKeyboard(BaseModel):
    keyboard: list[list[LanguageButton]]
    resize_keyboard: bool
    is_persistent: bool


class WebhookResult(BaseModel):
    result: str
    method: Literal["sendMessage"] | None = None
    chat_id: int | None = None
    text: str | None = None
    reply_markup: LanguageKeyboard | None = None


class DeliveryStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    assignment_version: int
    recipient_id: UUID
    due_at: datetime
    next_attempt_at: datetime
    attempts: int
    status: str
    last_error: str | None
    sent_at: datetime | None


@router.post(
    "/telegram/link-token",
    response_model=LinkTokenResponse,
    status_code=201,
    responses=ERRORS,
)
def link_token(
    response: Response,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    username = settings.telegram_bot_username
    if not username or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise AuthError(503, "telegram_not_configured", "Telegram не настроен")
    now = datetime.now(timezone.utc)
    token = service.issue_link_token(db, actor, now)
    db.commit()
    return LinkTokenResponse(
        token=token,
        url=f"https://t.me/{username}?start={token}",
        expires_at=now + timedelta(minutes=10),
    )


@router.get("/telegram/status", response_model=LinkStatus, responses=ERRORS)
def status(
    response: Response,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return LinkStatus(linked=db.get(TelegramBinding, actor.id) is not None)


@router.post("/telegram/unlink", response_model=LinkStatus, responses=ERRORS)
def unlink(
    response: Response,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    service.unlink(db, actor, datetime.now(timezone.utc))
    db.commit()
    return LinkStatus(linked=False)


def _webhook_transaction(db, payload):
    """One synchronous unit of work; no raw DB exception escapes to ASGI logs."""
    try:
        result = service.handle_update(db, payload, datetime.now(timezone.utc))
        reply = service.prepare_reply(db, payload, result)
        db.commit()
        return WebhookResult(result=result, **reply)
    except SQLAlchemyError:
        try:
            db.rollback()
        except SQLAlchemyError:
            pass
        raise AuthError(
            503, "telegram_unavailable", "Telegram временно недоступен"
        ) from None


@router.post("/telegram/webhook", response_model=WebhookResult, response_model_exclude_none=True, responses=ERRORS)
async def webhook(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    secret = settings.telegram_webhook_secret
    if not secret:
        raise AuthError(503, "telegram_not_configured", "Telegram не настроен")
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if len(supplied) > 256 or not hmac.compare_digest(
        supplied.encode(), secret.get_secret_value().encode()
    ):
        raise AuthError(403, "invalid_webhook_secret", "Запрос отклонён")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65536:
            raise AuthError(413, "payload_too_large", "Запрос слишком большой")
        body.extend(chunk)
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise AuthError(422, "invalid_payload", "Некорректный запрос") from None
    return await run_in_threadpool(_webhook_transaction, db, payload)


@router.get(
    "/work-orders/{order_id}/notifications",
    response_model=list[DeliveryStatus],
    responses=ERRORS,
)
def notifications(
    order_id: UUID,
    response: Response,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    order = db.get(WorkOrder, order_id)
    if order is None:
        raise AuthError(404, "not_found", "Объект не найден")
    require_order_access(db, actor, order)
    query = select(Notification).where(Notification.work_order_id == order_id)
    if actor.role == "worker":
        query = query.where(Notification.recipient_id == actor.id)
    return list(
        db.scalars(
            query
            .order_by(Notification.due_at, Notification.id)
        )
    )
