import os
import subprocess
import sys

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
import psycopg
import pytest

from app.core.config import settings
from app.main import app


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def test_import_liveness_and_openapi_do_not_connect_to_database():
    script = '''
import psycopg
def forbidden_connection(*args, **kwargs):
    raise AssertionError("Database connection during import or liveness")
psycopg.connect = forbidden_connection
from app.main import app
import asyncio
from httpx import ASGITransport, AsyncClient
async def check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")
        assert response.json() == {"status": "ok"}
        assert response.status_code == 200
        assert (await client.get("/openapi.json")).status_code == 200
asyncio.run(check())
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "DATABASE_URL": "invalid-url", "OPENAI_API_KEY": ""},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("database_url", [None, "invalid-url", "sqlite:///demo.db"])
async def test_readiness_rejects_missing_or_invalid_database(client, monkeypatch, database_url):
    monkeypatch.setattr(settings, "database_url", SecretStr(database_url) if database_url else None)
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


async def test_unreachable_database_does_not_break_liveness(client, monkeypatch):
    monkeypatch.setattr(settings, "database_url", SecretStr("postgresql+psycopg://probe:unused@127.0.0.1:1/qosthub"))
    assert (await client.get("/health/ready")).status_code == 503
    assert (await client.get("/health/live")).json() == {"status": "ok"}


async def test_readiness_suppresses_database_error_details(client, monkeypatch):
    monkeypatch.setattr(settings, "database_url", SecretStr("postgresql+psycopg://probe:unused@db/qosthub"))

    def unavailable(*args, **kwargs):
        raise psycopg.OperationalError("private connection details")

    monkeypatch.setattr(psycopg, "connect", unavailable)
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "private" not in response.text


async def test_readiness_checks_sql_and_closes_connection(client, monkeypatch):
    monkeypatch.setattr(settings, "database_url", SecretStr("postgresql+psycopg://probe:p%40ss%2Fword@db:5432/qosthub"))
    state = {"cursor_closed": False, "connection_closed": False, "queried": False}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            state["cursor_closed"] = True

        def execute(self, query):
            assert query == "SELECT 1"
            state["queried"] = True

        def fetchone(self):
            return (1,)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            state["connection_closed"] = True

        def cursor(self):
            return Cursor()

    def connect(dsn, **kwargs):
        from psycopg.conninfo import conninfo_to_dict
        parsed = conninfo_to_dict(dsn, **kwargs)
        assert parsed["password"] == "p@ss/word"
        assert parsed["connect_timeout"] == 3
        assert parsed["options"] == "-c statement_timeout=3000"
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert all(state.values())
