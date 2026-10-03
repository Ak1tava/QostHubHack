"""Persistent opaque sessions and atomic PostgreSQL throttles."""

import math
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.security import (
    AuthError,
    cookie_secure,
    hash_password,
    require_csrf,
    session_hash,
    verify_password,
)
from app.modules.auth.models import AuthSession, AuthThrottle, User
from app.modules.auth.schemas import LoginRequest

COOKIE = "qosthub_session"
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def now_utc():
    return datetime.now(timezone.utc)


def read_session(db: Session, request: Request, *, lock: bool = False):
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 128:
        return None
    query = select(AuthSession).where(
        AuthSession.token_hash == session_hash(token),
        AuthSession.expires_at > now_utc(),
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query.execution_options(populate_existing=True))


def enforce_limits(db: Session, keys: list[tuple[str, int, int]]) -> None:
    now = now_utc()
    exceeded = []
    # Stable lock order prevents deadlocks across concurrent login requests.
    for name, limit, seconds in sorted(keys):
        key = session_hash(name)
        table = AuthThrottle.__table__
        statement = insert(table).values(
            key=key, attempts=1, expires_at=now + timedelta(seconds=seconds)
        )
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.key],
            set_={
                "attempts": case(
                    (table.c.expires_at <= now, 1), else_=table.c.attempts + 1
                ),
                "expires_at": case(
                    (table.c.expires_at <= now, now + timedelta(seconds=seconds)),
                    else_=table.c.expires_at,
                ),
            },
        ).returning(table.c.attempts, table.c.expires_at)
        attempts, expires_at = db.execute(statement).one()
        if attempts > limit:
            exceeded.append(max(1, math.ceil((expires_at - now).total_seconds())))
    if exceeded:
        db.commit()  # failed requests must not erase their throttle counters
        raise AuthError(
            429,
            "rate_limited",
            "Слишком много попыток. Попробуйте позже",
            max(exceeded),
        )


def peer(request: Request) -> str:
    # Only the ASGI peer: never trust arbitrary X-Forwarded-For headers here.
    return request.client.host if request.client else "unknown"


def issue_session(db: Session, user_id, response: Response):
    secure = cookie_secure()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = now_utc()
    lifetime = 12 * 3600 if user_id else 15 * 60
    row = AuthSession(
        token_hash=session_hash(token),
        user_id=user_id,
        csrf_token=csrf,
        created_at=now,
        expires_at=now + timedelta(seconds=lifetime),
    )
    db.add(row)
    db.flush()
    response.set_cookie(
        COOKIE,
        token,
        max_age=lifetime,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return row


def prune_expired_throttles(db: Session) -> None:
    # Bound the batch and skip rows being updated by concurrent requests.
    expired = list(
        db.scalars(
            select(AuthThrottle.key)
            .where(AuthThrottle.expires_at <= now_utc())
            .order_by(AuthThrottle.key)
            .limit(500)
            .with_for_update(skip_locked=True)
        )
    )
    if expired:
        db.execute(delete(AuthThrottle).where(AuthThrottle.key.in_(expired)))


def csrf(db: Session, request: Request, response: Response):
    prune_expired_throttles(db)
    enforce_limits(db, [("csrf-ip:" + peer(request), 60, 60)])
    row = read_session(db, request)
    if row is None:
        # Expired tokens may remain in browsers; remove only expired server rows.
        db.execute(delete(AuthSession).where(AuthSession.expires_at <= now_utc()))
        row = issue_session(db, None, response)
    db.commit()
    return row.csrf_token


def login(db: Session, request: Request, response: Response, payload: LoginRequest):
    row = read_session(db, request, lock=True)
    require_csrf(request, row)
    # Stop a blocked IP before allocating keys for attacker-controlled logins.
    enforce_limits(db, [("login-ip:" + peer(request), 30, 900)])
    enforce_limits(
        db,
        [
            ("login-account:" + payload.login.casefold(), 10, 900),
            ("login-pair:" + peer(request) + ":" + payload.login.casefold(), 5, 900),
        ],
    )
    user = db.scalar(select(User).where(User.login == payload.login))
    verified = verify_password(
        payload.password, user.password_hash if user else _DUMMY_HASH
    )
    if not verified or not user or not user.is_active:
        db.commit()
        raise AuthError(401, "invalid_credentials", "Неверный логин или пароль")
    db.delete(row)
    new_row = issue_session(db, user.id, response)
    db.commit()
    return user, new_row.csrf_token


def logout(db: Session, request: Request, response: Response):
    row = read_session(db, request, lock=True)
    user = db.get(User, row.user_id) if row and row.user_id else None
    if not user or not user.is_active:
        raise AuthError(401, "unauthenticated", "Требуется вход")
    require_csrf(request, row)
    db.delete(row)
    db.commit()
    response.delete_cookie(
        COOKIE, path="/", secure=cookie_secure(), httponly=True, samesite="lax"
    )
