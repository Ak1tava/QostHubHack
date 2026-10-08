"""The real photo acceptance script only reads explicitly disposable local targets."""

from pathlib import Path
import runpy
import sys

import pytest


def test_compose_photo_capture_reaches_database_validation(monkeypatch, tmp_path):
    """The existing CLI must accept the disposable Compose database used by CI."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://qosthub:synthetic@127.0.0.1:5432/qosthub_demo")
    monkeypatch.setenv("E2E_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("E2E_LOGIN", "e2e-worker")
    monkeypatch.setattr(sys, "argv", ["verify_photo_persistence.py", "capture", "--state", str(tmp_path / "photo.json")])

    class DatabaseCheckpoint(Exception):
        pass

    def checkpoint(*args, **kwargs):
        raise DatabaseCheckpoint

    import psycopg
    monkeypatch.setattr(psycopg, "connect", checkpoint)
    script = Path(__file__).resolve().parents[3] / "infra/verify_photo_persistence.py"
    with pytest.raises(DatabaseCheckpoint):
        runpy.run_path(str(script), run_name="__main__")


@pytest.fixture
def validate(monkeypatch):
    monkeypatch.setenv("CI", "true")
    script = Path(__file__).resolve().parents[3] / "infra/verify_photo_persistence.py"
    namespace = runpy.run_path(str(script))
    assert callable(namespace.get("validate_target")), "Persistence guard must be independently verifiable"
    return namespace["validate_target"]


@pytest.mark.parametrize("name", ["qosthub_demo", "qosthub_demo_t05"])
def test_photo_acceptance_allows_disposable_compose_and_native_targets(validate, name):
    validate(f"postgresql://qosthub:synthetic@127.0.0.1:5432/{name}", "http://localhost:5173")


@pytest.mark.parametrize("database,base", [
    ("postgresql://qosthub@127.0.0.1/qosthub", "http://localhost:5173"),
    ("postgresql://qosthub@127.0.0.1/qosthub_demo_prod", "http://localhost:5173"),
    ("postgresql://qosthub@example.com/qosthub_demo", "http://localhost:5173"),
    ("postgresql://qosthub@127.0.0.1/qosthub_demo?hostaddr=192.0.2.1", "http://localhost:5173"),
    ("postgresql://qosthub@127.0.0.1/qosthub_demo?dbname=qosthub", "http://localhost:5173"),
    ("postgresql://qosthub@127.0.0.1/qosthub_demo#fragment", "http://localhost:5173"),
    ("postgresql://qosthub@127.0.0.1/qosthub_demo", "https://example.com"),
    ("postgresql://qosthub@127.0.0.1/qosthub_demo", "http://localhost:5173?target=production"),
    ("postgresql://qosthub@127.0.0.1/qosthub_demo", "http://user:secret@localhost:5173"),
])
def test_photo_acceptance_refuses_other_targets(validate, database, base):
    with pytest.raises(SystemExit, match="disposable"):
        validate(database, base)


def test_photo_acceptance_requires_explicit_ci_mode(validate, monkeypatch):
    monkeypatch.delenv("CI")
    with pytest.raises(SystemExit, match="CI=true"):
        validate("postgresql://qosthub@127.0.0.1/qosthub_demo", "http://localhost:5173")


@pytest.mark.parametrize("variable", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"])
def test_photo_acceptance_refuses_driver_environment_overrides(validate, monkeypatch, variable):
    monkeypatch.setenv(variable, "synthetic-override")
    with pytest.raises(SystemExit, match="disposable"):
        validate("postgresql://qosthub@127.0.0.1/qosthub_demo", "http://localhost:5173")


@pytest.mark.parametrize("session_expired", [False, True])
def test_restart_reuses_session_without_login_or_cookie_disclosure(monkeypatch, tmp_path, capsys, session_expired):
    """A restart must keep authorization; logging in again hides session loss and hits limits."""
    from io import BytesIO
    import json
    from unittest.mock import MagicMock

    import httpx
    from PIL import Image
    import psycopg

    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test@localhost/qosthub_demo")
    monkeypatch.setenv("E2E_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("E2E_LOGIN", "e2e-worker")
    monkeypatch.setenv("E2E_PASSWORD", "synthetic-password")
    connection = MagicMock()
    connection.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = ("synthetic-photo",)
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: connection)
    pixels = BytesIO()
    Image.new("RGB", (2, 2), "red").save(pixels, format="PNG")
    token = "synthetic-opaque-session-not-public"
    login_count = 0
    anonymous_count = 0
    restarted = False

    def respond(request):
        nonlocal login_count, anonymous_count
        path = request.url.path
        if path.endswith("/csrf"):
            return httpx.Response(200, json={"csrf_token": "synthetic-csrf"})
        if path.endswith("/login"):
            login_count += 1
            if login_count > 1:
                return httpx.Response(429, headers={"Retry-After": "900"})
            return httpx.Response(200, json={"user": {"id": "synthetic-worker"}}, headers={"Set-Cookie": f"qosthub_session={token}; Path=/; HttpOnly"})
        authorized = f"qosthub_session={token}" in request.headers.get("cookie", "")
        if not authorized:
            anonymous_count += 1
            return httpx.Response(401)
        if restarted and session_expired:
            return httpx.Response(401)
        if path.endswith("/me"):
            return httpx.Response(200, json={"user": {"id": "synthetic-worker"}})
        return httpx.Response(200, content=pixels.getvalue(), headers={"Cache-Control": "no-store"})

    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    script = Path(__file__).resolve().parents[3] / "infra/verify_photo_persistence.py"
    state = tmp_path / "photo.json"
    monkeypatch.setattr(sys, "argv", [str(script), "capture", "--state", str(state)])
    runpy.run_path(str(script), run_name="__main__")
    metadata = json.loads(state.read_text())
    restarted = True
    monkeypatch.setattr(sys, "argv", [str(script), "check", "--state", str(state)])
    if session_expired:
        with pytest.raises(httpx.HTTPStatusError) as error:
            runpy.run_path(str(script), run_name="__main__")
        assert error.value.response.status_code == 401
    else:
        runpy.run_path(str(script), run_name="__main__")
    assert login_count == 1
    assert anonymous_count == 2
    assert token not in json.dumps(metadata)
    assert token not in capsys.readouterr().out
