"""Disposable Compose acceptance of the real AI worker with paid calls disabled."""
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


def docker(*arguments):
    result = subprocess.run(["docker", "compose", *arguments], cwd=ROOT,
                            capture_output=True, timeout=45)
    if result.returncode:
        if arguments[0] == "exec":
            raise AssertionError("AI worker must run without an OpenAI key on a local synthetic demo database")
        raise AssertionError("Disposable AI worker configuration check/restart failed")


def state(connection, order_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, submission_id, status, attempts, last_error FROM review_jobs "
                       "WHERE work_order_id=%s", (order_id,))
        jobs = cursor.fetchall()
        cursor.execute("SELECT count(*) FROM review_receipts r JOIN outbox_events e "
                       "ON e.id=r.outbox_id WHERE e.work_order_id=%s AND e.type='work_order.submit'",
                       (order_id,))
        receipts = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM ai_reviews r JOIN submissions s "
                       "ON s.id=r.submission_id WHERE s.work_order_id=%s", (order_id,))
        reviews = cursor.fetchone()[0]
    return jobs, receipts, reviews


def wait_state(connection, order_id, expected="blocked"):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        jobs, receipts, reviews = state(connection, order_id)
        assert len(jobs) <= 1 and receipts <= 1 and reviews == 0, "Duplicate job/receipt or fake AI result"
        if len(jobs) == receipts == 1 and jobs[0][2] == expected:
            assert jobs[0][3] == 0, "Unconfigured AI worker must make zero model attempts"
            if expected == "blocked":
                assert jobs[0][4] == "api_key_missing", "Wrong reason for blocked review"
            return jobs[0]
        time.sleep(0.25)
    raise AssertionError(f"AI worker did not persist {expected} state within 45 seconds")


def sign_in(client, base, login):
    csrf = client.get("/api/v1/auth/csrf")
    csrf.raise_for_status()
    auth = client.post("/api/v1/auth/login", json={"login": login, "password": os.environ["E2E_PASSWORD"]},
                       headers={"Origin": base, "X-CSRF-Token": csrf.json()["csrf_token"]})
    auth.raise_for_status()
    return {"Origin": base, "X-CSRF-Token": auth.json()["csrf_token"]}


def post(client, path, body, headers):
    response = client.post(path, json=body, headers={**headers, "Idempotency-Key": str(uuid4())})
    response.raise_for_status()
    return response.json()


def main():
    database = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    base = os.environ.get("E2E_BASE_URL", "http://localhost:5173").rstrip("/")
    validate_target(database, base)
    prefix = os.environ["E2E_LOGIN"]
    if prefix != "e2e-worker" or os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Synthetic e2e-worker accounts and no OpenAI key required")
    # Check the actual running container configuration before submitting anything.
    # Never print configuration values or trust only the host's environment.
    docker("exec", "-T", "ai-worker", "/workspace/services/api/.venv/bin/python", "-c",
           "from app.core.config import settings; from sqlalchemy.engine import make_url; "
           "u=make_url(settings.database_url.get_secret_value()); "
           "assert not settings.openai_api_key and u.host in ('db','localhost','127.0.0.1') "
           "and u.database in ('qosthub_demo','qosthub_demo_t05'), 'Unsafe AI worker target/configuration'")
    with psycopg.connect(database, connect_timeout=5, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT u.id, a.area_id, e.id FROM users u JOIN user_areas a ON a.user_id=u.id "
                           "JOIN areas ar ON ar.id=a.area_id JOIN equipment e ON e.area_id=a.area_id "
                           "WHERE u.login=%s AND u.role='worker' AND u.is_active "
                           "AND ar.name='Демонстрационный участок' ORDER BY e.id LIMIT 1",
                           (prefix + "-t07-review",))
            assignment = cursor.fetchone()
            cursor.execute("SELECT id FROM work_codes WHERE code='T05-DEMO'")
            work_code = cursor.fetchone()
            cursor.execute("SELECT id FROM users WHERE login=%s AND role='master' AND is_active",
                           (prefix + "-master-t07-review",))
            master = cursor.fetchone()
        assert assignment and work_code and master, "Synthetic T07 accounts/equipment/work code not seeded"
        worker_id, area_id, equipment_id = assignment
        with httpx.Client(base_url=base, timeout=10, trust_env=False) as client, \
                httpx.Client(base_url=base, timeout=10, trust_env=False) as worker:
            master_headers = sign_in(client, base, prefix + "-master-t07-review")
            worker_headers = sign_in(worker, base, prefix + "-t07-review")
            order = post(client, "/api/v1/work-orders", {
                "description": "Плановый синтетический отчёт: Compose AI worker acceptance",
                "work_type": "planned", "area_id": str(area_id), "equipment_id": str(equipment_id),
                "assignee_id": str(worker_id),
                "due_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            }, master_headers)
            path = f"/api/v1/work-orders/{order['id']}"
            try:
                for action in ("accept", "start"):
                    order = post(worker, path + "/actions",
                                 {"action": action, "expected_version": order["version"]}, worker_headers)
                report = post(worker, path + "/submissions", {
                    "expected_version": order["version"], "assignment_version": order["assignment_version"],
                    "work_description": "Синтетическое соединение проверено; неисправность устранена",
                    "fault_code_id": str(work_code[0]), "materials": [], "no_materials_used": True,
                    "after_photo_ids": [], "comment": "CI synthetic acceptance",
                }, worker_headers)
                original = wait_state(connection, order["id"])
                assert str(original[1]) == report["id"], "Job belongs to another report"
                docker("restart", "ai-worker")
                # Redeliver the same submit to this consumer only. The receipt
                # and unique job must be recovered without touching other cursors.
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute("DELETE FROM review_receipts r USING outbox_events e "
                                       "WHERE r.outbox_id=e.id AND e.work_order_id=%s "
                                       "AND e.type='work_order.submit'", (order["id"],))
                        assert cursor.rowcount == 1, "Expected exactly one synthetic receipt to redeliver"
                recovered = wait_state(connection, order["id"])
                assert recovered[:2] == original[:2], "Worker restart/redelivery created a second review job"
                detail = client.get(path)
                detail.raise_for_status()
                assert detail.json()["status"] == "AI_REVIEW" and detail.json()["ai_review"] is None
            finally:
                detail = client.get(path)
                detail.raise_for_status()
                post(client, path + "/actions", {
                    "action": "cancel", "expected_version": detail.json()["version"],
                    "reason": "Synthetic AI worker acceptance cleanup",
                }, master_headers)
            wait_state(connection, order["id"], expected="discarded")
    print("PASS: real API/AI worker, blocked persistence, restart/redelivery dedup and stale cancellation; zero paid calls")


if __name__ == "__main__":
    main()
