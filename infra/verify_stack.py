"""CI-only acceptance on the disposable Compose stack; never use on production."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
WEB = "http://localhost:5173"


def compose(*args: str) -> str:
    result = subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"docker compose {' '.join(args[:2])} failed (exit {result.returncode})")
    return result.stdout.strip()


def health(base: str, path: str) -> tuple[int, dict]:
    try:
        with urlopen(base + path, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def wait_ready(status: int) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if health(API, "/health/ready") == (status, {"status": "ready" if status == 200 else "not_ready"}):
                return
        except (URLError, TimeoutError):
            pass
        time.sleep(1)
    raise AssertionError(f"Readiness did not reach HTTP {status}")


def main() -> None:
    if os.environ.get("CI") != "true":
        raise SystemExit("This command restarts the disposable CI stack; CI=true is required")
    wait_ready(200)
    assert health(WEB, "/health/ready") == (200, {"status": "ready"})
    cluster = compose("exec", "-T", "db", "psql", "-U", "qosthub", "-d", "qosthub_demo", "-Atc", "SELECT system_identifier FROM pg_control_system()")
    users = compose("exec", "-T", "db", "psql", "-U", "qosthub", "-d", "qosthub_demo", "-Atc", "SELECT count(*) FROM users")
    assert int(users) > 0, "Acceptance accounts were not seeded"
    marker = secrets.token_hex(16)
    python = "/workspace/services/api/.venv/bin/python"
    compose("exec", "-T", "api", python, "-c", "import sys; from pathlib import Path; Path('/workspace/data/photos/t01-probe.txt').write_text(sys.argv[1])", marker)
    compose("stop", "db")
    wait_ready(503)
    assert health(API, "/health/live") == (200, {"status": "ok"})
    assert health(WEB, "/health/live") == (200, {"status": "ok"})
    assert health(WEB, "/health/ready") == (503, {"status": "not_ready"})
    compose("start", "db")
    wait_ready(200)
    compose("down")
    compose("up", "-d", "--wait", "--wait-timeout", "120")
    wait_ready(200)
    restored_cluster = compose("exec", "-T", "db", "psql", "-U", "qosthub", "-d", "qosthub_demo", "-Atc", "SELECT system_identifier FROM pg_control_system()")
    assert restored_cluster == cluster, "PostgreSQL volume was reinitialized"
    assert compose("exec", "-T", "db", "psql", "-U", "qosthub", "-d", "qosthub_demo", "-Atc", "SELECT count(*) FROM users") == users, "Account data did not persist"
    restored_marker = compose("exec", "-T", "api", python, "-c", "from pathlib import Path; print(Path('/workspace/data/photos/t01-probe.txt').read_text())")
    assert restored_marker == marker, "Photo volume did not persist"
    compose("exec", "-T", "api", python, "-c", "from pathlib import Path; Path('/workspace/data/photos/t01-probe.txt').unlink()")
    print("PASS: real SQL readiness, database outage/recovery, PostgreSQL and private photo volume persistence")


if __name__ == "__main__":
    main()
