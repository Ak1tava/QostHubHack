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
