"""Telegram credentials stay one-use and private; HTTP uses real app auth."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from conftest import sign_in
from pydantic import SecretStr
from sqlalchemy import select
from work_order_helpers import headers, seed_order

NOW = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
BASE = "/api/v1/telegram"


def test_telegram_contract_exposes_link_webhook_and_delivery_reads():
    from app.main import app as production_app

    paths = production_app.openapi()["paths"]
    assert "post" in paths.get(BASE + "/link-token", {})
    assert "post" in paths.get(BASE + "/webhook", {})
    assert "get" in paths.get("/api/v1/work-orders/{order_id}/notifications", {})


def start(token, update_id=1, sender=123, chat=123, chat_type="private"):
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": sender},
            "chat": {"id": chat, "type": chat_type},
            "text": "/start " + token,
        },
    }


def test_link_route_requires_login_and_csrf(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "telegram_bot_username", "synthetic_bot")
    assert client.post(BASE + "/link-token").status_code == 401
    csrf = sign_in(client)
    assert client.post(BASE + "/link-token").status_code == 403
    response = client.post(BASE + "/link-token", headers=headers(csrf))
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["url"].startswith("https://t.me/synthetic_bot?start=")
    assert client.get(BASE + "/status").json() == {"linked": False}


def test_token_is_hashed_one_use_and_update_is_deduplicated(database):
    from app.modules.telegram.models import (
        TelegramBinding,
        TelegramLinkToken,
        TelegramUpdate,
    )
    from app.modules.telegram.service import handle_update, issue_link_token

    db, user = database["session"], database["worker"]
    token = issue_link_token(db, user, NOW)
    row = db.scalar(select(TelegramLinkToken))
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.expires_at == NOW + timedelta(minutes=10)
    assert handle_update(db, start(token), NOW) == "linked"
    assert handle_update(db, start(token), NOW) == "duplicate"
    assert handle_update(db, start(token, 2), NOW) == "invalid_token"
    db.commit()
    binding = db.get(TelegramBinding, user.id)
    assert binding.telegram_user_id == 123 and binding.private_chat_id == 123
    assert len(list(db.scalars(select(TelegramUpdate)))) == 2


@pytest.mark.parametrize("seconds", [600, 601])
def test_expired_token_cannot_bind(database, seconds):
    from app.modules.telegram.models import TelegramBinding
    from app.modules.telegram.service import handle_update, issue_link_token

    db = database["session"]
    token = issue_link_token(db, database["worker"], NOW)
    assert (
        handle_update(db, start(token), NOW + timedelta(seconds=seconds))
        == "invalid_token"
    )
    assert db.get(TelegramBinding, database["worker"].id) is None


@pytest.mark.parametrize(
    "sender,chat,kind",
    [
        (123, 123, "group"),
        (123, 124, "private"),
        (True, True, "private"),
        (0, 0, "private"),
        (-1, -1, "private"),
        ("123", "123", "private"),
        (2**63, 2**63, "private"),
    ],
)
def test_invalid_private_identity_never_consumes_token(database, sender, chat, kind):
    from app.modules.telegram.models import TelegramLinkToken
    from app.modules.telegram.service import handle_update, issue_link_token

    db = database["session"]
    token = issue_link_token(db, database["worker"], NOW)
    assert (
        handle_update(db, start(token, sender=sender, chat=chat, chat_type=kind), NOW)
        == "ignored"
    )
    assert db.scalar(select(TelegramLinkToken)).used_at is None


def test_conflicting_identity_requires_unlink_and_invalidates_tokens(database):
    from app.modules.telegram.models import TelegramBinding
    from app.modules.telegram.service import handle_update, issue_link_token, unlink

    db = database["session"]
    first = issue_link_token(db, database["worker"], NOW)
    assert handle_update(db, start(first), NOW) == "linked"
    other = issue_link_token(db, database["master"], NOW)
    assert handle_update(db, start(other, 2), NOW) == "conflict"
    relink = issue_link_token(db, database["worker"], NOW)
    assert handle_update(db, start(relink, 3, sender=124, chat=124), NOW) == "conflict"
    unlink(db, database["worker"], NOW)
    assert db.get(TelegramBinding, database["worker"].id) is None
    assert handle_update(db, start(relink, 4), NOW) == "invalid_token"


def test_webhook_secret_payload_limits_and_safe_status(client, database, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "telegram_webhook_secret", SecretStr("synthetic-secret")
    )
    assert client.post(BASE + "/webhook", json={"update_id": 1}).status_code == 403
    secret = {"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"}
    assert client.post(
        BASE + "/webhook", json={"update_id": 1}, headers=secret
    ).json() == {"result": "ignored"}
    assert (
        client.post(BASE + "/webhook", content="x" * 65537, headers=secret).status_code
        == 413
    )
    order = seed_order(database)
    sign_in(client, "outsider")
    assert (
        client.get(f"/api/v1/work-orders/{order['id']}/notifications").status_code
        == 404
    )
    sign_in(client, "worker")
    assert client.get(f"/api/v1/work-orders/{order['id']}/notifications").json() == []


def test_link_issuance_is_bounded(database):
    from app.core.security import AuthError
    from app.modules.telegram.service import issue_link_token

    for _ in range(5):
        issue_link_token(database["session"], database["worker"], NOW)
    with pytest.raises(AuthError) as error:
        issue_link_token(database["session"], database["worker"], NOW)
    assert error.value.status_code == 429
