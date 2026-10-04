"""Capture/check a synthetic E2E photo around a separately managed API restart."""
import argparse
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx
from PIL import Image
import psycopg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "check"))
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    database = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    base = os.environ["E2E_BASE_URL"].rstrip("/")
    db_url, http_url = urlsplit(database), urlsplit(base)
    if (
        os.environ.get("CI") != "true"
        or db_url.scheme != "postgresql"
        or db_url.hostname not in ("localhost", "127.0.0.1", "::1")
        or db_url.path != "/qosthub_demo_t05"
        or http_url.scheme != "http"
        or http_url.hostname not in ("localhost", "127.0.0.1", "::1")
    ):
        raise SystemExit("CI=true, local qosthub_demo_t05 and loopback HTTP required")
    login = os.environ["E2E_LOGIN"] + "-t05-execution"
    if args.mode == "capture":
        with psycopg.connect(database, connect_timeout=5) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT p.id FROM photos p JOIN users u ON u.id=p.uploaded_by "
                    "WHERE u.login=%s ORDER BY p.received_at, p.id LIMIT 1", (login,)
                )
                row = cursor.fetchone()
        if row is None:
            raise SystemExit("No synthetic execution photo; complete execution E2E first")
        expected = {"photo_id": str(row[0])}
    else:
        expected = json.loads(args.state.read_text(encoding="utf-8"))
    url = f"{base}/api/v1/photos/{expected['photo_id']}"
    with httpx.Client(timeout=10, trust_env=False) as client:
        anonymous = client.get(url)
        if anonymous.status_code != 401:
            raise SystemExit(f"Anonymous photo GET returned {anonymous.status_code}, expected 401")
        csrf = client.get(f"{base}/api/v1/auth/csrf")
        csrf.raise_for_status()
        auth = client.post(
            f"{base}/api/v1/auth/login",
            json={"login": login, "password": os.environ["E2E_PASSWORD"]},
            headers={"Origin": base, "X-CSRF-Token": csrf.json()["csrf_token"]},
        )
        auth.raise_for_status()
        started = time.perf_counter()
        photo = client.get(url)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        photo.raise_for_status()
        if photo.headers.get("cache-control") != "no-store":
            raise SystemExit("Protected photo must have Cache-Control: no-store")
        if len(photo.content) > 5 * 1024 * 1024:
            raise SystemExit("Photo exceeds 5 MiB")
        with Image.open(BytesIO(photo.content)) as image:
            dimensions = list(image.size)
            image.verify()
        actual = {
            "photo_id": expected["photo_id"], "url": url,
            "sha256": hashlib.sha256(photo.content).hexdigest(),
            "size_bytes": len(photo.content), "dimensions": dimensions,
        }
        if args.mode == "capture":
            args.state.parent.mkdir(parents=True, exist_ok=True)
            args.state.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        elif actual != expected:
            raise SystemExit("Photo ID, URL, bytes, hash or dimensions changed after restart")
    print(json.dumps({"result": "PASS", "mode": args.mode, **actual, "get_ms": elapsed_ms}))


if __name__ == "__main__":
    main()
