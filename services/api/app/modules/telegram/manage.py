"""Explicit operator command; configuration comes from environment, never argv."""

import argparse
import json

from app.modules.telegram.client import TelegramClient, TelegramError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["set-webhook", "info"])
    command = parser.parse_args().command
    try:
        client = TelegramClient()
        result = (
            {"configured": bool(client.set_webhook())}
            if command == "set-webhook"
            else client.webhook_info()
        )
        print(json.dumps(result))
    except TelegramError as error:
        print(json.dumps({"error": error.code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
