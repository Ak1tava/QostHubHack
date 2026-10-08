"""Bounded Telegram HTTP transport. Exceptions contain only stable safe codes."""

import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.core.config import settings

HTTP_TIMEOUT = 10  # shorter than the worker's 60-second lease


class TelegramError(Exception):
    def __init__(self, code, *, retry_after=None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


def https_url(url):
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not (
                parsed.username or parsed.password or parsed.query or parsed.fragment
            )
        )
    except ValueError:
        return False


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _transport(request, timeout):
    try:
        response = build_opener(_NoRedirect).open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(65537)
        if len(raw) > 65536:
            raise TelegramError("invalid_response")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            body = {}
        return response.status, body


class TelegramClient:
    def __init__(self, *, transport=None):
        self.transport = transport or _transport

    def _call(self, method, body):
        if not settings.telegram_bot_token:
            raise TelegramError("missing_configuration")
        token = settings.telegram_bot_token.get_secret_value()
        request = Request(
            "https://api.telegram.org/bot" + token + "/" + method,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            status, result = self.transport(request, HTTP_TIMEOUT)
        except (TimeoutError, socket.timeout):
            raise TelegramError("timeout") from None
        except URLError as error:
            code = (
                "timeout"
                if isinstance(error.reason, (TimeoutError, socket.timeout))
                else "telegram_unavailable"
            )
            raise TelegramError(code) from None
        except TelegramError:
            raise
        except Exception:
            raise TelegramError("telegram_unavailable") from None
        result = result if isinstance(result, dict) else {}
        code = result.get("error_code", status)
        if code == 403:
            raise TelegramError("bot_blocked")
        if code == 429:
            parameters = result.get("parameters")
            retry = (
                parameters.get("retry_after") if isinstance(parameters, dict) else None
            )
            retry = retry if type(retry) is int and 0 < retry <= 86400 else 60
            raise TelegramError("rate_limited", retry_after=retry)
        if status >= 500 or (type(code) is int and code >= 500):
            raise TelegramError("telegram_unavailable")
        if 300 <= status < 400:
            raise TelegramError("telegram_unavailable")
        if status >= 400:
            raise TelegramError("telegram_rejected")
        if result.get("ok") is not True:
            raise TelegramError("invalid_response")
        return result.get("result")

    def send_message(self, chat_id, text, url, *, language="ru"):
        if not https_url(url):
            raise TelegramError("invalid_public_url")
        self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": {
                    "inline_keyboard": [[{"text": "Нарядты ашу" if language == "kk" else "Открыть наряд", "url": url}]]
                },
            },
        )

    def set_webhook(self):
        secret = settings.telegram_webhook_secret
        if (
            not secret
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret.get_secret_value())
            or not https_url(settings.public_base_url)
        ):
            raise TelegramError("invalid_webhook_configuration")
        return self._call(
            "setWebhook",
            {
                "url": settings.public_base_url.rstrip("/")
                + "/api/v1/telegram/webhook",
                "secret_token": secret.get_secret_value(),
                "allowed_updates": ["message"],
                "drop_pending_updates": False,
            },
        )

    def webhook_info(self):
        result = self._call("getWebhookInfo", {})
        # Telegram's diagnostic text/URL can contain user configuration; never print it.
        if not isinstance(result, dict):
            raise TelegramError("invalid_response")
        return {
            "configured": bool(result.get("url")),
            "pending_update_count": result.get("pending_update_count", 0),
            "has_delivery_error": bool(result.get("last_error_date")),
        }
