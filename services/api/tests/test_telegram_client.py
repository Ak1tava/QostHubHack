"""HTTP boundary responses produce sanitized delivery results, never raw URLs."""

import json
import socket

import pytest
from pydantic import SecretStr


def test_http_message_contains_only_summary_and_https_button(monkeypatch):
    from app.core.config import settings
    from app.modules.telegram.client import TelegramClient

    monkeypatch.setattr(
        settings, "telegram_bot_token", SecretStr("synthetic-secret-token")
    )
    sent = []

    def transport(request, timeout):
        assert 0 < timeout < 60
        sent.append(json.loads(request.data))
        return 200, {"ok": True, "result": {"message_id": 1}}

    TelegramClient(transport=transport).send_message(
        123, "WO-1 | normal | 09:00", "https://synthetic.invalid/orders/1"
    )
    assert sent == [
        {
            "chat_id": 123,
            "text": "WO-1 | normal | 09:00",
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "Открыть наряд",
                            "url": "https://synthetic.invalid/orders/1",
                        }
                    ]
                ]
            },
        }
    ]


@pytest.mark.parametrize(
    "status,body,code,retry",
    [
        (
            403,
            {"ok": False, "description": "private raw diagnostic"},
            "bot_blocked",
            None,
        ),
        (429, {"ok": False, "parameters": {"retry_after": 37}}, "rate_limited", 37),
        (
            500,
            {"ok": False, "description": "private raw diagnostic"},
            "telegram_unavailable",
            None,
        ),
        (200, {"ok": False, "error_code": 403}, "bot_blocked", None),
        (200, {}, "invalid_response", None),
    ],
)
def test_http_errors_are_sanitized(monkeypatch, status, body, code, retry):
    from app.core.config import settings
    from app.modules.telegram.client import TelegramClient, TelegramError

    monkeypatch.setattr(
        settings, "telegram_bot_token", SecretStr("synthetic-secret-token")
    )
    with pytest.raises(TelegramError) as error:
        TelegramClient(transport=lambda request, timeout: (status, body)).send_message(
            123, "summary", "https://synthetic.invalid/order"
        )
    assert str(error.value) == code and error.value.retry_after == retry


def test_timeout_and_missing_configuration_do_not_leak_transport_exception(monkeypatch):
    from app.core.config import settings
    from app.modules.telegram.client import TelegramClient, TelegramError

    monkeypatch.setattr(
        settings, "telegram_bot_token", SecretStr("synthetic-secret-token")
    )

    def timeout(request, timeout):
        raise socket.timeout("https://api.telegram.org/botPRIVATE/sendMessage")

    with pytest.raises(TelegramError, match="^timeout$"):
        TelegramClient(transport=timeout).send_message(
            123, "summary", "https://synthetic.invalid/order"
        )
    monkeypatch.setattr(settings, "telegram_bot_token", None)
    with pytest.raises(TelegramError, match="^missing_configuration$"):
        TelegramClient(transport=timeout).send_message(
            123, "summary", "https://synthetic.invalid/order"
        )


def test_non_https_button_and_unsafe_webhook_configuration_are_rejected(monkeypatch):
    from app.core.config import settings
    from app.modules.telegram.client import TelegramClient, TelegramError

    monkeypatch.setattr(
        settings, "telegram_bot_token", SecretStr("synthetic-secret-token")
    )
    with pytest.raises(TelegramError, match="^invalid_public_url$"):
        TelegramClient().send_message(123, "summary", "http://localhost/order")
    monkeypatch.setattr(settings, "telegram_webhook_secret", SecretStr("bad secret"))
    monkeypatch.setattr(settings, "public_base_url", "https://synthetic.invalid")
    with pytest.raises(TelegramError, match="^invalid_webhook_configuration$"):
        TelegramClient().set_webhook()


def test_real_transport_does_not_follow_redirects_with_credentials():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.request import Request

    from app.modules.telegram.client import _transport

    captured = []

    class Destination(BaseHTTPRequestHandler):
        def do_GET(self):
            captured.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *args):
            pass

    destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            # Consume the POST body before closing, so Windows does not reset
            # an unread socket before the client can receive the redirect.
            assert self.rfile.read(int(self.headers["Content-Length"])) == b"{}"
            self.send_response(302)
            self.send_header("Content-Length", "0")
            self.send_header(
                "Location",
                f"http://127.0.0.1:{destination.server_port}/botSYNTHETIC/sendMessage",
            )
            self.end_headers()

        def log_message(self, *args):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threads = [
        Thread(target=server.serve_forever, daemon=True)
        for server in (destination, source)
    ]
    for thread in threads:
        thread.start()
    try:
        status, body = _transport(
            Request(
                f"http://127.0.0.1:{source.server_port}/botSYNTHETIC/sendMessage",
                data=b"{}",
            ),
            1,
        )
        assert status == 302 and captured == []
    finally:
        for server in (source, destination):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
