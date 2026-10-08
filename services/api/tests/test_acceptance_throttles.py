"""CI phases have separate login budgets without changing production limits."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy

import psycopg
import pytest
from sqlalchemy import func, select


INFRA = Path(__file__).resolve().parents[3] / "infra"
SCRIPT = INFRA / "reset_acceptance_throttles.py"


@pytest.fixture
def reset_module(monkeypatch):
    monkeypatch.syspath_prepend(str(INFRA))
    assert SCRIPT.is_file(), "The CI throttle reset is missing"
    return runpy.run_path(str(SCRIPT))


@pytest.fixture
def safe_environment(monkeypatch):
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://qosthub:synthetic@127.0.0.1:5432/qosthub_demo")
    monkeypatch.setenv("E2E_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("E2E_LOGIN", "e2e-worker")
    for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("key,value", [
    ("CI", None),
    ("CI", "false"),
    ("E2E_LOGIN", None),
    ("E2E_LOGIN", "production-worker"),
    ("E2E_LOGIN", "e2e-worker-production"),
    ("DATABASE_URL", None),
    ("DATABASE_URL", "postgresql://qosthub@localhost/qosthub"),
    ("DATABASE_URL", "postgresql://qosthub@localhost/qosthub_demo_prod"),
    ("DATABASE_URL", "postgresql://qosthub@remote.example/qosthub_demo"),
    ("DATABASE_URL", "postgresql://qosthub@localhost/qosthub_demo?hostaddr=192.0.2.1"),
    ("DATABASE_URL", "postgresql://qosthub@localhost/qosthub_demo?dbname=qosthub"),
    ("DATABASE_URL", "postgresql://qosthub@localhost/qosthub_demo#fragment"),
    ("E2E_BASE_URL", None),
    ("E2E_BASE_URL", "https://example.com"),
    ("E2E_BASE_URL", "http://localhost:5173?target=production"),
    ("PGHOSTADDR", "192.0.2.1"),
    ("PGSERVICE", "production"),
    ("PGSERVICEFILE", "production.conf"),
    ("PGOPTIONS", "-c search_path=production"),
])
def test_reset_refuses_unsafe_environment_before_connecting(
    reset_module, safe_environment, monkeypatch, key, value,
):
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)

    def forbidden_connect(*args, **kwargs):
        pytest.fail("Unsafe reset reached the database")

    monkeypatch.setattr(psycopg, "connect", forbidden_connect)
    with pytest.raises(SystemExit):
        reset_module["main"]()


@pytest.mark.parametrize("scheme,name", [
    ("postgresql+psycopg", "qosthub_demo"),
    ("postgresql", "qosthub_demo_t05"),
])
def test_reset_allows_only_validated_local_acceptance_targets(
    reset_module, safe_environment, monkeypatch, scheme, name,
):
    monkeypatch.setenv("DATABASE_URL", f"{scheme}://qosthub:synthetic@127.0.0.1:5432/{name}")

    class DatabaseCheckpoint(Exception):
        pass

    def checkpoint(database, *, connect_timeout):
        assert database == f"postgresql://qosthub:synthetic@127.0.0.1:5432/{name}"
        assert connect_timeout == 5
        raise DatabaseCheckpoint

    monkeypatch.setattr(psycopg, "connect", checkpoint)
    with pytest.raises(DatabaseCheckpoint):
        reset_module["main"]()


def test_reset_restores_login_budget_and_preserves_sessions(
    reset_module, database, safe_environment, monkeypatch, capsys,
):
    from app.core.security import AuthError, session_hash
    from app.modules.auth.models import AuthSession, AuthThrottle, User
    from app.modules.auth.service import enforce_limits

    db = database["session"]
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    session = AuthSession(
        token_hash=session_hash("synthetic-session"), csrf_token="synthetic-csrf",
        user_id=database["worker"].id, created_at=datetime.now(timezone.utc), expires_at=expires,
    )
    db.add(session)
    db.add(AuthThrottle(key=session_hash("login-ip:ci-client"), attempts=30, expires_at=expires))
    db.commit()
    with pytest.raises(AuthError) as denied:
        enforce_limits(db, [("login-ip:ci-client", 30, 900)])
    assert denied.value.status_code == 429
    users = db.scalar(select(func.count()).select_from(User))

    # The real SQL runs on this fixture's isolated qosthub_test* database; the CLI
    # guard still accepts only the two disposable acceptance database names.
    url = database["engine"].url.render_as_string(hide_password=False).replace("postgresql+psycopg://", "postgresql://", 1)
    connect = psycopg.connect
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: connect(url, **kwargs))
    reset_module["main"]()
    assert "synthetic" not in capsys.readouterr().out

    assert db.scalar(select(func.count()).select_from(AuthThrottle)) == 0
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 1
    assert db.scalar(select(func.count()).select_from(User)) == users
    enforce_limits(db, [("login-ip:ci-client", 30, 900)])
    db.commit()
    db.expire_all()
    assert db.scalar(select(AuthThrottle.attempts)) == 1
