"""CI-only API/outbox/worker acceptance without contacting a real Telegram bot."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import httpx
import psycopg

from verify_photo_persistence import validate_target

ROOT = Path(__file__).resolve().parents[1]


def state(connection, order_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, dedup_key, status, last_error FROM notifications "
            "WHERE work_order_id=%s ORDER BY dedup_key", (order_id,),
        )
        jobs = cursor.fetchall()
        cursor.execute(
            "SELECT count(*) FROM notification_receipts r JOIN outbox_events e "
            "ON e.id=r.outbox_id WHERE e.work_order_id=%s", (order_id,),
        )
        receipts = cursor.fetchone()[0]
    return jobs, receipts


def wait_state(connection, order_id, cancelled=False):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        jobs, receipts = state(connection, order_id)
        ready = (jobs and receipts >= 2 and all(row[2] == "CANCELLED" for row in jobs)) if cancelled else (
            jobs and receipts >= 1 and any(row[2:] == ("BLOCKED", "missing_configuration") for row in jobs)
        )
        if ready:
            return jobs
        time.sleep(0.25)
    raise AssertionError("Worker did not persist the expected notification state")


def main():
    database = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    base = os.environ.get("E2E_BASE_URL", "http://localhost:5173").rstrip("/")
    validate_target(database, base)
    prefix = os.environ["E2E_LOGIN"]
    if prefix != "e2e-worker" or os.environ.get("TELEGRAM_BOT_TOKEN"):
        raise SystemExit("Disposable synthetic accounts and no real Telegram token required")
    created = []
    with psycopg.connect(database, connect_timeout=5, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT u.id, a.area_id, e.id FROM users u JOIN user_areas a ON a.user_id=u.id "
                "JOIN equipment e ON e.area_id=a.area_id WHERE u.login=%s AND u.role='worker' "
                "ORDER BY e.id LIMIT 1", (prefix + "-t06-worker",),
            )
            assignment = cursor.fetchone()
        assert assignment is not None, "Synthetic worker/equipment not seeded"
        worker_id, area_id, equipment_id = assignment
        with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
            csrf = client.get("/api/v1/auth/csrf")
            csrf.raise_for_status()
            login = client.post("/api/v1/auth/login", json={
                "login": prefix + "-master-t06-worker", "password": os.environ["E2E_PASSWORD"],
            }, headers={"Origin": base, "X-CSRF-Token": csrf.json()["csrf_token"]})
            login.raise_for_status()
            headers = {"Origin": base, "X-CSRF-Token": login.json()["csrf_token"]}

            def issue():
                response = client.post("/api/v1/work-orders", json={
                    "description": "Synthetic notification worker acceptance", "work_type": "planned",
                    "area_id": str(area_id), "equipment_id": str(equipment_id), "assignee_id": str(worker_id),
                    "due_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                }, headers={**headers, "Idempotency-Key": str(uuid4())})
                response.raise_for_status()
                order = response.json()
                created.append(order["id"])
                return order["id"]

            try:
                first = issue()
                original = {(row[0], row[1]) for row in wait_state(connection, first)}
                restarted = subprocess.run(["docker", "compose", "restart", "worker"], cwd=ROOT,
                                           capture_output=True, timeout=45)
                assert restarted.returncode == 0, "Disposable worker restart failed"
                second = issue()
                wait_state(connection, second)
                assert {(row[0], row[1]) for row in state(connection, first)[0]} == original, "Worker restart duplicated jobs"
                assert len(original) == len({row[1] for row in state(connection, first)[0]}), "Notification dedup keys repeated"
            finally:
                for order_id in created:
                    detail = client.get(f"/api/v1/work-orders/{order_id}")
                    detail.raise_for_status()
                    cancelled = client.post(f"/api/v1/work-orders/{order_id}/actions", json={
                        "action": "cancel", "expected_version": detail.json()["version"],
                        "reason": "Synthetic worker acceptance cleanup",
                    }, headers={**headers, "Idempotency-Key": str(uuid4())})
                    cancelled.raise_for_status()
            for order_id in created:
                wait_state(connection, order_id, cancelled=True)
    print("PASS: production API/outbox/worker, persisted blocked jobs, restart dedup and cancellation; no live Telegram delivery")


if __name__ == "__main__":
    main()
