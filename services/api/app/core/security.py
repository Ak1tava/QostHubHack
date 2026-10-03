"""Password verification and shared authorization dependencies."""

import base64
import hashlib
import hmac
import secrets
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.modules.auth.models import User, UserArea


class AuthError(Exception):
    def __init__(
        self, status_code: int, code: str, message: str, retry_after: int | None = None
    ):
        self.status_code, self.code, self.message, self.retry_after = (
            status_code,
            code,
            message,
            retry_after,
        )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return (
        "pbkdf2_sha256$600000$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(digest).decode()
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        rounds = int(iterations)
        if algorithm != "pbkdf2_sha256" or not 600_000 <= rounds <= 2_000_000:
            return False
        salt_bytes = base64.b64decode(salt, validate=True)
        expected_bytes = base64.b64decode(expected, validate=True)
        if len(salt_bytes) != 16 or len(expected_bytes) != 32:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt_bytes, rounds
        )
        return hmac.compare_digest(actual, expected_bytes)
    except (ValueError, TypeError):
        return False


def session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cookie_secure() -> bool:
    url = urlsplit(settings.public_base_url)
    if url.scheme == "https":
        return True
    if url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}:
        return settings.session_cookie_secure
    raise AuthError(503, "configuration_error", "Для входа требуется HTTPS")


def origin_matches(request: Request) -> bool:
    expected = urlsplit(settings.public_base_url)
    raw = request.headers.get("origin")
    if raw is None:
        raw = request.headers.get("referer")
    if not raw:
        return False
    try:
        parsed = urlsplit(raw)
        if parsed.username or parsed.password or not parsed.hostname:
            return False
        actual_origin = (
            parsed.scheme,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
        expected_origin = (
            expected.scheme,
            expected.hostname,
            expected.port or (443 if expected.scheme == "https" else 80),
        )
        if request.headers.get("origin") is not None and (
            parsed.path not in {"", "/"} or parsed.query or parsed.fragment
        ):
            return False
        return actual_origin == expected_origin
    except ValueError:
        return False


def require_csrf(request: Request, auth_session) -> None:
    supplied = request.headers.get("x-csrf-token", "")
    if (
        not auth_session
        or not supplied
        or len(supplied) > 128
        or not origin_matches(request)
    ):
        raise AuthError(403, "csrf_failed", "Проверка безопасности запроса не пройдена")
    if not hmac.compare_digest(
        supplied.encode("utf-8"), auth_session.csrf_token.encode("utf-8")
    ):
        raise AuthError(403, "csrf_failed", "Проверка безопасности запроса не пройдена")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    from app.modules.auth.service import read_session

    row = read_session(db, request)
    user = db.get(User, row.user_id) if row and row.user_id else None
    if not user or not user.is_active:
        raise AuthError(401, "unauthenticated", "Требуется вход")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        require_csrf(request, row)
    return user


def allowed_area_ids(db: Session, user: User) -> set[UUID]:
    return set(db.scalars(select(UserArea.area_id).where(UserArea.user_id == user.id)))


def require_order_creation(db: Session, actor: User, area_id: UUID) -> None:
    if (
        not actor.is_active
        or actor.role != "master"
        or area_id not in allowed_area_ids(db, actor)
    ):
        raise AuthError(403, "forbidden", "Действие недоступно")


def can_access_order(db: Session, actor: User, order, *, write: bool = False) -> bool:
    if not actor.is_active:
        return False
    if actor.role in {"master", "manager", "admin"}:
        return order.area_id in allowed_area_ids(db, actor) and (
            not write or actor.role == "master"
        )
    if actor.role != "worker":
        return False
    if order.assignee_id == actor.id:
        return True
    if order.brigade_id and order.brigade_id == actor.brigade_id:
        return not write or order.responsible_id == actor.id
    return False


def require_order_access(
    db: Session, actor: User, order, *, write: bool = False
) -> None:
    if not can_access_order(db, actor, order, write=write):
        raise AuthError(404, "not_found", "Объект не найден")
